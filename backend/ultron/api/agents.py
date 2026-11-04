"""Agentes e missões."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ultron.agents.runtime import run_agent
from ultron.api.common import row
from ultron.api.deps import current_user, owner
from ultron.db import get_session
from ultron.governance import audit
from ultron.missions.engine import MissionError, cancel_mission, create_mission
from ultron.models import AgentDefinition, AgentRun, Mission, MissionEvent, MissionTask, User
from ultron.tools.base import all_tools

router = APIRouter(prefix="/api", tags=["agents", "missions"])


class AgentRunIn(BaseModel):
    task: str = Field(min_length=3, max_length=20000)


class AgentPatch(BaseModel):
    status: str = Field(pattern="^(active|disabled)$")


class MissionIn(BaseModel):
    objective: str = Field(min_length=5, max_length=8000)
    priority: int = Field(default=5, ge=1, le=10)
    budget_usd: float | None = Field(default=None, gt=0, le=5)


@router.get("/agents")
async def list_agents(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    agents = (await session.execute(select(AgentDefinition).order_by(AgentDefinition.builtin.desc(),
                                                                     AgentDefinition.name))).scalars().all()
    stats = (await session.execute(select(AgentRun.agent_id, func.count(), func.sum(case((AgentRun.status == "failed", 1),
                                                                                          else_=0)),
                                          func.coalesce(func.sum(AgentRun.cost_usd), 0.0), func.max(AgentRun.started_at))
                                   .group_by(AgentRun.agent_id))).all()
    st = {a: {"runs": n, "failed": int(f or 0), "cost_usd": round(c or 0, 5), "last_run": m.isoformat() + "Z" if m
              else None} for a, n, f, c, m in stats}
    running = {a for (a,) in (await session.execute(select(AgentRun.agent_id).where(AgentRun.status == "running")))}
    tools = all_tools()
    return [{**row(a, exclude=("system_prompt",)), "stats": st.get(a.id, {"runs": 0, "failed": 0, "cost_usd": 0}),
             "working": a.id in running,
             "tool_details": [{"name": t, "scope": tools[t].scope, "description": tools[t].description}
                              for t in a.tools if t in tools]} for a in agents]


@router.get("/agents/{aid}/runs")
async def agent_runs(aid: str, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(AgentRun).where(AgentRun.agent_id == aid)
                                  .order_by(AgentRun.started_at.desc()).limit(30))).scalars().all()
    return [row(r) for r in rows]


@router.get("/agent-runs/{rid}")
async def get_run(rid: str, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    r = await session.get(AgentRun, rid)
    if r is None:
        raise HTTPException(404, "execução não encontrada")
    return row(r)


@router.patch("/agents/{aid}")
async def patch_agent(aid: str, body: AgentPatch, user: User = Depends(owner), session: AsyncSession = Depends(get_session)):
    a = await session.get(AgentDefinition, aid)
    if a is None:
        raise HTTPException(404, "agente não encontrado")
    if a.status == "pending_approval":
        raise HTTPException(400, "agente aguardando aprovação — decida em Aprovações")
    a.status = body.status
    await audit.record(f"user:{user.id}", "agent.status", aid, {"status": body.status}, session=session)
    return {"ok": True}


@router.post("/agents/{aid}/run")
async def run_agent_now(aid: str, body: AgentRunIn, user: User = Depends(current_user)):
    res = await run_agent(aid, body.task, user_id=user.id)
    return {"status": res.status, "output": res.output, "run_id": res.run_id, "cost_usd": res.cost_usd,
            "steps": res.steps, "models": res.models, "approval": res.approval}


@router.get("/missions")
async def list_missions(status: str | None = None, user: User = Depends(current_user),
                        session: AsyncSession = Depends(get_session)):
    q = select(Mission).order_by(Mission.created_at.desc()).limit(100)
    if status:
        q = q.where(Mission.status == status.upper())
    missions = (await session.execute(q)).scalars().all()
    counts = dict((await session.execute(select(MissionTask.mission_id, func.count()).group_by(MissionTask.mission_id))).all())
    return [{**row(m, exclude=("plan", "result", "review")), "tasks": counts.get(m.id, 0),
             "result_preview": (m.result or "")[:300]} for m in missions]


@router.post("/missions")
async def new_mission(body: MissionIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    try:
        m = await create_mission(session, body.objective, user_id=user.id, source="api", priority=body.priority,
                                 budget_usd=body.budget_usd)
    except MissionError as e:
        raise HTTPException(400, str(e))
    return row(m)


@router.get("/missions/{mid}")
async def get_mission(mid: str, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    m = await session.get(Mission, mid)
    if m is None:
        raise HTTPException(404, "missão não encontrada")
    tasks = (await session.execute(select(MissionTask).where(MissionTask.mission_id == mid)
                                   .order_by(MissionTask.position))).scalars().all()
    events = (await session.execute(select(MissionEvent).where(MissionEvent.mission_id == mid)
                                    .order_by(MissionEvent.ts.asc()))).scalars().all()
    return {**row(m), "tasks": [row(t) for t in tasks], "events": [row(e) for e in events]}


@router.post("/missions/{mid}/cancel")
async def cancel(mid: str, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    try:
        await cancel_mission(session, mid, f"user:{user.id}")
    except MissionError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@router.post("/missions/{mid}/retry")
async def retry(mid: str, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    m = await session.get(Mission, mid)
    if m is None or m.status not in ("FAILED", "CANCELLED"):
        raise HTTPException(400, "apenas missões falhas ou canceladas podem ser repetidas")
    tasks = (await session.execute(select(MissionTask).where(MissionTask.mission_id == mid))).scalars().all()
    for t in tasks:
        if t.status != "DONE":
            t.status = "PENDING"
            t.error = ""
    m.status = "RUNNING" if tasks else "RECEIVED"
    m.attempts = 0
    m.error = ""
    m.finished_at = None
    m.lease_owner = ""
    await audit.record(f"user:{user.id}", "mission.retry", mid, {}, session=session)
    return {"ok": True}
