"""Observabilidade própria: métricas agregadas a partir de dados reais registrados."""

from __future__ import annotations

import os
import resource
import shutil
import time
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ultron.config import get_settings
from ultron.models import AgentRun, ErrorEvent, LLMCall, Message, MetricPoint, Mission, ToolCall
from ultron.providers.router import health
from ultron.utils import utcnow

STARTED_AT = time.time()


class ApiStats:
    """Agregador em memória das requisições HTTP (gravado periodicamente como métricas)."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.count = 0
        self.errors_5xx = 0
        self.errors_4xx = 0
        self.latencies: list[float] = []

    def add(self, status: int, latency_ms: float) -> None:
        self.count += 1
        if status >= 500:
            self.errors_5xx += 1
        elif status >= 400:
            self.errors_4xx += 1
        if len(self.latencies) < 5000:
            self.latencies.append(latency_ms)

    def flush_points(self) -> list[tuple[str, float, dict]]:
        if not self.count:
            return []
        lat = sorted(self.latencies) or [0]
        pts = [("api.requests", self.count, {}), ("api.errors_5xx", self.errors_5xx, {}),
               ("api.errors_4xx", self.errors_4xx, {}),
               ("api.latency_p50_ms", lat[len(lat) // 2], {}), ("api.latency_p95_ms", lat[int(len(lat) * 0.95) - 1
                                                                                         if len(lat) > 1 else 0], {})]
        self.reset()
        return pts


api_stats = ApiStats()


def _pct(values: list[int], p: float) -> int:
    if not values:
        return 0
    v = sorted(values)
    return v[min(len(v) - 1, int(len(v) * p))]


async def snapshot(session: AsyncSession, hours: int = 24) -> dict:
    since = utcnow() - timedelta(hours=hours)
    calls = (await session.execute(select(LLMCall.provider, LLMCall.model, LLMCall.success, LLMCall.latency_ms,
                                          LLMCall.cost_usd, LLMCall.cached, LLMCall.tokens_in, LLMCall.tokens_out,
                                          LLMCall.price_known)
                                   .where(LLMCall.ts >= since))).all()
    by_provider: dict[str, dict] = defaultdict(lambda: {"calls": 0, "failures": 0, "cost_usd": 0.0, "latencies": [],
                                                        "tokens": 0, "cached": 0, "unknown_price": 0})
    for c in calls:
        d = by_provider[c.provider]
        d["calls"] += 1
        d["failures"] += 0 if c.success else 1
        d["cost_usd"] += c.cost_usd or 0
        d["tokens"] += (c.tokens_in or 0) + (c.tokens_out or 0)
        d["cached"] += 1 if c.cached else 0
        d["unknown_price"] += 0 if c.price_known else 1
        if c.success and not c.cached and c.latency_ms:
            d["latencies"].append(c.latency_ms)
    providers = {}
    for p, d in by_provider.items():
        providers[p] = {"calls": d["calls"], "failures": d["failures"],
                        "error_rate": round(d["failures"] / d["calls"], 3) if d["calls"] else 0,
                        "cost_usd": round(d["cost_usd"], 5), "tokens": d["tokens"], "cached": d["cached"],
                        "unknown_price": d["unknown_price"],
                        "latency_p50_ms": _pct(d["latencies"], 0.5), "latency_p95_ms": _pct(d["latencies"], 0.95)}
    total_calls = len(calls)
    total_fail = sum(1 for c in calls if not c.success)

    tools = (await session.execute(select(ToolCall.tool, func.count(),
                                          func.sum(case((ToolCall.success.is_(False), 1), else_=0)),
                                          func.sum(case((ToolCall.denied.is_(True), 1), else_=0)))
                                   .where(ToolCall.ts >= since).group_by(ToolCall.tool))).all()
    tools_d = {t: {"calls": n, "failures": int(f or 0), "denied": int(dn or 0),
                   "failure_rate": round((f or 0) / n, 3) if n else 0} for t, n, f, dn in tools}

    mrows = (await session.execute(select(Mission.status, func.count()).where(Mission.created_at >= since)
                                   .group_by(Mission.status))).all()
    missions = {s: n for s, n in mrows}
    finished = missions.get("COMPLETED", 0) + missions.get("FAILED", 0)
    arows = (await session.execute(select(AgentRun.agent_id, AgentRun.status, func.count())
                                   .where(AgentRun.started_at >= since).group_by(AgentRun.agent_id, AgentRun.status))).all()
    agents: dict[str, dict] = defaultdict(lambda: {"runs": 0, "failed": 0})
    for a, st, n in arows:
        agents[a]["runs"] += n
        if st == "failed":
            agents[a]["failed"] += n
    for v in agents.values():
        v["failure_rate"] = round(v["failed"] / v["runs"], 3) if v["runs"] else 0

    erows = (await session.execute(select(ErrorEvent.signature, ErrorEvent.source, func.count(),
                                          func.max(ErrorEvent.message))
                                   .where(ErrorEvent.ts >= since).group_by(ErrorEvent.signature, ErrorEvent.source)
                                   .order_by(func.count().desc()).limit(15))).all()
    errors = [{"signature": sig, "source": src, "count": n, "message": msg} for sig, src, n, msg in erows]

    fb = (await session.execute(select(Message.feedback, func.count()).where(Message.created_at >= since,
                                                                             Message.feedback.is_not(None))
                                .group_by(Message.feedback))).all()
    fbd = {int(k): n for k, n in fb}
    assistant_msgs = (await session.execute(select(func.count()).select_from(Message).where(
        Message.created_at >= since, Message.role == "assistant"))).scalar_one()

    api_rows = (await session.execute(select(MetricPoint.name, func.sum(MetricPoint.value), func.max(MetricPoint.value))
                                      .where(MetricPoint.ts >= since, MetricPoint.name.like("api.%"))
                                      .group_by(MetricPoint.name))).all()
    api = {n: {"sum": round(sv or 0, 2), "max": round(mx or 0, 2)} for n, sv, mx in api_rows}

    s = get_settings()
    disk = shutil.disk_usage(s.data_dir if s.data_dir.exists() else "/")
    rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    return {
        "window_hours": hours,
        "llm": {"calls": total_calls, "failures": total_fail,
                "error_rate": round(total_fail / total_calls, 3) if total_calls else 0,
                "cost_usd": round(sum(c.cost_usd or 0 for c in calls), 5), "providers": providers},
        "tools": tools_d,
        "missions": {"by_status": missions, "success_rate": round(missions.get("COMPLETED", 0) / finished, 3)
                     if finished else None},
        "agents": dict(agents),
        "errors": errors,
        "quality": {"assistant_messages": assistant_msgs, "positive": fbd.get(1, 0), "negative": fbd.get(-1, 0)},
        "api": api,
        "provider_health": health.snapshot(),
        "system": {"uptime_s": int(time.time() - STARTED_AT), "max_rss_mb": round(rss_mb, 1),
                   "disk_free_gb": round(disk.free / 1e9, 2), "pid": os.getpid()},
    }


async def record_history(session: AsyncSession, snap: dict) -> None:
    """Grava indicadores-chave como série histórica (comparação entre ciclos/publicações)."""
    pts = [
        ("kpi.llm_error_rate", snap["llm"]["error_rate"]),
        ("kpi.llm_calls", snap["llm"]["calls"]),
        ("kpi.llm_cost_usd", snap["llm"]["cost_usd"]),
        ("kpi.mission_success_rate", snap["missions"]["success_rate"] if snap["missions"]["success_rate"] is not None
         else -1),
        ("kpi.negative_feedback", snap["quality"]["negative"]),
        ("kpi.recurring_errors", sum(e["count"] for e in snap["errors"])),
    ]
    for name, value in pts:
        session.add(MetricPoint(name=name, value=float(value), labels={"window_h": snap["window_hours"]}))
