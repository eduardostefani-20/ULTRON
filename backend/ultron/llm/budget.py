"""Controle de orçamento (CÓDIGO DE GOVERNANÇA — agentes não podem alterar).

Limites aplicados ANTES de cada chamada de modelo:
- mensal global (R$ → US$);
- mensal por modelo (opcional);
- por missão;
- fatia mensal da autoevolução e orçamento por ciclo;
- por execução de agente (aplicado no runtime do agente).

Ao estourar a fatia da autoevolução, ela é pausada automaticamente.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ultron import telemetry
from ultron.config import get_settings
from ultron.db import session_scope
from ultron.governance import audit
from ultron.models import EvolutionCycle, LLMCall, Mission
from ultron.utils import utcnow


class BudgetExceeded(Exception):
    def __init__(self, scope: str, message: str):
        super().__init__(message)
        self.scope = scope


@dataclass
class BudgetContext:
    purpose: str = ""
    agent_id: str = ""
    mission_id: str = ""
    cycle_id: str = ""
    run_budget_usd: float | None = None
    run_spent_usd: float = 0.0


def month_start(now: datetime | None = None) -> datetime:
    now = now or utcnow()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


_cache: dict[str, tuple[float, float]] = {}


async def _db_sum(session: AsyncSession, key: str, *conds) -> float:
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < 10:
        return hit[1]
    q = select(func.coalesce(func.sum(LLMCall.cost_usd), 0.0)).where(LLMCall.ts >= month_start(), *conds)
    val = float((await session.execute(q)).scalar_one() or 0.0)
    _cache[key] = (time.monotonic(), val)
    return val


def clear_cache() -> None:
    _cache.clear()


async def monthly_limit_usd(session: AsyncSession) -> float:
    from ultron.settings_store import get_setting

    s = get_settings()
    brl = await get_setting(session, "budget.monthly_brl")
    brl = float(brl) if brl not in (None, "") else s.monthly_budget_brl
    return brl / max(0.1, s.usd_brl_rate)


async def month_spend(session: AsyncSession) -> float:
    return await _db_sum(session, "all") + telemetry.pending("all")


async def evolution_spend(session: AsyncSession) -> float:
    db = await _db_sum(session, "evolution", or_(LLMCall.cycle_id != "", LLMCall.purpose.like("evolution%")))
    return db + telemetry.pending("evolution")


async def check(session: AsyncSession, estimated_usd: float, ctx: BudgetContext, provider: str, model: str) -> None:
    from ultron.settings_store import get_setting, system_set

    limit = await monthly_limit_usd(session)
    spent = await month_spend(session)
    hard = bool(await get_setting(session, "budget.hard_stop"))
    if hard and spent + estimated_usd > limit:
        raise BudgetExceeded("monthly", f"orçamento mensal esgotado (US$ {spent:.2f} de US$ {limit:.2f})")

    per_model = await get_setting(session, "budget.per_model_monthly_usd") or {}
    mkey = f"{provider}:{model}"
    if mkey in per_model:
        mspent = await _db_sum(session, f"model:{mkey}", LLMCall.provider == provider, LLMCall.model == model)
        mspent += telemetry.pending(f"model:{mkey}")
        if mspent + estimated_usd > float(per_model[mkey]):
            raise BudgetExceeded("model", f"limite mensal do modelo {mkey} atingido")

    if ctx.run_budget_usd is not None and ctx.run_spent_usd + estimated_usd > ctx.run_budget_usd:
        raise BudgetExceeded("agent_run", f"orçamento da execução do agente {ctx.agent_id} esgotado")

    if ctx.mission_id:
        m = await session.get(Mission, ctx.mission_id)
        if m is not None:
            mspent = float(m.cost_usd or 0) + telemetry.pending(f"mission:{ctx.mission_id}")
            if mspent + estimated_usd > float(m.budget_usd or 0):
                raise BudgetExceeded("mission", f"orçamento da missão esgotado (US$ {mspent:.3f})")

    if ctx.cycle_id or ctx.purpose.startswith("evolution"):
        share = float(await get_setting(session, "evolution.monthly_budget_share") or 0.35)
        ev_spent = await evolution_spend(session)
        if ev_spent + estimated_usd > limit * share:
            paused = await get_setting(session, "evolution.paused")
            if not paused:
                # transação própria: a pausa precisa persistir mesmo com a exceção abaixo
                async with session_scope() as s2:
                    await system_set(s2, "evolution.paused", True, "system:budget")
                    await audit.record("system:budget", "evolution.auto_paused", "budget",
                                       {"spent_usd": ev_spent, "limit_usd": limit * share}, session=s2)
            raise BudgetExceeded("evolution", "fatia mensal de orçamento da autoevolução esgotada — evolução pausada")
        if ctx.cycle_id:
            cyc = await session.get(EvolutionCycle, ctx.cycle_id)
            if cyc is not None:
                c_spent = float(cyc.cost_usd or 0) + telemetry.pending(f"cycle:{ctx.cycle_id}")
                if c_spent + estimated_usd > float(cyc.budget_usd or 0):
                    raise BudgetExceeded("cycle", "orçamento do ciclo de evolução esgotado")


async def status(session: AsyncSession) -> dict:
    from ultron.settings_store import get_setting

    s = get_settings()
    limit = await monthly_limit_usd(session)
    clear_cache()
    spent = await month_spend(session)
    ev = await evolution_spend(session)
    share = float(await get_setting(session, "evolution.monthly_budget_share") or 0.35)
    threshold = float(await get_setting(session, "budget.alert_threshold") or 0.8)
    now = utcnow()
    start = month_start(now)
    elapsed_days = max(1.0, (now - start).total_seconds() / 86400)
    projected = spent / elapsed_days * 30
    return {
        "limit_usd": round(limit, 4),
        "limit_brl": round(limit * s.usd_brl_rate, 2),
        "spent_usd": round(spent, 6),
        "spent_brl": round(spent * s.usd_brl_rate, 2),
        "usage_ratio": round(spent / limit, 4) if limit else 0,
        "projected_month_usd": round(projected, 4),
        "projected_month_brl": round(projected * s.usd_brl_rate, 2),
        "evolution_spent_usd": round(ev, 6),
        "evolution_limit_usd": round(limit * share, 4),
        "alert": spent >= limit * threshold,
        "usd_brl_rate": s.usd_brl_rate,
    }
