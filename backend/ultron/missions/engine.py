"""MISSION ENGINE — missões longas em segundo plano, com plano em grafo (DAG), delegação a
agentes, checkpoints persistentes, retomada após interrupção, aprovação humana e revisão.

Estados: RECEIVED → PLANNING → RUNNING → REVIEWING → COMPLETED
         (WAITING_APPROVAL, FAILED e CANCELLED em qualquer ponto aplicável)
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ultron import telemetry
from ultron.agents.runtime import run_agent
from ultron.db import session_scope
from ultron.governance import audit
from ultron.governance.approvals import request_approval
from ultron.llm.budget import BudgetContext, BudgetExceeded
from ultron.llm.service import ChatMessage, NoProviderConfigured, TaskProfile, complete, complete_json
from ultron.models import AgentDefinition, Message, Mission, MissionEvent, MissionTask
from ultron.utils import truncate, utcnow

log = logging.getLogger("ultron.missions")

ACTIVE_STATES = ("RECEIVED", "PLANNING", "RUNNING", "REVIEWING")
TERMINAL_STATES = ("COMPLETED", "FAILED", "CANCELLED")
MAX_TASKS = 8
TASK_CONCURRENCY = 3
LEASE_SECONDS = 180
WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"

PLAN_PROMPT = """Você é o Director Agent do ULTRON. Planeje a missão abaixo dividindo-a em tarefas para os agentes
especializados. Use o MÍNIMO de tarefas necessário (1 a {max_tasks}). Tarefas independentes podem rodar em paralelo;
use "depends_on" quando uma precisa do resultado de outra. Declare em "writes" recursos que a tarefa altera
(ex.: "memory", "workspace") para evitar conflitos de escrita.

Agentes disponíveis:
{agents}

