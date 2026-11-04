"""Memory Intelligence: memória persistente com tipos, status de confiabilidade, busca híbrida
e políticas de retenção."""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ultron.memory.embeddings import bm25_scores, cosine, local_embedding
from ultron.models import MemoryItem
from ultron.utils import sha256, truncate, utcnow

log = logging.getLogger("ultron.memory")

KINDS = ("conversation", "personal", "operational", "semantic", "document", "decision", "task", "learning",
         "technical")
STATUSES = ("confirmed", "hypothesis", "outdated", "unverified", "preference", "decision")
STATUS_LABEL = {
    "confirmed": "CONFIRMADO",
    "hypothesis": "HIPÓTESE",
    "outdated": "DESATUALIZADO",
    "unverified": "NÃO VERIFICADO",
    "preference": "PREFERÊNCIA DO USUÁRIO",
    "decision": "DECISÃO TÉCNICA",
}
STATUS_WEIGHT = {"confirmed": 1.1, "preference": 1.15, "decision": 1.1, "unverified": 0.9, "hypothesis": 0.85,
                 "outdated": 0.45}
CANDIDATE_LIMIT = 3000


class MemoryError_(ValueError):
    pass


async def remember(session: AsyncSession, content: str, *, kind: str = "semantic", status: str = "unverified",
                   user_id: str | None = None, tags: list[str] | None = None, source: str = "",
                   importance: float = 0.5, access_scope: str = "agents") -> MemoryItem:
    content = (content or "").strip()
    if not content:
        raise MemoryError_("conteúdo vazio")
    if kind not in KINDS:
        raise MemoryError_(f"tipo de memória inválido: {kind}")
    if status not in STATUSES:
        raise MemoryError_(f"status inválido: {status}")
    content = truncate(content, 8000)
    h = sha256(f"{user_id}|{kind}|{content.lower()}")
    existing = (await session.execute(select(MemoryItem).where(MemoryItem.content_hash == h))).scalar_one_or_none()
    if existing:
        existing.importance = max(existing.importance, importance)
        existing.updated_at = utcnow()
        return existing
    emb = local_embedding(content)
    # quase-duplicata: atualiza a existente em vez de acumular
    recent = (
        await session.execute(
            select(MemoryItem).where(MemoryItem.user_id == user_id, MemoryItem.kind == kind)
            .order_by(MemoryItem.updated_at.desc()).limit(200)
        )
    ).scalars().all()
    for r in recent:
        if cosine(r.embedding_local, emb) > 0.95:
            r.content = content
            r.embedding_local = emb
            r.status = status if status != "unverified" else r.status
            r.importance = max(r.importance, importance)
            r.updated_at = utcnow()
            return r
    from ultron.settings_store import get_setting

    retention = await get_setting(session, "memory.retention_days") or {}
    expires = None
    if kind in retention and retention[kind]:
        expires = utcnow() + timedelta(days=int(retention[kind]))
    item = MemoryItem(user_id=user_id, kind=kind, status=status, content=content, summary=truncate(content, 380),
                      tags=tags or [], source=source[:200], importance=max(0.0, min(1.0, importance)),
                      embedding_local=emb, access_scope=access_scope, content_hash=h, expires_at=expires)
    session.add(item)
    await session.flush()
    return item


async def recall(session: AsyncSession, query: str, *, user_id: str | None = None, kinds: list[str] | None = None,
                 limit: int = 6, for_agent: bool = False, min_score: float = 0.08) -> list[tuple[MemoryItem, float]]:
    q = select(MemoryItem).where((MemoryItem.expires_at.is_(None)) | (MemoryItem.expires_at > utcnow()))
    if user_id is not None:
        q = q.where((MemoryItem.user_id == user_id) | (MemoryItem.user_id.is_(None)))
    if kinds:
        q = q.where(MemoryItem.kind.in_(kinds))
    if for_agent:
        q = q.where(MemoryItem.access_scope == "agents")
        from ultron.settings_store import get_setting

        if not await get_setting(session, "memory.agents_can_read_personal"):
            q = q.where(MemoryItem.kind != "personal")
    q = q.order_by(MemoryItem.updated_at.desc()).limit(CANDIDATE_LIMIT)
    items = (await session.execute(q)).scalars().all()
    if not items:
        return []
    qemb = local_embedding(query)
    bm = bm25_scores(query, [i.content for i in items])
    bmax = max(bm) or 1.0
    now = utcnow()
    scored: list[tuple[MemoryItem, float]] = []
    for item, b in zip(items, bm, strict=False):
        sem = cosine(item.embedding_local, qemb)
        age_days = max(0.0, (now - (item.updated_at or now)).total_seconds() / 86400)
        recency = 1.0 / (1.0 + age_days / 30)
        score = 0.55 * sem + 0.30 * (b / bmax) + 0.10 * item.importance + 0.05 * recency
        score *= STATUS_WEIGHT.get(item.status, 1.0)
        if score >= min_score and (sem > 0.05 or b > 0):
            scored.append((item, round(score, 4)))
    scored.sort(key=lambda t: t[1], reverse=True)
    top = scored[:limit]
    for item, _ in top:
        item.access_count = (item.access_count or 0) + 1
        item.last_accessed_at = now
    return top


