"""Configurações, uso/custos, segurança/auditoria e visão do sistema."""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ultron import __version__
from ultron.api.common import iso, row
from ultron.api.deps import current_user, owner
from ultron.config import get_settings
from ultron.db import get_session
from ultron.evolution import codeintel, sandbox
from ultron.evolution.observability import snapshot
from ultron.evolution.scheduler import scheduler
from ultron.evolution.workspace import get_workspace
from ultron.governance.audit import verify_chain
from ultron.governance.integrity import governance_fingerprint
from ultron.governance.permissions import ALL_SCOPES
from ultron.governance.policy import FORBIDDEN_PATHS
from ultron.llm import budget as budget_mod
from ultron.memory.service import stats as memory_stats
from ultron.models import (
    AgentDefinition,
    Approval,
    AuditLog,
    Conversation,
    Diagnostic,
    EvolutionCycle,
    LLMCall,
    Mission,
    Proposal,
    ToolCall,
    User,
)
from ultron.providers import registry
from ultron.settings_store import DEFAULTS, SettingPermissionError, get_many, set_setting
from ultron.utils import utcnow

router = APIRouter(prefix="/api", tags=["system"])


class SettingsIn(BaseModel):
    values: dict[str, Any]


@router.get("/health")
async def health_check():
    return {"status": "ok", "service": "ultron", "version": __version__}


_TUNNEL_HOST = re.compile(r"[a-z0-9-]{1,80}\.trycloudflare\.com")


@router.get("/system/access")
async def access_info(user: User = Depends(current_user)):
    """Endereço HTTPS temporário do túnel (instalação no notebook), para abrir o app no celular."""
    url = get_settings().tunnel_metrics_url
    host = ""
    if url:
        try:  # chamada interna fixa (configurada pelo operador), sem proxy
            async with httpx.AsyncClient(timeout=3, trust_env=False, follow_redirects=False) as c:
                r = await c.get(url)
            host = str((r.json() or {}).get("hostname") or "").strip().lower()
        except Exception:
            host = ""
    ok = bool(_TUNNEL_HOST.fullmatch(host))
    return {"tunnel_url": f"https://{host}" if ok else None, "tunnel_configured": bool(url)}


