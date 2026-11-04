"""Ciclo contínuo de autoevolução:

OBSERVAR → DIAGNOSTICAR → PESQUISAR → PLANEJAR → DESENVOLVER → TESTAR → AUDITAR →
PUBLICAR OU SOLICITAR APROVAÇÃO → MONITORAR

Cada fase grava um checkpoint; um ciclo interrompido é retomado da última fase concluída.
"""

from __future__ import annotations

import logging
import os
import socket
from datetime import timedelta

from sqlalchemy import func, select

from ultron import telemetry
from ultron.db import session_scope
from ultron.evolution import codeintel, developer, diagnostics, evaluation, proposals, publisher, sandbox
from ultron.evolution.observability import record_history, snapshot
from ultron.evolution.workspace import get_workspace
from ultron.governance import audit
from ultron.llm import budget as budget_mod
from ultron.models import Diagnostic, EvolutionCycle, LLMCall, Proposal
from ultron.providers import registry
from ultron.research.search import available_search_providers
from ultron.utils import truncate, utcnow

log = logging.getLogger("ultron.cycle")
PHASES = ("OBSERVE", "DIAGNOSE", "RESEARCH", "PLAN", "DEVELOP", "TEST", "AUDIT", "PUBLISH", "MONITOR")
PHASE_LABEL = {"OBSERVE": "Observar", "DIAGNOSE": "Diagnosticar", "RESEARCH": "Pesquisar", "PLAN": "Planejar",
               "DEVELOP": "Desenvolver", "TEST": "Testar", "AUDIT": "Auditar",
               "PUBLISH": "Publicar ou solicitar aprovação", "MONITOR": "Monitorar"}
WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"
LEASE_MIN = 30


class CycleStop(Exception):
    pass


async def create_cycle(trigger: str) -> str:
    from ultron.settings_store import get_setting

    async with session_scope() as s:
        running = (await s.execute(select(EvolutionCycle).where(EvolutionCycle.status == "running"))).scalars().first()
        if running:
            raise RuntimeError(f"já existe um ciclo em execução (#{running.number})")
        n = (await s.execute(select(func.count()).select_from(EvolutionCycle))).scalar_one()
        c = EvolutionCycle(number=n + 1, trigger=trigger, budget_usd=float(await get_setting(s, "evolution.cycle_budget_usd")
                                                                            or 0.4),
                           lease_owner=WORKER_ID, lease_expires_at=utcnow() + timedelta(minutes=LEASE_MIN))
        s.add(c)
        await s.flush()
        await audit.record("evolution_engine", "cycle.started", f"#{c.number}", {"trigger": trigger}, session=s)
        return c.id


async def _log(cycle_id: str, phase: str, message: str, data: dict | None = None) -> None:
    async with session_scope() as s:
        c = await s.get(EvolutionCycle, cycle_id)
        entry = {"ts": utcnow().isoformat() + "Z", "phase": phase, "message": truncate(message, 1000)}
        if data:
            entry["data"] = data
        c.log = [*(c.log or []), entry][-200:]
        c.lease_expires_at = utcnow() + timedelta(minutes=LEASE_MIN)


async def _checkpoint(cycle_id: str, phase: str, data: dict) -> None:
    async with session_scope() as s:
        c = await s.get(EvolutionCycle, cycle_id)
        ck = dict(c.checkpoint or {})
        ck[phase] = data
        c.checkpoint = ck
        c.completed_phases = [*(c.completed_phases or []), phase]
        await telemetry.flush()
        spent = (await s.execute(select(func.coalesce(func.sum(LLMCall.cost_usd), 0.0))
                                 .where(LLMCall.cycle_id == cycle_id))).scalar_one()
        c.cost_usd = float(spent or 0)


async def _guard(cycle_id: str, deadline) -> None:
    from ultron.settings_store import get_setting

    async with session_scope() as s:
        c = await s.get(EvolutionCycle, cycle_id)
        if c.status == "cancelled":
            raise CycleStop("ciclo cancelado")
        if await get_setting(s, "evolution.paused") or not await get_setting(s, "evolution.enabled"):
            raise CycleStop("autoevolução pausada")
    if utcnow() > deadline:
        raise CycleStop("tempo máximo do ciclo atingido")


