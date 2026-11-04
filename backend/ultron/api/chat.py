"""Conversas, chat e Conselho."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ultron.api.common import iso
from ultron.api.deps import current_user
from ultron.core.chat import choose_mode, handle_message, serialize_message
from ultron.council import engine as council
from ultron.db import get_session
from ultron.llm.budget import BudgetContext
from ultron.memory.service import format_for_context, recall
from ultron.models import Conversation, Message, User

router = APIRouter(prefix="/api", tags=["chat"])


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=20000)
    conversation_id: str | None = None
    mode: str = "AUTO"


class FeedbackIn(BaseModel):
    value: int = Field(ge=-1, le=1)


class TitleIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class CouncilIn(BaseModel):
    question: str = Field(min_length=3, max_length=20000)
    mode: str = "COUNCIL"


@router.get("/conversations")
async def list_conversations(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(Conversation, func.count(Message.id)).outerjoin(Message)
                                  .where(Conversation.user_id == user.id, Conversation.archived.is_(False))
                                  .group_by(Conversation.id).order_by(Conversation.updated_at.desc()).limit(200))).all()
    return [{"id": c.id, "title": c.title, "mode": c.mode, "messages": n, "updated_at": iso(c.updated_at)}
            for c, n in rows]


@router.get("/conversations/{cid}")
async def get_conversation(cid: str, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    c = await session.get(Conversation, cid)
    if c is None or c.user_id != user.id:
        raise HTTPException(404, "conversa não encontrada")
    msgs = (await session.execute(select(Message).where(Message.conversation_id == cid)
                                  .order_by(Message.created_at.asc()))).scalars().all()
    return {"id": c.id, "title": c.title, "mode": c.mode, "messages": [serialize_message(m) for m in msgs]}


@router.patch("/conversations/{cid}")
async def rename_conversation(cid: str, body: TitleIn, user: User = Depends(current_user),
                              session: AsyncSession = Depends(get_session)):
    c = await session.get(Conversation, cid)
    if c is None or c.user_id != user.id:
        raise HTTPException(404, "conversa não encontrada")
    c.title = body.title
    return {"ok": True}


@router.delete("/conversations/{cid}")
async def delete_conversation(cid: str, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    c = await session.get(Conversation, cid)
    if c is None or c.user_id != user.id:
        raise HTTPException(404, "conversa não encontrada")
    await session.execute(delete(Message).where(Message.conversation_id == cid))
    await session.delete(c)
    return {"ok": True}


@router.post("/chat")
async def chat(body: ChatIn, user: User = Depends(current_user)):
    mode = body.mode.upper()
    if mode not in ("AUTO", "MISSION", *council.MODES):
        raise HTTPException(400, f"modo inválido: {body.mode}")
    try:
        return await handle_message(user.id, body.message, conversation_id=body.conversation_id, mode=mode)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/chat/suggest-mode")
async def suggest_mode(text: str, user: User = Depends(current_user)):
    return {"mode": choose_mode(text)}


@router.post("/messages/{mid}/feedback")
async def feedback(mid: str, body: FeedbackIn, user: User = Depends(current_user),
                   session: AsyncSession = Depends(get_session)):
    m = await session.get(Message, mid)
    if m is None:
        raise HTTPException(404, "mensagem não encontrada")
    c = await session.get(Conversation, m.conversation_id)
    if c is None or c.user_id != user.id:
        raise HTTPException(404, "mensagem não encontrada")
    m.feedback = body.value or None
    return {"ok": True}


@router.get("/council/modes")
async def council_modes(user: User = Depends(current_user)):
    return [
        {"id": "QUICK", "name": "Rápido", "description": "Um modelo econômico responde diretamente."},
        {"id": "STANDARD", "name": "Padrão", "description": "Director Agent com memória e ferramentas (busca, cálculo)."},
        {"id": "COUNCIL", "name": "Conselho", "description": "Vários modelos respondem de forma independente; um crítico "
                                                             "compara e um sintetizador consolida, registrando divergências."},
        {"id": "DEEP_RESEARCH", "name": "Pesquisa profunda", "description": "Sub-consultas, leitura de fontes e "
                                                                          "relatório com citações."},
        {"id": "ENGINEERING", "name": "Engineering Council", "description": "Proponente, crítico e revisor de segurança/"
                                                                           "arquitetura produzem um registro de decisão "
                                                                           "técnica que pode virar proposta de evolução."},
    ]


@router.post("/council")
async def run_council(body: CouncilIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    mode = body.mode.upper()
    if mode not in council.MODES:
        raise HTTPException(400, "modo inválido")
    mems = await recall(session, body.question, user_id=user.id, limit=5)
    ctx_mem = format_for_context(mems)
    await session.commit()
    ctx = BudgetContext(purpose=f"council.{mode.lower()}", agent_id="director")
    try:
        if mode == "QUICK":
            r = await council.quick(body.question, [], ctx_mem, ctx)
        elif mode == "STANDARD":
            r = await council.standard(body.question, [], ctx_mem, ctx, user.id)
        elif mode == "COUNCIL":
            r = await council.council(body.question, [], ctx_mem, ctx)
        elif mode == "DEEP_RESEARCH":
            r = await council.research_mode(body.question, ctx, user.id)
        else:
            r = await council.engineering(body.question, ctx_mem, ctx)
    except Exception as e:
        raise HTTPException(502, f"{e.__class__.__name__}: {e}")
    return {"mode": r.mode, "answer": r.answer, "cost_usd": r.cost_usd, "models": r.models, "details": r.details,
            "sources": r.sources}