Responda em JSON:
{{"title": "título curto", "strategy": "estratégia em 1-2 frases",
 "tasks": [{{"key": "t1", "title": "...", "agent": "id_do_agente", "instructions": "instruções completas e autocontidas",
            "depends_on": [], "writes": []}}]}}"""

REVIEW_PROMPT = """Você é o revisor independente de missões do ULTRON. Avalie se o resultado consolidado atende ao
objetivo. Seja crítico e baseado em evidências. Responda em JSON:
{"meets_objective": true|false, "score": 0-10, "issues": ["problemas concretos"], "missing": ["o que faltou"]}"""

CONSOLIDATE_PROMPT = """Você é o Director Agent do ULTRON. Consolide os resultados das tarefas em uma entrega final clara
para o usuário, em português do Brasil, com markdown. Não invente nada além dos resultados. Indique limitações."""


class MissionError(Exception):
    pass


async def add_event(session: AsyncSession, mission_id: str, type_: str, message: str, data: dict | None = None) -> None:
    session.add(MissionEvent(mission_id=mission_id, type=type_, message=truncate(message, 2000), data=data or {}))


async def create_mission(session: AsyncSession, objective: str, *, user_id: str | None, source: str = "api",
                         priority: int = 5, budget_usd: float | None = None, conversation_id: str | None = None,
                         title: str = "") -> Mission:
    from ultron.settings_store import get_setting

    objective = (objective or "").strip()
    if len(objective) < 5:
        raise MissionError("descreva o objetivo da missão")
    default_budget = float(await get_setting(session, "budget.per_mission_usd") or 0.3)
    m = Mission(objective=truncate(objective, 8000), user_id=user_id, source=source, priority=max(1, min(10, priority)),
                budget_usd=min(float(budget_usd or default_budget), 5.0), conversation_id=conversation_id,
                title=title or truncate(objective.replace("\n", " "), 80))
    session.add(m)
    await session.flush()
    await add_event(session, m.id, "received", "Missão recebida")
    await audit.record(f"user:{user_id}" if user_id else "system", "mission.created", m.id,
                       {"source": source, "budget_usd": m.budget_usd}, session=session)
    return m


def validate_plan(plan: dict, agent_ids: set[str]) -> list[dict]:
    tasks = plan.get("tasks") if isinstance(plan, dict) else None
    if not isinstance(tasks, list) or not tasks:
        raise MissionError("plano sem tarefas")
    out: list[dict] = []
    keys: set[str] = set()
    for i, t in enumerate(tasks[:MAX_TASKS]):
        if not isinstance(t, dict):
            continue
        key = str(t.get("key") or f"t{i + 1}")[:40]
        if key in keys:
            key = f"{key}_{i}"
        keys.add(key)
        agent = str(t.get("agent") or "").strip()
        if agent not in agent_ids:
            agent = "analyst" if "analyst" in agent_ids else next(iter(agent_ids))
        out.append({"key": key, "title": truncate(str(t.get("title") or key), 200), "agent": agent,
                    "instructions": truncate(str(t.get("instructions") or t.get("title") or ""), 4000),
                    "depends_on": [str(d) for d in (t.get("depends_on") or [])],
                    "writes": [str(w) for w in (t.get("writes") or [])][:5]})
    for t in out:
        t["depends_on"] = [d for d in t["depends_on"] if d in keys and d != t["key"]]
    # detecção de ciclos (Kahn)
    indeg = {t["key"]: len(t["depends_on"]) for t in out}
    children: dict[str, list[str]] = {t["key"]: [] for t in out}
    for t in out:
        for d in t["depends_on"]:
            children[d].append(t["key"])
    queue = [k for k, v in indeg.items() if v == 0]
    seen = 0
    while queue:
        k = queue.pop()
        seen += 1
        for c in children[k]:
            indeg[c] -= 1
            if indeg[c] == 0:
                queue.append(c)
    if seen != len(out):
        raise MissionError("plano contém dependências circulares")
    return out


class _ResourceLocks:
    """Evita conflitos de escrita: tarefas que escrevem o mesmo recurso não rodam juntas."""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}

    def get(self, name: str) -> asyncio.Lock:
        return self._locks.setdefault(name, asyncio.Lock())


resource_locks = _ResourceLocks()


async def _claim(mission_id: str) -> bool:
    async with session_scope() as s:
        m = await s.get(Mission, mission_id)
        now = utcnow()
        if m is None or m.status not in ACTIVE_STATES:
            return False
        if m.lease_owner and m.lease_owner != WORKER_ID and m.lease_expires_at and m.lease_expires_at > now:
            return False
        m.lease_owner = WORKER_ID
        m.lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
        return True


async def _renew(mission_id: str) -> None:
    async with session_scope() as s:
        m = await s.get(Mission, mission_id)
        if m and m.lease_owner == WORKER_ID:
            m.lease_expires_at = utcnow() + timedelta(seconds=LEASE_SECONDS)


async def _set_status(mission_id: str, status: str, message: str, **fields) -> None:
    async with session_scope() as s:
        m = await s.get(Mission, mission_id)
        m.status = status
        for k, v in fields.items():
            setattr(m, k, v)
        if status in TERMINAL_STATES:
            m.finished_at = utcnow()
            m.lease_owner = ""
        if status == "WAITING_APPROVAL":
            m.lease_owner = ""
        await add_event(s, mission_id, status.lower(), message)


async def _is_cancelled(mission_id: str) -> bool:
    async with session_scope() as s:
        m = await s.get(Mission, mission_id)
        return m is None or m.status == "CANCELLED"


async def _agents_catalog() -> tuple[str, set[str]]:
    async with session_scope() as s:
        rows = (await s.execute(select(AgentDefinition).where(AgentDefinition.status == "active"))).scalars().all()
    lines = [f"- {a.id}: {a.role} — {truncate(a.description, 160)} (ferramentas: {', '.join(a.tools)})" for a in rows]
    return "\n".join(lines), {a.id for a in rows}


async def plan_mission(mission_id: str, feedback: str = "") -> None:
    async with session_scope() as s:
        m = await s.get(Mission, mission_id)
        objective, budget_ctx = m.objective, BudgetContext(purpose="mission.plan", agent_id="director", mission_id=m.id)
        m.status = "PLANNING"
        m.started_at = m.started_at or utcnow()
        await add_event(s, m.id, "planning", "Director Agent elaborando o plano")
    catalog, ids = await _agents_catalog()
    prompt = PLAN_PROMPT.format(agents=catalog, max_tasks=MAX_TASKS)
    user = f"MISSÃO:\n{objective}" + (f"\n\nREPLANEJAMENTO — problemas da tentativa anterior:\n{feedback}" if feedback else "")
    try:
        data, res = await complete_json([ChatMessage("system", prompt), ChatMessage("user", user)],
                                        TaskProfile(task="plan", tier="balanced"), ctx=budget_ctx, max_tokens=2500)
        tasks = validate_plan(data, ids)
        plan = {"title": str((data or {}).get("title") or ""), "strategy": str((data or {}).get("strategy") or ""),
                "planner_model": f"{res.provider}:{res.model}"}
    except MissionError as e:
        tasks = [{"key": "t1", "title": "Executar objetivo", "agent": "director", "instructions": objective,
                  "depends_on": [], "writes": []}]
        plan = {"title": "", "strategy": f"plano simplificado ({e})"}
        res = None
    async with session_scope() as s:
        m = await s.get(Mission, mission_id)
        prev = (await s.execute(select(MissionTask).where(MissionTask.mission_id == mission_id))).scalars().all()
        offset = len(prev)
        # tarefas antigas falhas/puladas ficam no histórico; o novo plano recebe chaves novas
        prefix = f"r{m.attempts}_" if prev else ""
        for i, t in enumerate(tasks):
            s.add(MissionTask(mission_id=mission_id, key=prefix + t["key"], title=t["title"], agent_id=t["agent"],
                              instructions=t["instructions"], depends_on=[prefix + d for d in t["depends_on"]],
                              resources=t["writes"], position=offset + i))
        plan["approved_actions"] = (m.plan or {}).get("approved_actions", [])
        plan["rounds"] = (m.plan or {}).get("rounds", 0) + 1
        m.plan = plan
        if res is not None:
            m.cost_usd = (m.cost_usd or 0) + res.cost_usd
        if plan.get("title") and not m.title:
            m.title = plan["title"][:200]
        m.status = "RUNNING"
        await add_event(s, mission_id, "planned", f"Plano com {len(tasks)} tarefa(s): " +
                        "; ".join(f"{t['key']}→{t['agent']}" for t in tasks), {"tasks": tasks})


async def _run_task(mission_id: str, task_id: str, approved: set[str], user_id: str | None) -> None:
    async with session_scope() as s:
        t = await s.get(MissionTask, task_id)
        deps = (await s.execute(select(MissionTask).where(MissionTask.mission_id == mission_id,
                                                          MissionTask.key.in_(t.depends_on or [])))).scalars().all()
        m = await s.get(Mission, mission_id)
        context = f"OBJETIVO DA MISSÃO:\n{m.objective}"
        for d in deps:
            context += f"\n\nRESULTADO DA TAREFA '{d.title}' ({d.agent_id}):\n{truncate(d.output, 3500)}"
        t.status = "RUNNING"
        t.started_at = utcnow()
        t.attempts += 1
        agent_id, instructions, resources = t.agent_id, t.instructions, list(t.resources or [])
        await add_event(s, mission_id, "task_started", f"{t.key}: {t.title} → {agent_id}", {"task_id": t.id})
    locks = [resource_locks.get(f"{r}") for r in sorted(set(resources))]
    for lk in locks:
        await lk.acquire()
    try:
        result = await run_agent(agent_id, instructions, context=context, user_id=user_id, mission_id=mission_id,
                                 task_id=task_id, approved_actions=approved)
    finally:
        for lk in reversed(locks):
            lk.release()
    async with session_scope() as s:
        t = await s.get(MissionTask, task_id)
        m = await s.get(Mission, mission_id)
        t.agent_run_id = result.run_id
        t.cost_usd = (t.cost_usd or 0) + result.cost_usd
        m.cost_usd = (m.cost_usd or 0) + result.cost_usd
        t.finished_at = utcnow()
        if result.status == "completed":
            t.status = "DONE"
            t.output = truncate(result.output, 20000)
            await add_event(s, mission_id, "task_done", f"{t.key} concluída", {"task_id": t.id, "cost": result.cost_usd})
        elif result.status == "needs_approval":
            t.status = "WAITING_APPROVAL"
            t.output = result.output
            ap = await request_approval(s, kind="mission_action", target_type="mission_task", target_id=t.id,
                                        risk="high", title=f"Missão '{truncate(m.title, 60)}' pede ação sensível",
                                        summary=(result.approval or {}).get("summary", ""), details=result.approval or {},
                                        requested_by=f"agent:{t.agent_id}")
            await add_event(s, mission_id, "approval_requested", f"{t.key} aguarda aprovação", {"approval_id": ap.id})
        else:
            t.status = "FAILED"
            t.error = truncate(result.output, 4000)
            await add_event(s, mission_id, "task_failed", f"{t.key} falhou: {truncate(result.output, 300)}",
                            {"task_id": t.id})


async def _execute_dag(mission_id: str, user_id: str | None) -> str:
    """Executa tarefas prontas em paralelo até concluir, falhar ou precisar de aprovação."""
    sem = asyncio.Semaphore(TASK_CONCURRENCY)
    while True:
        if await _is_cancelled(mission_id):
            return "CANCELLED"
        await _renew(mission_id)
        async with session_scope() as s:
            m = await s.get(Mission, mission_id)
            approved = set((m.plan or {}).get("approved_actions", []))
            tasks = (await s.execute(select(MissionTask).where(MissionTask.mission_id == mission_id)
                                     .order_by(MissionTask.position))).scalars().all()
            status = {t.key: t.status for t in tasks}
            for t in tasks:
                if t.status == "PENDING" and any(status.get(d) in ("FAILED", "SKIPPED") for d in t.depends_on or []):
                    t.status = "SKIPPED"
                    t.error = "dependência falhou"
                    status[t.key] = "SKIPPED"
            ready = [t.id for t in tasks if t.status == "PENDING"
                     and all(status.get(d) == "DONE" for d in t.depends_on or [])]
            waiting = any(t.status == "WAITING_APPROVAL" for t in tasks)
            pending = any(t.status in ("PENDING", "RUNNING") for t in tasks)
        if not ready:
            if waiting:
                return "WAITING_APPROVAL"
            if pending:
                return "STALLED"
            return "DONE"

        async def _guarded(tid: str) -> None:
            async with sem:
                await _run_task(mission_id, tid, approved, user_id)

        await asyncio.gather(*[_guarded(tid) for tid in ready])


async def _review_and_consolidate(mission_id: str) -> tuple[bool, str, dict]:
    async with session_scope() as s:
        m = await s.get(Mission, mission_id)
        m.status = "REVIEWING"
        await add_event(s, mission_id, "reviewing", "Consolidando e revisando o resultado")
        tasks = (await s.execute(select(MissionTask).where(MissionTask.mission_id == mission_id,
                                                           MissionTask.status == "DONE")
                                 .order_by(MissionTask.position))).scalars().all()
        objective = m.objective
        results = "\n\n".join(f"### {t.title} ({t.agent_id})\n{truncate(t.output, 5000)}" for t in tasks)
    ctx = BudgetContext(purpose="mission.review", agent_id="director", mission_id=mission_id)
    if len(tasks) == 1:
        final = tasks[0].output
        cost = 0.0
    else:
        r = await complete([ChatMessage("system", CONSOLIDATE_PROMPT),
                            ChatMessage("user", f"OBJETIVO:\n{objective}\n\nRESULTADOS:\n{results}")],
                           TaskProfile(task="summarize", tier="balanced"), ctx=ctx, max_tokens=3000)
        final, cost = r.text, r.cost_usd
    review: dict = {}
    try:
        data, rr = await complete_json([ChatMessage("system", REVIEW_PROMPT),
                                        ChatMessage("user", f"OBJETIVO:\n{objective}\n\nRESULTADO:\n{truncate(final, 8000)}")],
                                       TaskProfile(task="critique", tier="fast"), ctx=ctx, max_tokens=800)
        review = data if isinstance(data, dict) else {}
        review["model"] = f"{rr.provider}:{rr.model}"
        cost += rr.cost_usd
    except Exception as e:
        review = {"meets_objective": True, "error": f"revisão indisponível: {e}"}
    async with session_scope() as s:
        m = await s.get(Mission, mission_id)
        m.cost_usd = (m.cost_usd or 0) + cost
    ok = bool(review.get("meets_objective", True))
    return ok, final, review


async def process_mission(mission_id: str) -> str:
    """Processa (ou retoma) uma missão. Idempotente a partir de qualquer checkpoint."""
    if not await _claim(mission_id):
        return "skipped"
    try:
        async with session_scope() as s:
            m = await s.get(Mission, mission_id)
            user_id = m.user_id
            # retomada: tarefas que estavam rodando quando o processo caiu voltam para PENDING
            stale = (await s.execute(select(MissionTask).where(MissionTask.mission_id == mission_id,
                                                               MissionTask.status == "RUNNING"))).scalars().all()
            for t in stale:
                t.status = "PENDING"
                await add_event(s, mission_id, "resumed", f"Tarefa {t.key} retomada após interrupção")
            has_tasks = (await s.execute(select(MissionTask.id).where(MissionTask.mission_id == mission_id)
                                         .limit(1))).first() is not None
            status = m.status
        if status in ("RECEIVED", "PLANNING") or not has_tasks:
            await plan_mission(mission_id)
        while True:
            outcome = await _execute_dag(mission_id, user_id)
            if outcome == "CANCELLED":
                return "CANCELLED"
            if outcome == "WAITING_APPROVAL":
                await _set_status(mission_id, "WAITING_APPROVAL", "Aguardando aprovação humana")
                return "WAITING_APPROVAL"
            async with session_scope() as s:
                m = await s.get(Mission, mission_id)
                tasks = (await s.execute(select(MissionTask).where(MissionTask.mission_id == mission_id))).scalars().all()
                failed = [t for t in tasks if t.status in ("FAILED", "SKIPPED") and not t.key.startswith("x_")]
                done = [t for t in tasks if t.status == "DONE"]
                attempts, max_attempts = m.attempts, m.max_attempts
            current_round_failed = [t for t in failed if t.status == "FAILED"]
            if current_round_failed and attempts + 1 < max_attempts:
                feedback = "\n".join(f"- {t.title} ({t.agent_id}): {truncate(t.error, 400)}" for t in current_round_failed)
                if done:
                    feedback += "\n\nTarefas já concluídas (NÃO repita; use apenas para completar o que falhou):\n" + \
                        "\n".join(f"- {t.title}" for t in done)
                async with session_scope() as s:
                    m = await s.get(Mission, mission_id)
                    m.attempts += 1
                    for t in tasks:
                        if t.status in ("FAILED", "SKIPPED"):
                            obj = await s.get(MissionTask, t.id)
                            obj.key = "x_" + obj.key  # arquiva a tentativa
                    await add_event(s, mission_id, "replanning", "Falhas detectadas — replanejando", {"feedback": feedback})
                await plan_mission(mission_id, feedback)
                continue
            if not done:
                await _set_status(mission_id, "FAILED", "Nenhuma tarefa concluída",
                                  error="; ".join(truncate(t.error, 200) for t in failed[:3]))
                return "FAILED"
            ok, final, review = await _review_and_consolidate(mission_id)
            async with session_scope() as s:
                m = await s.get(Mission, mission_id)
                attempts = m.attempts
            if not ok and attempts + 1 < max_attempts and (review.get("issues") or review.get("missing")):
                async with session_scope() as s:
                    m = await s.get(Mission, mission_id)
                    m.attempts += 1
                    m.review = review
                    await add_event(s, mission_id, "review_failed", "Revisão apontou problemas — nova rodada",
                                    {"review": review})
                feedback = "Problemas: " + "; ".join(map(str, review.get("issues", []) + review.get("missing", [])))
                await plan_mission(mission_id, feedback)
                continue
            await _set_status(mission_id, "COMPLETED", "Missão concluída", result=final, review=review)
            await _after_completion(mission_id)
            return "COMPLETED"
    except BudgetExceeded as e:
        await _set_status(mission_id, "FAILED", f"Orçamento: {e}", error=str(e))
        return "FAILED"
    except NoProviderConfigured as e:
        await _set_status(mission_id, "FAILED", str(e), error=str(e))
        return "FAILED"
    except Exception as e:
        log.exception("falha na missão %s", mission_id)
        telemetry.record_error("mission", f"{e.__class__.__name__}: {e}")
        await _set_status(mission_id, "FAILED", f"Erro interno: {e}", error=f"{e.__class__.__name__}: {e}")
        return "FAILED"


async def _after_completion(mission_id: str) -> None:
    from ultron.memory.service import remember

    async with session_scope() as s:
        m = await s.get(Mission, mission_id)
        telemetry.record_metric("mission.completed", 1, {"source": m.source})
        try:
            await remember(s, f"Missão concluída: {truncate(m.objective, 300)} → {truncate(m.result, 600)}",
                           kind="task", status="confirmed", user_id=m.user_id, source=f"mission:{m.id}",
                           importance=0.5)
        except Exception:
            pass
        if m.conversation_id:
            s.add(Message(conversation_id=m.conversation_id, role="assistant", mode="MISSION",
                          content=f"**Missão concluída:** {m.title}\n\n{m.result}",
                          meta={"mission_id": m.id, "review": m.review}, cost_usd=m.cost_usd))


async def approve_task_action(session: AsyncSession, task_id: str, approve: bool) -> None:
    """Chamado após a decisão humana sobre uma ação sensível de missão."""
    t = await session.get(MissionTask, task_id)
    if t is None:
        return
    m = await session.get(Mission, t.mission_id)
    if approve:
        from ultron.models import Approval

        ap = (await session.execute(select(Approval).where(Approval.target_id == task_id)
                                    .order_by(Approval.created_at.desc()))).scalars().first()
        key = (ap.details or {}).get("action_key") if ap else None
        plan = dict(m.plan or {})
        plan["approved_actions"] = list(set(plan.get("approved_actions", []) + ([key] if key else [])))
        m.plan = plan
        t.status = "PENDING"
        m.status = "RUNNING"
        await add_event(session, m.id, "approved", f"Ação da tarefa {t.key} aprovada — retomando")
    else:
        t.status = "FAILED"
        t.error = "ação rejeitada pelo proprietário"
        m.status = "RUNNING"
        await add_event(session, m.id, "rejected", f"Ação da tarefa {t.key} rejeitada")


async def cancel_mission(session: AsyncSession, mission_id: str, actor: str) -> Mission:
    m = await session.get(Mission, mission_id)
    if m is None:
        raise MissionError("missão não encontrada")
    if m.status in TERMINAL_STATES:
        raise MissionError(f"missão já finalizada ({m.status})")
    m.status = "CANCELLED"
    m.finished_at = utcnow()
    await add_event(session, mission_id, "cancelled", f"Cancelada por {actor}")
    await audit.record(actor, "mission.cancelled", mission_id, {}, session=session)
    return m


# --------------------------------------------------------------------------- worker


class MissionWorker:
    def __init__(self, concurrency: int = 2, poll_seconds: float = 3.0):
        self.concurrency = concurrency
        self.poll = poll_seconds
        self._running: dict[str, asyncio.Task] = {}
        self._stop = asyncio.Event()

    async def tick(self) -> int:
        self._running = {k: v for k, v in self._running.items() if not v.done()}
        free = self.concurrency - len(self._running)
        if free <= 0:
            return 0
        now = utcnow()
        async with session_scope() as s:
            rows = (await s.execute(
                select(Mission.id).where(Mission.status.in_(ACTIVE_STATES),
                                         or_(Mission.lease_owner == "", Mission.lease_expires_at.is_(None),
                                             Mission.lease_expires_at < now, Mission.lease_owner == WORKER_ID))
                .order_by(Mission.priority.desc(), Mission.created_at.asc()).limit(free + len(self._running))
            )).scalars().all()
        started = 0
        for mid in rows:
            if mid in self._running or len(self._running) >= self.concurrency:
                continue
            self._running[mid] = asyncio.create_task(process_mission(mid))
            started += 1
        return started

    async def run_forever(self) -> None:
        while not self._stop.is_set():
            try:
                await self.tick()
            except Exception:  # pragma: no cover
                log.exception("worker de missões")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.poll)
            except TimeoutError:
                pass

    async def stop(self) -> None:
        self._stop.set()
        for t in self._running.values():
            t.cancel()
        for t in self._running.values():
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass


worker = MissionWorker()