def format_for_context(items: list[tuple[MemoryItem, float]]) -> str:
    if not items:
        return ""
    lines = ["Memórias relevantes (use com critério; respeite o status de cada uma):"]
    for item, _score in items:
        lines.append(f"- [{STATUS_LABEL.get(item.status, item.status)} · {item.kind}] {truncate(item.content, 500)}")
    return "\n".join(lines)


async def update_status(session: AsyncSession, item_id: str, status: str, user_id: str | None = None) -> MemoryItem:
    if status not in STATUSES:
        raise MemoryError_("status inválido")
    item = await session.get(MemoryItem, item_id)
    if item is None or (user_id and item.user_id not in (user_id, None)):
        raise MemoryError_("memória não encontrada")
    item.status = status
    item.updated_at = utcnow()
    return item


async def forget(session: AsyncSession, item_id: str, user_id: str | None = None) -> bool:
    item = await session.get(MemoryItem, item_id)
    if item is None or (user_id and item.user_id not in (user_id, None)):
        return False
    await session.delete(item)
    return True


async def apply_retention(session: AsyncSession) -> int:
    r = await session.execute(delete(MemoryItem).where(MemoryItem.expires_at.is_not(None),
                                                       MemoryItem.expires_at < utcnow()))
    return r.rowcount or 0


async def stats(session: AsyncSession, user_id: str | None = None) -> dict:
    base = select(MemoryItem.kind, MemoryItem.status, func.count()).group_by(MemoryItem.kind, MemoryItem.status)
    if user_id:
        base = base.where((MemoryItem.user_id == user_id) | (MemoryItem.user_id.is_(None)))
    rows = (await session.execute(base)).all()
    by_kind: dict[str, int] = {}
    by_status: dict[str, int] = {}
    total = 0
    for kind, status, n in rows:
        by_kind[kind] = by_kind.get(kind, 0) + n
        by_status[status] = by_status.get(status, 0) + n
        total += n
    accessed = (await session.execute(select(func.count()).select_from(MemoryItem).where(
        MemoryItem.access_count > 0))).scalar_one()
    return {"total": total, "by_kind": by_kind, "by_status": by_status, "ever_recalled": accessed,
            "embedding": "local-hash-256 (custo zero) + BM25"}


EXTRACT_PROMPT = """Você é o Memory Agent do ULTRON. Extraia APENAS informações duráveis e úteis no futuro
da troca abaixo: fatos pessoais do usuário, preferências, decisões técnicas, objetivos, aprendizados.
Ignore conversa trivial. Não invente. Se nada for durável, retorne lista vazia.

Responda em JSON: {"memories": [{"content": "frase autocontida", "kind": "personal|semantic|decision|task|learning|technical",
"status": "preference|confirmed|unverified|decision|hypothesis", "importance": 0.0-1.0, "tags": ["..."]}]}
Use status "preference" para preferências do usuário, "confirmed" só para o que o próprio usuário afirmou como fato,
"decision" para decisões técnicas tomadas, "unverified" para o resto. Máximo de 4 itens."""


async def extract_from_exchange(user_id: str | None, user_msg: str, assistant_msg: str, *, source: str) -> int:
    """Usa um modelo rápido para extrair memórias duráveis (custo baixo e limitado)."""
    from ultron.db import session_scope
    from ultron.llm.service import BudgetContext, ChatMessage, TaskProfile, complete_json

    try:
        data, _ = await complete_json(
            [ChatMessage("system", EXTRACT_PROMPT),
             ChatMessage("user", f"USUÁRIO: {truncate(user_msg, 3000)}\n\nULTRON: {truncate(assistant_msg, 2000)}")],
            TaskProfile(task="classify", tier="fast"), ctx=BudgetContext(purpose="memory.extract", agent_id="memory"),
            max_tokens=600, effort="low",
        )
    except Exception as e:
        log.info("extração de memória ignorada: %s", e)
        return 0
    mems = (data or {}).get("memories", []) if isinstance(data, dict) else []
    n = 0
    async with session_scope() as s:
        for m in mems[:4]:
            try:
                await remember(s, str(m.get("content", "")), kind=m.get("kind", "semantic") if m.get("kind") in KINDS
                               else "semantic", status=m.get("status") if m.get("status") in STATUSES else "unverified",
                               user_id=user_id, tags=[str(t) for t in (m.get("tags") or [])][:6], source=source,
                               importance=float(m.get("importance") or 0.5))
                n += 1
            except (MemoryError_, ValueError, TypeError):
                continue
    return n
