"""Auditoria append-only com encadeamento de hashes (evidência de adulteração).

- Cada registro contém o hash do anterior; alterar ou remover um registro quebra a cadeia.
- O banco bloqueia UPDATE/DELETE na tabela via triggers (migração inicial).
- ``prev_hash`` é único: duas inserções concorrentes não conseguem bifurcar a cadeia.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ultron.db import session_scope
from ultron.models import AuditLog
from ultron.utils import canonical_json, redact_secrets, sha256, utcnow

GENESIS = "0" * 64
_lock = asyncio.Lock()


def compute_hash(ts: str, actor: str, action: str, target: str, details: dict, prev_hash: str) -> str:
    return sha256(canonical_json({"ts": ts, "actor": actor, "action": action, "target": target,
                                  "details": details, "prev": prev_hash}))


def _sanitize(details: dict[str, Any] | None) -> dict:
    """Cópia serializável dos detalhes, sem segredos."""
    if not details:
        return {}
    return json.loads(redact_secrets(json.dumps(details, default=str, ensure_ascii=False)))


async def _insert(session: AsyncSession, actor: str, action: str, target: str, details: dict) -> AuditLog:
    last = (await session.execute(select(AuditLog).order_by(AuditLog.seq.desc()).limit(1))).scalar_one_or_none()
    prev = last.hash if last else GENESIS
    now = utcnow()
    ts = now.replace(microsecond=(now.microsecond // 1000) * 1000)
    h = compute_hash(ts.isoformat(), actor, action, target, details, prev)
    row = AuditLog(ts=ts, actor=actor, action=action, target=target, details=details, prev_hash=prev, hash=h)
    session.add(row)
    await session.flush()
    return row


async def record(actor: str, action: str, target: str = "", details: dict[str, Any] | None = None,
                 session: AsyncSession | None = None) -> None:
    """Grava um evento de auditoria.

    Se ``session`` for informada, o evento entra na mesma transação (use quando a sessão
    já fez escritas — evita bloqueios no SQLite).
    """
    clean = _sanitize(details)
    async with _lock:
        for attempt in range(5):
            try:
                if session is not None:
                    async with session.begin_nested():
                        await _insert(session, actor, action, target, clean)
                else:
                    async with session_scope() as s:
                        await _insert(s, actor, action, target, clean)
                return
            except IntegrityError:
                if attempt == 4:
                    raise
                await asyncio.sleep(0.05 * (attempt + 1))


async def verify_chain(session: AsyncSession, limit: int | None = None) -> dict:
    """Recalcula a cadeia inteira e aponta o primeiro registro inconsistente."""
    rows = (await session.execute(select(AuditLog).order_by(AuditLog.seq.asc()))).scalars().all()
    prev = GENESIS
    for row in rows:
        expected = compute_hash(row.ts.isoformat(), row.actor, row.action, row.target, row.details or {}, prev)
        if row.prev_hash != prev or row.hash != expected:
            return {"valid": False, "entries": len(rows), "broken_at": row.seq,
                    "message": f"cadeia de auditoria quebrada no registro #{row.seq}"}
        prev = row.hash
    return {"valid": True, "entries": len(rows), "head": prev, "message": "cadeia íntegra"}