async def _observe(cycle_id: str) -> dict:
    async with session_scope() as s:
        snap = await snapshot(s, hours=24)
        await record_history(s, snap)
        handles = await registry.get_llm_handles(s)
        search = [p for p in await available_search_providers(s) if p not in ("wikipedia", "duckduckgo")]
        bstatus = await budget_mod.status(s)
    ctx: dict = {"llm_providers": sorted(handles), "search_providers": search, "budget": bstatus,
                 "sandbox_network": "isolated" if sandbox.isolation_level() in ("namespace", "container")
                 else "not_isolated"}
    codemap_summary: dict = {}
    try:
        ws = await get_workspace()
        await ws.sync()
        head = await ws.head()
        ctx["github"] = bool(ws.token)
        async with session_scope() as s:
            snap_code = await codeintel.refresh(s, ws.root, head)
            data = {"summary": snap_code.summary, "modules": snap_code.modules, "edges": snap_code.edges,
                    "findings": snap_code.findings}
            codemap_summary = snap_code.summary
        doc = ws.root / codeintel.GENERATED_DOC
        ctx["doc_stale"] = (not doc.exists()) or doc.read_text() != codeintel.render_architecture_doc(data)
        base = await evaluation._baseline(ws, head)
        ctx["baseline_tests"] = {k: base.get(k) for k in ("passed", "failed", "errors", "tests", "failed_ids", "time_s")}
        ctx["head"] = head
        ctx["codemap"] = data
    except Exception as e:
        ctx["workspace_error"] = f"{e.__class__.__name__}: {e}"
        ctx["github"] = False
    return {"snapshot": snap, "ctx": ctx, "codemap_summary": codemap_summary}