@router.get("/settings")
async def get_settings_api(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    s = get_settings()
    return {"values": await get_many(session), "defaults": DEFAULTS,
            "server": {"env": s.env, "monthly_budget_brl_env": s.monthly_budget_brl, "usd_brl_rate": s.usd_brl_rate,
                       "background": s.enable_background, "database": "postgresql" if "postgresql" in
                       s.resolved_database_url else "sqlite", "version": __version__}}


@router.put("/settings")
async def put_settings(body: SettingsIn, user: User = Depends(owner), session: AsyncSession = Depends(get_session)):
    errors = {}
    for k, v in body.values.items():
        if k == "publication.auto_publish_low_risk":
            errors[k] = "use Self-Evolution → Publicação automática (exige senha e autoteste)"
            continue
        try:
            await set_setting(session, k, v, actor=f"user:{user.id}", actor_is_human_owner=True)
        except (SettingPermissionError, KeyError) as e:
            errors[k] = str(e)
    if errors and len(errors) == len(body.values):
        raise HTTPException(400, {"errors": errors})
    registry.invalidate()
    budget_mod.clear_cache()
    return {"ok": True, "errors": errors}


@router.get("/usage")
async def usage(days: int = 30, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    from ultron import telemetry

    await telemetry.flush()
    status = await budget_mod.status(session)
    start = budget_mod.month_start()
    since = utcnow() - timedelta(days=max(1, min(90, days)))

    async def group(col):
        rows = (await session.execute(select(col, func.count(), func.coalesce(func.sum(LLMCall.cost_usd), 0.0),
                                             func.coalesce(func.sum(LLMCall.tokens_in + LLMCall.tokens_out), 0))
                                      .where(LLMCall.ts >= start).group_by(col)
                                      .order_by(func.sum(LLMCall.cost_usd).desc()))).all()
        return [{"key": k or "(geral)", "calls": n, "cost_usd": round(c, 5), "tokens": int(t)} for k, n, c, t in rows]

    daily_rows = (await session.execute(select(func.date(LLMCall.ts), func.coalesce(func.sum(LLMCall.cost_usd), 0.0),
                                               func.count()).where(LLMCall.ts >= since)
                                        .group_by(func.date(LLMCall.ts)).order_by(func.date(LLMCall.ts)))).all()
    by_model = (await session.execute(select(LLMCall.provider, LLMCall.model, func.count(),
                                             func.coalesce(func.sum(LLMCall.cost_usd), 0.0))
                                      .where(LLMCall.ts >= start).group_by(LLMCall.provider, LLMCall.model)
                                      .order_by(func.sum(LLMCall.cost_usd).desc()))).all()
    cached = (await session.execute(select(func.count()).select_from(LLMCall).where(LLMCall.ts >= start,
                                                                                    LLMCall.cached.is_(True)))).scalar_one()
    missions = (await session.execute(select(Mission.id, Mission.title, Mission.cost_usd, Mission.budget_usd)
                                      .where(Mission.created_at >= start).order_by(Mission.cost_usd.desc()).limit(10))).all()
    budgets = await get_many(session, "budget.")
    return {"budget": status, "budgets": budgets,
            "by_provider": await group(LLMCall.provider), "by_agent": await group(LLMCall.agent_id),
            "by_purpose": await group(LLMCall.purpose),
            "by_model": [{"key": f"{p}:{m}", "calls": n, "cost_usd": round(c, 5)} for p, m, n, c in by_model],
            "daily": [{"date": str(d), "cost_usd": round(c, 5), "calls": n} for d, c, n in daily_rows],
            "cache_hits": cached,
            "top_missions": [{"id": i, "title": t, "cost_usd": round(c or 0, 5), "budget_usd": b} for i, t, c, b in missions]}


@router.get("/audit")
async def audit_log(limit: int = 100, before: int | None = None, action: str = "", user: User = Depends(current_user),
                    session: AsyncSession = Depends(get_session)):
    q = select(AuditLog).order_by(AuditLog.seq.desc()).limit(max(1, min(500, limit)))
    if before:
        q = q.where(AuditLog.seq < before)
    if action:
        q = q.where(AuditLog.action.like(f"{action}%"))
    return [row(r) for r in (await session.execute(q)).scalars().all()]


@router.get("/audit/verify")
async def audit_verify(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return await verify_chain(session)


@router.get("/security/status")
async def security_status(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    vals = await get_many(session)
    since = utcnow() - timedelta(days=7)
    denied = (await session.execute(select(func.count()).select_from(ToolCall).where(ToolCall.ts >= since,
                                                                                     ToolCall.denied.is_(True)))).scalar_one()
    failed_logins = (await session.execute(select(func.count()).select_from(AuditLog).where(
        AuditLog.ts >= since, AuditLog.action == "auth.login_failed"))).scalar_one()
    s = get_settings()
    fp = governance_fingerprint()
    return {"governance_fingerprint": fp["combined"], "governance_files": fp["files"],
            "audit_chain": await verify_chain(session), "granted_scopes": vals["autonomy.granted_scopes"],
            "all_scopes": sorted(ALL_SCOPES), "forbidden_paths": FORBIDDEN_PATHS,
            "sandbox": {"isolation": sandbox.isolation_level(), "capabilities": sandbox.capabilities()},
            "selftest": vals["publication.safety_selftest"], "auto_publish": vals["publication.auto_publish_low_risk"],
            "denied_tool_calls_7d": denied, "failed_logins_7d": failed_logins,
            "production": s.is_production, "secret_key_from_env": bool(s.secret_key),
            "setup_token_configured": bool(s.setup_token)}


@router.get("/system/overview")
async def overview(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    from ultron import telemetry

    await telemetry.flush()
    handles = await registry.get_llm_handles(session)
    snap = await snapshot(session, hours=24)
    b = await budget_mod.status(session)
    count = lambda model, *conds: select(func.count()).select_from(model).where(*conds)  # noqa: E731
    active_missions = (await session.execute(count(Mission, Mission.status.in_(("RECEIVED", "PLANNING", "RUNNING",
                                                                                 "REVIEWING", "WAITING_APPROVAL"))))
                       ).scalar_one()
    recent_missions = (await session.execute(select(Mission).order_by(Mission.created_at.desc()).limit(5))).scalars().all()
    diags = (await session.execute(select(Diagnostic).where(Diagnostic.status == "open")
                                   .order_by(Diagnostic.last_seen_at.desc()).limit(6))).scalars().all()
    last_cycle = (await session.execute(select(EvolutionCycle).order_by(EvolutionCycle.started_at.desc()).limit(1))
                  ).scalars().first()
    vals = await get_many(session)
    return {
        "user": {"name": user.name},
        "providers": sorted(handles), "budget": b,
        "counts": {
            "conversations": (await session.execute(count(Conversation, Conversation.user_id == user.id))).scalar_one(),
            "active_missions": active_missions,
            "agents_active": (await session.execute(count(AgentDefinition, AgentDefinition.status == "active"))).scalar_one(),
            "memories": (await memory_stats(session, user.id))["total"],
            "pending_approvals": (await session.execute(count(Approval, Approval.status == "pending"))).scalar_one(),
            "open_diagnostics": (await session.execute(count(Diagnostic, Diagnostic.status == "open"))).scalar_one(),
            "proposals_queued": (await session.execute(count(Proposal, Proposal.status == "queued"))).scalar_one(),
            "published": (await session.execute(count(Proposal, Proposal.status == "published"))).scalar_one(),
        },
        "llm_24h": snap["llm"], "missions_24h": snap["missions"], "provider_health": snap["provider_health"],
        "recent_missions": [{"id": m.id, "title": m.title, "status": m.status, "cost_usd": m.cost_usd,
                             "created_at": iso(m.created_at)} for m in recent_missions],
        "diagnostics": [{"id": d.id, "title": d.title, "severity": d.severity, "category": d.category} for d in diags],
        "evolution": {"enabled": vals["evolution.enabled"], "paused": vals["evolution.paused"],
                      "auto_publish": vals["publication.auto_publish_low_risk"],
                      "last_cycle": row(last_cycle, exclude=("checkpoint", "log")) if last_cycle else None},
        "system": snap["system"],
    }


@router.get("/system/metrics")
async def metrics(hours: int = 24, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return await snapshot(session, hours=max(1, min(24 * 30, hours)))


@router.get("/system/architecture")
async def architecture(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    snap = await codeintel.latest_snapshot(session)
    if snap is None:
        return {"available": False}
    return {"available": True, **row(snap)}


@router.post("/system/architecture/refresh")
async def refresh_architecture(user: User = Depends(owner), session: AsyncSession = Depends(get_session)):
    ws = await get_workspace()
    await ws.sync()
    snap = await codeintel.refresh(session, ws.root, await ws.head(), force=True)
    return {"available": True, **row(snap)}


@router.get("/system/scheduler")
async def scheduler_status(user: User = Depends(current_user)):
    return await scheduler.status()
