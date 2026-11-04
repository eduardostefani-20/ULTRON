"""Scheduler persistente: roda no processo do backend, independente da interface aberta.

Usa arrendamentos no banco (job_leases) para que apenas uma instância execute cada trabalho,
e retoma ciclos interrompidos a partir do checkpoint.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import select

from ultron import telemetry
from ultron.config import get_settings
from ultron.db import session_scope
from ultron.evolution.cycle import WORKER_ID, create_cycle, run_cycle
from ultron.evolution.observability import api_stats
from ultron.models import EvolutionCycle, JobLease, ProviderCredential
from ultron.utils import utcnow

log = logging.getLogger("ultron.scheduler")

FIXED_JOBS = {  # nome: (intervalo em minutos, timeout em minutos)
    "provider_health": (30, 5),
    "publication_monitor": (10, 15),
    "memory_retention": (24 * 60, 10),
    "cache_purge": (6 * 60, 5),
    "api_metrics": (1, 2),
}


async def _acquire(name: str, timeout_min: int) -> bool:
    now = utcnow()
    async with session_scope() as s:
        row = await s.get(JobLease, name)
        if row is None:
            row = JobLease(name=name)
            s.add(row)
        elif row.holder and row.holder != WORKER_ID and row.expires_at and row.expires_at > now:
            return False
        row.holder = WORKER_ID
        row.expires_at = now + timedelta(minutes=timeout_min)
        return True


async def _release(name: str, status: str, message: str = "") -> None:
    async with session_scope() as s:
        row = await s.get(JobLease, name)
        if row:
            row.holder = ""
            row.expires_at = None
            row.last_run_at = utcnow()
            row.last_status = status
            row.last_message = message[:2000]
            row.runs = (row.runs or 0) + 1


async def _due(name: str, interval_min: float) -> bool:
    async with session_scope() as s:
        row = await s.get(JobLease, name)
        if row is None or row.last_run_at is None:
            return True
        if row.holder and row.expires_at and row.expires_at > utcnow():
            return False
        return utcnow() >= row.last_run_at + timedelta(minutes=interval_min)


async def job_provider_health() -> str:
    from ultron.providers import registry
    from ultron.providers.router import health

    async with session_scope() as s:
        handles = await registry.get_llm_handles(s)
    results = []
    for pid, h in handles.items():
        try:
            models = await asyncio.wait_for(h.provider.list_models(), timeout=25)
            health.success(pid, "_health", 0)
            ok, msg = True, f"{len(models)} modelos"
        except Exception as e:
            ok, msg = False, str(e)[:300]
            health.failure(pid, "_health", msg, auth=getattr(e, "auth", False))
        telemetry.record_metric("provider.health", 1 if ok else 0, {"provider": pid})
        async with session_scope() as s:
            row = (await s.execute(select(ProviderCredential).where(ProviderCredential.provider == pid))
                   ).scalar_one_or_none()
            if row:
                row.last_test_at = utcnow()
                row.last_test_ok = ok
                row.last_test_message = msg
        results.append(f"{pid}:{'ok' if ok else 'falha'}")
    return ", ".join(results) or "nenhum provedor"


async def job_memory_retention() -> str:
    from ultron.memory.service import apply_retention

    async with session_scope() as s:
        n = await apply_retention(s)
    return f"{n} memórias expiradas removidas"


async def job_cache_purge() -> str:
    from ultron.llm.service import purge_cache

    return f"{await purge_cache()} entradas de cache expiradas"


async def job_publication_monitor() -> str:
    from ultron.evolution.publisher import monitor, retry_approved

    res = await monitor()
    retried = await retry_approved()
    return f"{len(res)} publicação(ões) monitoradas; {len(retried)} aprovação(ões) pendentes de publicação tentadas"


async def job_api_metrics() -> str:
    for name, value, labels in api_stats.flush_points():
        telemetry.record_metric(name, value, labels)
    await telemetry.flush()
    return "ok"


JOB_FUNCS = {
    "provider_health": job_provider_health,
    "publication_monitor": job_publication_monitor,
    "memory_retention": job_memory_retention,
    "cache_purge": job_cache_purge,
    "api_metrics": job_api_metrics,
}


class Scheduler:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._jobs: dict[str, asyncio.Task] = {}
        self._stop = asyncio.Event()
        self.started_at = utcnow()

    def _spawn(self, name: str, coro) -> None:
        async def wrapper():
            try:
                msg = await coro
                await _release(name, "ok", str(msg))
            except Exception as e:
                log.exception("job %s falhou", name)
                telemetry.record_error(f"job:{name}", f"{e.__class__.__name__}: {e}")
                await _release(name, "failed", f"{e.__class__.__name__}: {e}")

        self._jobs[name] = asyncio.create_task(wrapper())

    def _busy(self, name: str) -> bool:
        t = self._jobs.get(name)
        return t is not None and not t.done()

    async def tick(self) -> list[str]:
        from ultron.settings_store import get_setting

        started = []
        for name, (interval, timeout) in FIXED_JOBS.items():
            if self._busy(name) or not await _due(name, interval):
                continue
            if await _acquire(name, timeout):
                self._spawn(name, JOB_FUNCS[name]())
                started.append(name)
        # autoevolução contínua
        if not self._busy("evolution_cycle"):
            async with session_scope() as s:
                enabled = await get_setting(s, "evolution.enabled")
                paused = await get_setting(s, "evolution.paused")
                interval = float(await get_setting(s, "evolution.interval_minutes") or 360)
                interrupted = (await s.execute(select(EvolutionCycle).where(
                    EvolutionCycle.status.in_(("running", "interrupted"))).order_by(EvolutionCycle.started_at.desc())
                )).scalars().first()
                stale = interrupted is not None and (
                    interrupted.status == "interrupted"
                    or not interrupted.lease_expires_at or interrupted.lease_expires_at < utcnow()
                    or interrupted.lease_owner != WORKER_ID)
            if enabled and not paused:
                if interrupted is not None and stale:
                    if await _acquire("evolution_cycle", 60):
                        self._spawn("evolution_cycle", self._resume(interrupted.id))
                        started.append("evolution_cycle(retomado)")
                elif interrupted is None and await _due("evolution_cycle", interval):
                    if await _acquire("evolution_cycle", 60):
                        self._spawn("evolution_cycle", self._new_cycle("scheduled"))
                        started.append("evolution_cycle")
        return started

    async def _new_cycle(self, trigger: str) -> str:
        cid = await create_cycle(trigger)
        res = await run_cycle(cid)
        return f"ciclo {cid[:8]}: {res.get('status')}"

    async def _resume(self, cycle_id: str) -> str:
        res = await run_cycle(cycle_id)
        return f"ciclo {cycle_id[:8]} retomado: {res.get('status')}"

    async def run_now(self) -> str:
        if self._busy("evolution_cycle"):
            raise RuntimeError("um ciclo de evolução já está em execução")
        if not await _acquire("evolution_cycle", 60):
            raise RuntimeError("outro processo está executando a evolução")
        cid = await create_cycle("manual")

        async def go():
            res = await run_cycle(cid)
            return f"ciclo {cid[:8]}: {res.get('status')}"

        self._spawn("evolution_cycle", go())
        return cid

    async def _loop(self) -> None:
        tick = get_settings().scheduler_tick_seconds
        # pequeno atraso inicial para a aplicação terminar de subir
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=5)
        except TimeoutError:
            pass
        while not self._stop.is_set():
            try:
                await self.tick()
            except Exception:  # pragma: no cover
                log.exception("tick do scheduler")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=tick)
            except TimeoutError:
                pass

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop.clear()
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._stop.set()
        tasks = [t for t in [self._task, *self._jobs.values()] if t]
        for t in tasks:
            if t is not self._task:
                t.cancel()
        for t in tasks:
            try:
                await asyncio.wait_for(t, timeout=5)
            except (asyncio.CancelledError, TimeoutError, Exception):
                pass

    async def status(self) -> dict:
        async with session_scope() as s:
            rows = (await s.execute(select(JobLease))).scalars().all()
        jobs = {r.name: {"last_run_at": r.last_run_at.isoformat() + "Z" if r.last_run_at else None,
                         "last_status": r.last_status, "last_message": r.last_message, "runs": r.runs,
                         "running": self._busy(r.name)} for r in rows}
        return {"running": self._task is not None and not self._task.done(), "worker": WORKER_ID,
                "started_at": self.started_at.isoformat() + "Z", "jobs": jobs}


scheduler = Scheduler()
