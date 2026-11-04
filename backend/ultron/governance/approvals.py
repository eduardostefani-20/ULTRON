"""Aprovações humanas (publicações de médio/alto risco, ações sensíveis, novos agentes)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ultron.governance import audit
from ultron.models import Approval
from ultron.utils import utcnow


class ApprovalError(Exception):
    pass


async def request_approval(session: AsyncSession, *, kind: str, target_type: str, target_id: str, risk: str,
                           title: str, summary: str = "", details: dict | None = None,
                           requested_by: str = "ultron") -> Approval:
    existing = (
        await session.execute(
            select(Approval).where(Approval.target_type == target_type, Approval.target_id == target_id,
                                   Approval.status == "pending")
        )
    ).scalar_one_or_none()
    if existing:
        return existing
    ap = Approval(kind=kind, target_type=target_type, target_id=target_id, risk=risk, title=title[:200],
                  summary=summary, details=details or {}, requested_by=requested_by)
    session.add(ap)
    await session.flush()
    await audit.record(requested_by, "approval.requested", f"{target_type}:{target_id}",
                       {"approval_id": ap.id, "risk": risk, "title": title}, session=session)
    return ap


async def decide(session: AsyncSession, approval_id: str, *, approve: bool, decided_by: str, reason: str = "",
                 human: bool) -> Approval:
    """Somente humanos decidem aprovações. O chamador (API) garante a autenticação."""
    if not human:
        await audit.record(decided_by, "approval.denied_non_human", approval_id, {}, session=session)
        raise ApprovalError("aprovações só podem ser decididas por um humano autenticado")
    ap = await session.get(Approval, approval_id)
    if ap is None:
        raise ApprovalError("aprovação não encontrada")
    if ap.status != "pending":
        raise ApprovalError(f"aprovação já decidida ({ap.status})")
    ap.status = "approved" if approve else "rejected"
    ap.decided_by = decided_by
    ap.decided_at = utcnow()
    ap.reason = reason
    await session.flush()
    await audit.record(decided_by, "approval.approved" if approve else "approval.rejected",
                       f"{ap.target_type}:{ap.target_id}", {"approval_id": ap.id, "risk": ap.risk, "reason": reason},
                       session=session)
    return ap


async def is_approved(session: AsyncSession, target_type: str, target_id: str) -> bool:
    row = (
        await session.execute(
            select(Approval).where(Approval.target_type == target_type, Approval.target_id == target_id,
                                   Approval.status == "approved")
        )
    ).first()
    return row is not None