async def run_cycle(cycle_id: str) -> dict:
    from ultron.settings_store import get_setting

    async with session_scope() as s:
        c = await s.get(EvolutionCycle, cycle_id)
        if c.status not in ("running", "interrupted"):
            return {"status": c.status}
        c.status = "running"
        c.lease_owner = WORKER_ID
        c.lease_expires_at = utcnow() + timedelta(minutes=LEASE_MIN)
        max_min = int(await get_setting(s, "evolution.cycle_max_minutes") or 25)
        max_props = int(await get_setting(s, "evolution.max_proposals_per_cycle") or 3)
        max_dev = int(await get_setting(s, "evolution.max_developments_per_cycle") or 1)
        research_on = bool(await get_setting(s, "evolution.research_enabled"))
        done = list(c.completed_phases or [])
        ck = dict(c.checkpoint or {})
        deadline = utcnow() + timedelta(minutes=max_min)
    state: dict = {}
    try:
        for phase in PHASES:
            if phase in done:
                continue
            await _guard(cycle_id, deadline)
            async with session_scope() as s:
                cyc = await s.get(EvolutionCycle, cycle_id)
                cyc.phase = phase
            await _log(cycle_id, phase, f"Iniciando fase: {PHASE_LABEL[phase]}")
            result: dict = {}
            if phase == "OBSERVE":
                obs = await _observe(cycle_id)
                state.update(obs)
                ctx = obs["ctx"]
                result = {"llm_calls_24h": obs["snapshot"]["llm"]["calls"],
                          "llm_error_rate": obs["snapshot"]["llm"]["error_rate"],
                          "providers": ctx.get("llm_providers"), "baseline_tests": ctx.get("baseline_tests"),
                          "code": obs["codemap_summary"], "workspace_error": ctx.get("workspace_error"),
                          "doc_stale": ctx.get("doc_stale"), "head": ctx.get("head"),
                          "sandbox_network": ctx.get("sandbox_network")}
            elif phase == "DIAGNOSE":
                if "snapshot" not in state:
                    state.update(await _observe(cycle_id))
                findings = diagnostics.analyze(state["snapshot"], state["ctx"], state["ctx"].get("codemap"))
                async with session_scope() as s:
                    result = await diagnostics.upsert(s, findings, cycle_id)
                result["top"] = [f.title for f in sorted(findings, key=lambda f: -diagnostics.SEVERITY_WEIGHT.get(
                    f.severity, 1))[:6]]
            elif phase == "RESEARCH":
                result = await _research(cycle_id, research_on)
            elif phase == "PLAN":
                code_ctx = ""
                if state.get("ctx", {}).get("codemap"):
                    cm = state["ctx"]["codemap"]
                    code_ctx = f"Resumo: {cm['summary']}\nMódulos: " + ", ".join(m["path"] for m in cm["modules"][:120])
                created = await proposals.generate_from_diagnostics(cycle_id, max_props, code_context=code_ctx)
                async with session_scope() as s:
                    queued = len(await proposals.queue(s))
                result = {"created": created, "queue": queued}
            elif phase == "DEVELOP":
                async with session_scope() as s:
                    q = [p.id for p in (await proposals.queue(s))[:max_dev]]
                devs = []
                for pid in q:
                    await _guard(cycle_id, deadline)
                    r = await developer.develop(pid, cycle_id)
                    devs.append({"proposal_id": pid, **r})
                    await _log(cycle_id, phase, f"Desenvolvimento {pid[:8]}: {r['status']}", r)
                result = {"developed": devs}
            elif phase == "TEST":
                ids = [d["proposal_id"] for d in result_of(cycle_id, ck, state, "DEVELOP").get("developed", [])
                       if d.get("status") == "testing"]
                tested = []
                for pid in ids:
                    await _guard(cycle_id, deadline)
                    t = await evaluation.test_candidate(pid)
                    tested.append({"proposal_id": pid, "candidate": {k: t["candidate"].get(k) for k in
                                                                    ("passed", "failed", "errors", "tests")}})
                result = {"tested": tested}
            elif phase == "AUDIT":
                ids = [t["proposal_id"] for t in result_of(cycle_id, ck, state, "TEST").get("tested", [])]
                evals = []
                for pid in ids:
                    ev = await evaluation.finalize(pid, cycle_id)
                    evals.append({"proposal_id": pid, "verdict": ev.verdict, "risk": ev.risk_level})
                result = {"evaluated": evals}
            elif phase == "PUBLISH":
                ids = [e["proposal_id"] for e in result_of(cycle_id, ck, state, "AUDIT").get("evaluated", [])
                       if e["verdict"] == "pass"]
                outcomes = []
                for pid in ids:
                    try:
                        outcomes.append({"proposal_id": pid, "outcome": await publisher.decide(pid)})
                    except Exception as e:
                        outcomes.append({"proposal_id": pid, "outcome": f"erro: {e}"})
                result = {"decisions": outcomes}
            elif phase == "MONITOR":
                result = {"monitored": await publisher.monitor()}
            state[phase] = result
            ck[phase] = result
            await _checkpoint(cycle_id, phase, result)
            await _log(cycle_id, phase, f"Fase concluída: {PHASE_LABEL[phase]}")
        summary = await _summary(cycle_id, ck)
        async with session_scope() as s:
            c = await s.get(EvolutionCycle, cycle_id)
            c.status = "completed"
            c.phase = "DONE"
            c.summary = summary
            c.finished_at = utcnow()
            c.lease_owner = ""
            await audit.record("evolution_engine", "cycle.completed", f"#{c.number}", {"cost_usd": c.cost_usd},
                               session=s)
        return {"status": "completed", "summary": summary}
    except CycleStop as e:
        async with session_scope() as s:
            c = await s.get(EvolutionCycle, cycle_id)
            c.status = "interrupted" if "pausada" in str(e) else ("cancelled" if "cancel" in str(e) else "completed")
            c.summary = f"Ciclo encerrado: {e}"
            c.finished_at = utcnow() if c.status != "interrupted" else None
            c.lease_owner = ""
        await _log(cycle_id, "STOP", str(e))
        return {"status": "stopped", "reason": str(e)}
    except Exception as e:
        log.exception("ciclo de evolução falhou")
        telemetry.record_error("evolution.cycle", f"{e.__class__.__name__}: {e}")
        async with session_scope() as s:
            c = await s.get(EvolutionCycle, cycle_id)
            c.status = "failed"
            c.error = f"{e.__class__.__name__}: {e}"
            c.finished_at = utcnow()
            c.lease_owner = ""
        return {"status": "failed", "error": str(e)}


