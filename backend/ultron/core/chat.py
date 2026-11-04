"""ULTRON CORE — conversa: interpreta a solicitação, consulta memória, escolhe o modo,
executa via Council Engine e registra aprendizados."""

from __future__ import annotations

import asyncio
import logging
import re

from sqlalchemy import select

from ultron import telemetry
from ultron.council import engine as council
from ultron.db import session_scope
from ultron.llm.budget import BudgetContext, BudgetExceeded
from ultron.llm.service import AllProvidersFailed, NoProviderConfigured
from ultron.memory.service import extract_from_exchange, format_for_context, recall
from ultron.models import Conversation, Message
from ultron.utils import truncate, utcnow

log = logging.getLogger("ultron.chat")
_bg: set[asyncio.Task] = set()

RESEARCH_HINTS = re.compile(r"(?i)\b(pesquis\w*|fontes?|refer[êe]ncias?|not[íi]cias|compare|comparativo|estado da arte|"
                            r"o que h[áa] de novo|tend[êe]ncias|investigue)\b")
ENGINEERING_HINTS = re.compile(r"(?i)\b(arquitetura|refator\w*|implement\w*|bug|c[óo]digo|backend|frontend|api|banco de "
                               r"dados|deploy|performance|escalabilidade|seguran[çc]a do sistema|autoevolu\w*)\b")
DEEP_HINTS = re.compile(r"(?i)\b(analise profundamente|pr[óo]s e contras|decis[ãa]o importante|avalie op[çc][õo]es|"
                        r"conselho|v[áa]rios pontos de vista)\b")


def choose_mode(text: str) -> str:
    """Seleção automática e gratuita (heurística) do modo de inteligência."""
    t = text.strip()
    if RESEARCH_HINTS.search(t) and len(t) > 25:
        return "DEEP_RESEARCH"
    if ENGINEERING_HINTS.search(t) and re.search(r"(?i)ultron|sistema|plataforma|projeto", t) and len(t) > 60:
        return "ENGINEERING"
    if DEEP_HINTS.search(t):
        return "COUNCIL"
    if len(t) < 90 and t.count("?") <= 1 and "\n" not in t:
        return "QUICK"
    return "STANDARD"


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _bg.add(task)
    task.add_done_callback(_bg.discard)


async def handle_message(user_id: str, text: str, *, conversation_id: str | None = None, mode: str = "AUTO") -> dict:
    text = (text or "").strip()
    if not text:
        raise ValueError("mensagem vazia")
    mode = (mode or "AUTO").upper()
    async with session_scope() as s:
        conv = await s.get(Conversation, conversation_id) if conversation_id else None
        if conv is None or conv.user_id != user_id:
            conv = Conversation(user_id=user_id, title=truncate(text.replace("\n", " "), 70), mode=mode)
            s.add(conv)
            await s.flush()
        user_msg = Message(conversation_id=conv.id, role="user", content=text, mode=mode)
        s.add(user_msg)
        rows = (await s.execute(select(Message).where(Message.conversation_id == conv.id)
                                .order_by(Message.created_at.desc()).limit(13))).scalars().all()
        history = [(m.role, m.content) for m in reversed(rows) if m.id != user_msg.id][-12:]
        mems = await recall(s, text, user_id=user_id, limit=6)
        memory_ctx = format_for_context(mems)
        conv_id = conv.id
        conv.updated_at = utcnow()

    if mode == "MISSION":
        from ultron.missions.engine import create_mission

        async with session_scope() as s:
            m = await create_mission(s, text, user_id=user_id, source="chat", conversation_id=conv_id)
            mid = m.id
        answer = (f"Missão criada (`{mid[:8]}`). Vou planejar, delegar aos agentes e executar em segundo plano. "
                  "Acompanhe em **Missões** — o resultado também aparecerá aqui.")
        return await _save_answer(conv_id, answer, "MISSION", [], 0.0, {"mission_id": mid}, [], text, user_id, False)

    effective = choose_mode(text) if mode == "AUTO" else mode
    if effective not in council.MODES:
        effective = "STANDARD"
    ctx = BudgetContext(purpose=f"chat.{effective.lower()}", agent_id="director")
    meta: dict = {"requested_mode": mode, "memories_used": [m.id for m, _ in mems]}
    try:
        if effective == "QUICK":
            r = await council.quick(text, history, memory_ctx, ctx)
        elif effective == "STANDARD":
            r = await council.standard(text, history, memory_ctx, ctx, user_id)
        elif effective == "COUNCIL":
            r = await council.council(text, history, memory_ctx, ctx)
        elif effective == "DEEP_RESEARCH":
            r = await council.research_mode(text, ctx, user_id)
        else:
            r = await council.engineering(text, memory_ctx, ctx)
        meta.update(r.details)
        return await _save_answer(conv_id, r.answer, effective, r.models, r.cost_usd, meta, r.sources, text, user_id,
                                  True)
    except NoProviderConfigured as e:
        answer = f"⚠️ {e}"
        meta["error"] = "no_provider"
    except BudgetExceeded as e:
        answer = f"⚠️ Limite de orçamento atingido: {e}. Ajuste em Configurações → Orçamento."
        meta["error"] = "budget"
    except AllProvidersFailed as e:
        answer = f"⚠️ Os provedores de IA falharam: {e}"
        meta["error"] = "providers_failed"
        telemetry.record_error("chat", str(e))
    except Exception as e:
        log.exception("falha no chat")
        answer = f"⚠️ Ocorreu um erro ao processar a mensagem: {e.__class__.__name__}: {truncate(str(e), 300)}"
        meta["error"] = "internal"
        telemetry.record_error("chat", f"{e.__class__.__name__}: {e}")
    return await _save_answer(conv_id, answer, effective, [], 0.0, meta, [], text, user_id, False)


async def _save_answer(conv_id: str, answer: str, mode: str, models: list[str], cost: float, meta: dict,
                       sources: list, question: str, user_id: str, learn: bool) -> dict:
    meta = dict(meta)
    meta["sources"] = sources
    async with session_scope() as s:
        msg = Message(conversation_id=conv_id, role="assistant", content=answer, mode=mode,
                      model=", ".join(dict.fromkeys(models))[:120], meta=meta, cost_usd=round(cost, 6))
        s.add(msg)
        await s.flush()
        conv = await s.get(Conversation, conv_id)
        out = {"conversation": {"id": conv.id, "title": conv.title},
               "message": serialize_message(msg)}
    telemetry.record_metric("chat.response", 1, {"mode": mode, "ok": "error" not in meta})
    if learn:
        from ultron.settings_store import get_setting

        async with session_scope() as s:
            auto = await get_setting(s, "memory.auto_extract")
        if auto:
            _spawn(extract_from_exchange(user_id, question, answer, source=f"conversation:{conv_id}"))
    return out


def serialize_message(m: Message) -> dict:
    return {"id": m.id, "role": m.role, "content": m.content, "mode": m.mode, "model": m.model, "meta": m.meta or {},
            "cost_usd": m.cost_usd, "feedback": m.feedback, "created_at": m.created_at.isoformat() + "Z"}
