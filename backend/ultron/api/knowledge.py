"""Memória e pesquisa."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ultron.api.common import row
from ultron.api.deps import current_user
from ultron.db import get_session
from ultron.governance import audit
from ultron.memory.service import KINDS, STATUSES, MemoryError_, apply_retention, forget, recall, remember, stats
from ultron.models import MemoryItem, ResearchReport, User
from ultron.research.service import deep_research

router = APIRouter(prefix="/api", tags=["memory", "research"])
_bg: set[asyncio.Task] = set()


class MemoryIn(BaseModel):
    content: str = Field(min_length=2, max_length=8000)
    kind: str = "semantic"
    status: str = "confirmed"
    tags: list[str] = []
    importance: float = Field(default=0.6, ge=0, le=1)
    access_scope: str = Field(default="agents", pattern="^(agents|private)$")


class MemoryPatch(BaseModel):
    status: str | None = None
    content: str | None = Field(default=None, max_length=8000)
    access_scope: str | None = Field(default=None, pattern="^(agents|private)$")


class ResearchIn(BaseModel):
    query: str = Field(min_length=3, max_length=2000)


def mem_out(m: MemoryItem, score: float | None = None) -> dict:
    d = row(m, exclude=("embedding_local", "embedding", "content_hash"))
    if score is not None:
        d["score"] = score
    return d


@router.get("/memory")
async def list_memory(q: str = "", kind: str = "", status: str = "", limit: int = 50,
                      user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    limit = max(1, min(200, limit))
    if q.strip():
        items = await recall(session, q, user_id=user.id, kinds=[kind] if kind else None, limit=limit, min_score=0.02)
        return [mem_out(m, s) for m, s in items if not status or m.status == status]
    query = select(MemoryItem).where((MemoryItem.user_id == user.id) | (MemoryItem.user_id.is_(None)))
    if kind:
        query = query.where(MemoryItem.kind == kind)
    if status:
        query = query.where(MemoryItem.status == status)
    rows = (await session.execute(query.order_by(MemoryItem.updated_at.desc()).limit(limit))).scalars().all()
    return [mem_out(m) for m in rows]


@router.get("/memory/stats")
async def memory_stats(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    from ultron.settings_store import get_setting

    return {**await stats(session, user.id), "kinds": KINDS, "statuses": STATUSES,
            "retention_days": await get_setting(session, "memory.retention_days")}


@router.post("/memory")
async def add_memory(body: MemoryIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    try:
        m = await remember(session, body.content, kind=body.kind, status=body.status, user_id=user.id, tags=body.tags,
                           source="usuário", importance=body.importance, access_scope=body.access_scope)
    except MemoryError_ as e:
        raise HTTPException(400, str(e))
    return mem_out(m)


@router.patch("/memory/{mid}")
async def patch_memory(mid: str, body: MemoryPatch, user: User = Depends(current_user),
                       session: AsyncSession = Depends(get_session)):
    m = await session.get(MemoryItem, mid)
    if m is None or m.user_id not in (user.id, None):
        raise HTTPException(404, "memória não encontrada")
    if body.status:
        if body.status not in STATUSES:
            raise HTTPException(400, "status inválido")
        m.status = body.status
    if body.content:
        from ultron.memory.embeddings import local_embedding

        m.content = body.content
        m.summary = body.content[:380]
        m.embedding_local = local_embedding(body.content)
    if body.access_scope:
        m.access_scope = body.access_scope
    return mem_out(m)


@router.delete("/memory/{mid}")
async def delete_memory(mid: str, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    if not await forget(session, mid, user.id):
        raise HTTPException(404, "memória não encontrada")
    await audit.record(f"user:{user.id}", "memory.deleted", mid, {}, session=session)
    return {"ok": True}


@router.post("/memory/retention/run")
async def run_retention(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return {"removed": await apply_retention(session)}


@router.get("/research")
async def list_research(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(ResearchReport).order_by(ResearchReport.created_at.desc()).limit(100))
            ).scalars().all()
    return [{**row(r, exclude=("sources", "summary")), "sources_count": len(r.sources or []),
             "summary_preview": (r.summary or "")[:280]} for r in rows]


@router.post("/research")
async def start_research(body: ResearchIn, user: User = Depends(current_user),
                         session: AsyncSession = Depends(get_session)):
    rep = ResearchReport(user_id=user.id, query=body.query, origin="user")
    session.add(rep)
    await session.flush()
    rid = rep.id
    await session.commit()
    task = asyncio.create_task(deep_research(body.query, user_id=user.id, report_id=rid))
    _bg.add(task)
    task.add_done_callback(_bg.discard)
    return {"id": rid, "status": "running"}


@router.get("/research/{rid}")
async def get_research(rid: str, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    r = await session.get(ResearchReport, rid)
    if r is None:
        raise HTTPException(404, "relatório não encontrado")
    return row(r)
