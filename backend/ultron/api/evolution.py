"""Self-Evolution, aprovações e Development Workspace."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ultron.api.common import iso, row
from ultron.api.deps import current_user, owner
from ultron.config import get_settings
from ultron.db import get_session, session_scope
from ultron.evolution import sandbox
from ultron.evolution.cycle import PHASE_LABEL, PHASES, develop_now
from ultron.evolution.proposals import create_proposal
from ultron.evolution.publisher import PublishError, publish, rollback
from ultron.evolution.scheduler import scheduler
from ultron.evolution.selftest import run_selftest
from ultron.evolution.workspace import get_workspace
from ultron.governance import audit
from ultron.governance.approvals import ApprovalError, decide
from ultron.governance.policy import FORBIDDEN_PATHS, HIGH_RISK_PATHS, LOW_RISK_PATHS
from ultron.llm import budget as budget_mod
from ultron.models import (
    AgentDefinition,
    Approval,
    Diagnostic,
    Evaluation,
    EvolutionCycle,
    MetricPoint,
    Proposal,
    Publication,
    SandboxRun,
    User,
)
from ultron.security.passwords import verify_password
from ultron.settings_store import SettingPermissionError, get_many, set_setting, system_set

router = APIRouter(prefix="/api", tags=["evolution"])
_bg: set[asyncio.Task] = set()


def _spawn(coro) -> None:
    t = asyncio.create_task(coro)
    _bg.add(t)
    t.add_done_callback(_bg.discard)


class ProposalIn(BaseModel):
    title: str = Field(min_length=5, max_length=300)
    problem: str = Field(default="", max_length=8000)
    solution: str = Field(default="", max_length=8000)
    objective: str = Field(default="", max_length=4000)
    kind: str = "code"
    affected_files: list[str] = []
    acceptance_criteria: list[str] = []
    develop_now: bool = False


class EngineeringIn(BaseModel):
    question: str = Field(max_length=8000)
    decision_record: dict


class ToggleIn(BaseModel):
    enabled: bool
    password: str = ""


class DecisionIn(BaseModel):
    approve: bool
    reason: str = Field(default="", max_length=2000)
    password: str = Field(default="", max_length=200)


class RollbackIn(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


@router.get("/evolution/status")
async def evolution_status(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    st = await get_many(session, "evolution.")
    pub = await get_many(session, "publication.")
    current = (await session.execute(select(EvolutionCycle).where(EvolutionCycle.status.in_(("running", "interrupted")))
                                     .order_by(EvolutionCycle.started_at.desc()))).scalars().first()
    last = (await session.execute(select(EvolutionCycle).order_by(EvolutionCycle.started_at.desc()).limit(1))).scalars().first()
    counts = dict((await session.execute(select(Proposal.status, func.count()).group_by(Proposal.status))).all())
    pending = (await session.execute(select(func.count()).select_from(Approval).where(Approval.status == "pending"))
               ).scalar_one()
    open_diag = (await session.execute(select(func.count()).select_from(Diagnostic).where(Diagnostic.status == "open"))
                 ).scalar_one()
    b = await budget_mod.status(session)
    return {
        "enabled": st["evolution.enabled"], "paused": st["evolution.paused"],
        "interval_minutes": st["evolution.interval_minutes"],
        "auto_publish_low_risk": pub["publication.auto_publish_low_risk"],
        "safety_selftest": pub["publication.safety_selftest"],
        "current_cycle": row(current) if current else None,
        "last_cycle": row(last) if last else None,
        "phases": [{"id": p, "label": PHASE_LABEL[p]} for p in PHASES],
        "proposals_by_status": counts, "pending_approvals": pending, "open_diagnostics": open_diag,
        "scheduler": await scheduler.status(),
        "sandbox": {"isolation": sandbox.isolation_level(), "capabilities": sandbox.capabilities()},
        "budget": {"evolution_spent_usd": b["evolution_spent_usd"], "evolution_limit_usd": b["evolution_limit_usd"]},
        "settings": st,
        "runner": get_settings().evolution_runner,
    }


@router.post("/evolution/run")
async def run_now(user: User = Depends(owner)):
    try:
        cid = await scheduler.run_now()
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    await audit.record(f"user:{user.id}", "evolution.run_now", cid, {})
    return {"cycle_id": cid}


@router.post("/evolution/pause")
async def pause(user: User = Depends(owner), session: AsyncSession = Depends(get_session)):
    await system_set(session, "evolution.paused", True, f"user:{user.id}")
    return {"paused": True}


@router.post("/evolution/resume")
async def resume(user: User = Depends(owner), session: AsyncSession = Depends(get_session)):
    await system_set(session, "evolution.paused", False, f"user:{user.id}")
    return {"paused": False}


@router.post("/evolution/enabled")
async def set_enabled(body: ToggleIn, user: User = Depends(owner), session: AsyncSession = Depends(get_session)):
    await set_setting(session, "evolution.enabled", body.enabled, actor=f"user:{user.id}", actor_is_human_owner=True)
    return {"enabled": body.enabled}


@router.post("/evolution/autopublish")
async def autopublish(body: ToggleIn, user: User = Depends(owner), session: AsyncSession = Depends(get_session)):
    if body.enabled and not verify_password(body.password, user.password_hash):
        raise HTTPException(403, "confirme com sua senha para ativar a publicação automática")
    try:
        await set_setting(session, "publication.auto_publish_low_risk", body.enabled, actor=f"user:{user.id}",
                          actor_is_human_owner=True)
    except SettingPermissionError as e:
        raise HTTPException(400, str(e))
    return {"auto_publish_low_risk": body.enabled}


@router.post("/evolution/selftest")
async def selftest(user: User = Depends(owner)):
    return await run_selftest(f"user:{user.id}")


@router.get("/evolution/cycles")
async def cycles(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(EvolutionCycle).order_by(EvolutionCycle.started_at.desc()).limit(50))
            ).scalars().all()
    return [row(c, exclude=("checkpoint", "log")) for c in rows]


@router.get("/evolution/cycles/{cid}")
async def cycle(cid: str, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    c = await session.get(EvolutionCycle, cid)
    if c is None:
        raise HTTPException(404, "ciclo não encontrado")
    return row(c)


@router.post("/evolution/cycles/{cid}/cancel")
async def cancel_cycle(cid: str, user: User = Depends(owner), session: AsyncSession = Depends(get_session)):
    c = await session.get(EvolutionCycle, cid)
    if c is None or c.status not in ("running", "interrupted"):
        raise HTTPException(400, "ciclo não está em execução")
    c.status = "cancelled"
    await audit.record(f"user:{user.id}", "cycle.cancelled", cid, {}, session=session)
    return {"ok": True}


@router.get("/evolution/diagnostics")
async def list_diagnostics(status: str = "open", user: User = Depends(current_user),
                           session: AsyncSession = Depends(get_session)):
    q = select(Diagnostic).order_by(Diagnostic.last_seen_at.desc()).limit(200)
    if status != "all":
        q = q.where(Diagnostic.status == status)
    return [row(d) for d in (await session.execute(q)).scalars().all()]


@router.post("/evolution/diagnostics/{did}/ignore")
async def ignore_diag(did: str, user: User = Depends(owner), session: AsyncSession = Depends(get_session)):
    d = await session.get(Diagnostic, did)
    if d is None:
        raise HTTPException(404, "diagnóstico não encontrado")
    d.status = "ignored"
    return {"ok": True}


@router.get("/evolution/proposals")
async def list_proposals(status: str = "", user: User = Depends(current_user),
                         session: AsyncSession = Depends(get_session)):
    q = select(Proposal).order_by(Proposal.created_at.desc()).limit(200)
    if status:
        q = q.where(Proposal.status.in_(status.split(",")))
    return [row(p, exclude=("dev_log", "payload")) for p in (await session.execute(q)).scalars().all()]


@router.get("/evolution/proposals/{pid}")
async def get_proposal(pid: str, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    p = await session.get(Proposal, pid)
    if p is None:
        raise HTTPException(404, "proposta não encontrada")
    evals = (await session.execute(select(Evaluation).where(Evaluation.proposal_id == pid)
                                   .order_by(Evaluation.created_at.desc()))).scalars().all()
    runs = (await session.execute(select(SandboxRun).where(SandboxRun.proposal_id == pid)
                                  .order_by(SandboxRun.created_at.desc()).limit(30))).scalars().all()
    pubs = (await session.execute(select(Publication).where(Publication.proposal_id == pid))).scalars().all()
    approvals = (await session.execute(select(Approval).where(Approval.target_id == pid))).scalars().all()
    payload = dict(p.payload or {})
    tests = payload.pop("tests", None)
    return {**row(p, exclude=("payload",)), "payload": payload, "tests": tests, "evaluations": [row(e) for e in evals],
            "sandbox_runs": [row(r) for r in runs], "publications": [row(x) for x in pubs],
            "approvals": [row(a) for a in approvals]}


@router.post("/evolution/proposals")
async def new_proposal(body: ProposalIn, user: User = Depends(owner), session: AsyncSession = Depends(get_session)):
    p = await create_proposal(session, title=body.title, source="human", kind=body.kind, created_by=f"user:{user.id}",
                              problem=body.problem, solution=body.solution, objective=body.objective,
                              affected_files=body.affected_files, acceptance_criteria=body.acceptance_criteria,
                              severity="high", confidence=0.8)
    pid = p.id
    await session.commit()
    if body.develop_now:
        _spawn(develop_now(pid))
    return {"id": pid, "code": p.code, "status": p.status}


@router.post("/evolution/proposals/from-engineering")
async def from_engineering(body: EngineeringIn, user: User = Depends(owner), session: AsyncSession = Depends(get_session)):
    r = body.decision_record
    p = await create_proposal(session, title=str(r.get("decision") or body.question)[:300], source="human",
                              kind="code", created_by=f"user:{user.id}", problem=body.question,
                              solution=str(r.get("solution", "")), objective=str(r.get("decision", "")),
                              affected_files=[str(x) for x in r.get("affected_files") or []],
                              acceptance_criteria=[str(x) for x in r.get("acceptance_criteria") or []],
                              tests_required=[str(x) for x in r.get("tests_required") or []],
                              risks="; ".join(map(str, r.get("risks") or [])),
                              rollback_strategy=str(r.get("rollback_strategy") or "git revert do merge"),
                              declared_risk=str(r.get("risk_level") or ""), severity="high", confidence=0.8,
                              payload={"engineering_council": True})
    return {"id": p.id, "code": p.code}


@router.post("/evolution/proposals/{pid}/develop")
async def develop_proposal(pid: str, user: User = Depends(owner), session: AsyncSession = Depends(get_session)):
    p = await session.get(Proposal, pid)
    if p is None or p.status not in ("queued", "proposed", "failed"):
        raise HTTPException(400, "a proposta precisa estar na fila (ou falha) para ser desenvolvida")
    p.status = "queued"
    await audit.record(f"user:{user.id}", "proposal.develop_requested", p.code, {}, session=session)
    await session.commit()
    _spawn(develop_now(pid))
    return {"ok": True, "message": "desenvolvimento iniciado em segundo plano"}


@router.post("/evolution/proposals/{pid}/publish")
async def publish_now(pid: str, user: User = Depends(owner)):
    """Tenta publicar agora uma proposta já aprovada (ex.: após o CI do GitHub ficar verde)."""
    try:
        pub = await publish(pid, mode="approved", approved_by=f"user:{user.id}")
    except PublishError as e:
        raise HTTPException(400, str(e))
    return row(pub)


@router.post("/evolution/proposals/{pid}/reject")
async def reject_proposal(pid: str, user: User = Depends(owner), session: AsyncSession = Depends(get_session)):
    p = await session.get(Proposal, pid)
    if p is None or p.status == "published":
        raise HTTPException(400, "proposta inexistente ou já publicada")
    p.status = "rejected"
    await audit.record(f"user:{user.id}", "proposal.rejected", p.code, {}, session=session)
    return {"ok": True}


@router.post("/evolution/proposals/{pid}/requeue")
async def requeue(pid: str, user: User = Depends(owner), session: AsyncSession = Depends(get_session)):
    p = await session.get(Proposal, pid)
    if p is None or p.status not in ("failed", "rejected"):
        raise HTTPException(400, "só propostas falhas/rejeitadas voltam para a fila")
    p.status = "queued"
    p.error = ""
    return {"ok": True}


@router.get("/evolution/publications")
async def publications(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(Publication, Proposal.code, Proposal.title).join(
        Proposal, Proposal.id == Publication.proposal_id).order_by(Publication.published_at.desc()).limit(100))).all()
    return [{**row(p), "code": code, "title": title} for p, code, title in rows]


@router.post("/evolution/publications/{pub_id}/rollback")
async def do_rollback(pub_id: str, body: RollbackIn, user: User = Depends(owner)):
    try:
        pub = await rollback(pub_id, actor=f"user:{user.id}", reason=body.reason)
    except PublishError as e:
        raise HTTPException(400, str(e))
    return row(pub)


@router.get("/evolution/history")
async def history(name: str = "kpi.llm_error_rate", user: User = Depends(current_user),
                  session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(MetricPoint).where(MetricPoint.name == name)
                                  .order_by(MetricPoint.ts.desc()).limit(200))).scalars().all()
    return [{"ts": iso(r.ts), "value": r.value} for r in reversed(rows)]


@router.get("/evolution/policy")
async def policy(user: User = Depends(current_user)):
    return {"forbidden": FORBIDDEN_PATHS, "high": HIGH_RISK_PATHS, "low": LOW_RISK_PATHS,
            "rules": ["Baixo risco: documentação, interface, testes novos — publicação automática somente se ativada e "
                      "após autoteste", "Médio risco: integrações, agentes, banco, arquitetura — aprovação humana",
                      "Alto risco: autenticação, segurança, credenciais, permissões, dependências, infraestrutura — "
                      "aprovação humana obrigatória", "Caminhos protegidos: nenhum agente pode alterar"]}


# --------------------------------------------------------------------------- aprovações


@router.get("/approvals")
async def approvals(status: str = "pending", user: User = Depends(current_user),
                    session: AsyncSession = Depends(get_session)):
    q = select(Approval).order_by(Approval.created_at.desc()).limit(100)
    if status != "all":
        q = q.where(Approval.status == status)
    return [row(a) for a in (await session.execute(q)).scalars().all()]


@router.post("/approvals/{aid}/decide")
async def decide_approval(aid: str, body: DecisionIn, user: User = Depends(owner),
                          session: AsyncSession = Depends(get_session)):
    ap = await session.get(Approval, aid)
    if ap is None:
        raise HTTPException(404, "aprovação não encontrada")
    if body.approve and ap.risk == "high" and not verify_password(body.password, user.password_hash):
        raise HTTPException(403, "ações de alto risco exigem confirmação com sua senha")
    try:
        ap = await decide(session, aid, approve=body.approve, decided_by=f"user:{user.id}", reason=body.reason,
                          human=True)
    except ApprovalError as e:
        raise HTTPException(400, str(e))
    result: dict = {"status": ap.status}
    if ap.kind == "mission_action":
        from ultron.missions.engine import approve_task_action

        await approve_task_action(session, ap.target_id, body.approve)
    elif ap.kind == "agent_creation":
        agent = await session.get(AgentDefinition, ap.target_id)
        if agent:
            agent.status = "active" if body.approve else "disabled"
    elif ap.kind == "publication":
        p = await session.get(Proposal, ap.target_id)
        if p is not None:
            p.status = "approved" if body.approve else "rejected"
        await session.commit()
        if body.approve:
            async def _go(pid: str, actor: str) -> None:
                try:
                    await publish(pid, mode="approved", approved_by=actor)
                except Exception as e:  # registra qualquer falha na própria proposta (visível no app)
                    async with session_scope() as s:
                        prop = await s.get(Proposal, pid)
                        prop.error = f"publicação falhou: {e}"
                        if prop.status == "approved":
                            prop.status = "evaluated"
                    await audit.record(actor, "proposal.publish_failed", pid, {"error": str(e)[:500]})

            _spawn(_go(ap.target_id, f"user:{user.id}"))
            result["message"] = "publicação iniciada"
    return result


# --------------------------------------------------------------------------- workspace


@router.get("/workspace/status")
async def ws_status(user: User = Depends(current_user)):
    try:
        ws = await get_workspace()
    except Exception as e:
        return {"ready": False, "error": f"{e.__class__.__name__}: {e}"}
    return {"ready": ws.ready, "base_branch": ws.base_branch, "head": await ws.head(), "remote": bool(ws.remote_url),
            "push_enabled": bool(ws.token), "branches": await ws.branches("evolution/"), "log": await ws.log(n=15),
            "sandbox": {"isolation": sandbox.isolation_level(), "capabilities": sandbox.capabilities()}}


@router.post("/workspace/sync")
async def ws_sync(user: User = Depends(owner)):
    ws = await get_workspace()
    return await ws.sync()


@router.get("/workspace/tree")
async def ws_tree(path: str = ".", user: User = Depends(current_user)):
    ws = await get_workspace()
    try:
        return {"path": path, "entries": ws.list_dir(path)}
    except PermissionError as e:
        raise HTTPException(403, str(e))


@router.get("/workspace/file")
async def ws_file(path: str, user: User = Depends(current_user)):
    ws = await get_workspace()
    try:
        return {"path": path, "content": ws.read_text(path, max_chars=60000)}
    except PermissionError as e:
        raise HTTPException(403, str(e))


@router.get("/workspace/diff/{pid}")
async def ws_diff(pid: str, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    p = await session.get(Proposal, pid)
    if p is None or not p.branch:
        raise HTTPException(404, "proposta sem branch")
    ws = await get_workspace()
    try:
        return {"branch": p.branch, "diff": await ws.diff_text(p.base_sha, p.branch)}
    except Exception as e:
        raise HTTPException(404, f"diff indisponível: {e}")


@router.get("/workspace/sandbox-runs")
async def sandbox_runs(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(SandboxRun).order_by(SandboxRun.created_at.desc()).limit(60))).scalars().all()
    return [row(r) for r in rows]