def result_of(cycle_id: str, ck: dict, state: dict, phase: str) -> dict:
    return state.get(phase) or ck.get(phase) or {}


async def _research(cycle_id: str, enabled: bool) -> dict:
    if not enabled:
        return {"skipped": "pesquisa desativada"}
    async with session_scope() as s:
        if not await registry.get_llm_handles(s):
            return {"skipped": "sem provedor de IA"}
        rows = (await s.execute(select(Diagnostic).where(Diagnostic.status == "open",
                                                         Diagnostic.severity.in_(("high", "critical")),
                                                         Diagnostic.category.notin_(("capability", "security")),
                                                         Diagnostic.research == "").limit(1))).scalars().all()
        targets = [(d.id, d.title, d.detail) for d in rows]
    from ultron.research.service import deep_research

    done = []
    for did, title, detail in targets:
        rep = await deep_research(f"Como resolver em um sistema Python/FastAPI multiagente: {title}. {detail[:300]}",
                                  origin="evolution", cycle_id=cycle_id, max_sources=4)
        async with session_scope() as s:
            d = await s.get(Diagnostic, did)
            d.research = truncate(rep.summary or rep.error or "sem resultado", 4000)
        done.append({"diagnostic_id": did, "report_id": rep.id, "status": rep.status})
    return {"researched": done}


async def _summary(cycle_id: str, ck: dict) -> str:
    obs = ck.get("OBSERVE", {})
    dg = ck.get("DIAGNOSE", {})
    plan = ck.get("PLAN", {})
    dev = ck.get("DEVELOP", {}).get("developed", [])
    ev = ck.get("AUDIT", {}).get("evaluated", [])
    pub = ck.get("PUBLISH", {}).get("decisions", [])
    parts = [f"Observou {obs.get('llm_calls_24h', 0)} chamadas de IA (24h, erro {obs.get('llm_error_rate', 0):.0%})."]
    bt = obs.get("baseline_tests") or {}
    if bt:
        parts.append(f"Testes do branch estável: {bt.get('passed')} passando, {bt.get('failed')} falhando.")
    parts.append(f"Diagnósticos: {dg.get('created', 0)} novos, {dg.get('updated', 0)} recorrentes, "
                 f"{dg.get('resolved', 0)} resolvidos.")
    parts.append(f"Propostas criadas: {len(plan.get('created', []))} (fila: {plan.get('queue', 0)}).")
    if dev:
        parts.append(f"Desenvolvidas: {sum(1 for d in dev if d.get('status') == 'testing')} de {len(dev)}.")
    if ev:
        parts.append(f"Avaliadas: {sum(1 for e in ev if e['verdict'] == 'pass')} aprovadas, "
                     f"{sum(1 for e in ev if e['verdict'] != 'pass')} reprovadas.")
    if pub:
        parts.append("Publicação: " + ", ".join(f"{p['outcome']}" for p in pub) + ".")
    async with session_scope() as s:
        c = await s.get(EvolutionCycle, cycle_id)
        parts.append(f"Custo do ciclo: US$ {c.cost_usd:.4f}.")
    return " ".join(parts)


async def develop_now(proposal_id: str) -> dict:
    """Desenvolve e avalia uma proposta imediatamente (sem esperar o ciclo)."""
    r = await developer.develop(proposal_id)
    if r.get("status") != "testing":
        return r
    await evaluation.test_candidate(proposal_id)
    ev = await evaluation.finalize(proposal_id)
    out = {"status": "evaluated", "verdict": ev.verdict, "risk": ev.risk_level}
    if ev.verdict == "pass":
        out["decision"] = await publisher.decide(proposal_id)
    async with session_scope() as s:
        p = await s.get(Proposal, proposal_id)
        out["proposal_status"] = p.status
    return out
