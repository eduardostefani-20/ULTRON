"""Telemetria: chamadas de modelo, ferramentas, métricas e erros recorrentes.

Os registros são acumulados em memória e gravados em lote pelo ``flusher`` (evita
bloqueios de escrita no SQLite durante transações longas). Gastos são contabilizados
imediatamente em memória para o controle de orçamento.
"""

from __future__ import annotations

import asyncio
import logging
import re

from ultron.db import session_scope
from ultron.models import ErrorEvent, LLMCall, MetricPoint, ToolCall
from ultron.utils import redact_secrets, sha256, truncate, utcnow

log = logging.getLogger("ultron.telemetry")

_buffer: list = []
_lock = asyncio.Lock()
# custo ainda não gravado no banco, por dimensão ("all", "cycle:<id>", "mission:<id>",
# "model:<provedor:modelo>", "evolution")
_pending: dict[str, float] = {}
_task: asyncio.Task | None = None


def _dims(call: LLMCall) -> list[str]:
    dims = ["all", f"model:{call.provider}:{call.model}"]
    if call.cycle_id:
        dims.append(f"cycle:{call.cycle_id}")
    if call.mission_id:
        dims.append(f"mission:{call.mission_id}")
    if call.cycle_id or (call.purpose or "").startswith("evolution"):
        dims.append("evolution")
    return dims


def pending(dim: str = "all") -> float:
    return _pending.get(dim, 0.0)


def record_llm_call(**kw) -> None:
    kw.setdefault("ts", utcnow())
    if kw.get("error"):
        kw["error"] = truncate(redact_secrets(kw["error"]), 1000)
    call = LLMCall(**kw)
    _buffer.append(call)
    cost = float(kw.get("cost_usd") or 0.0)
    if cost:
        for d in _dims(call):
            _pending[d] = _pending.get(d, 0.0) + cost


def record_tool_call(**kw) -> None:
    kw.setdefault("ts", utcnow())
    if kw.get("args_summary"):
        kw["args_summary"] = truncate(redact_secrets(kw["args_summary"]), 500)
    if kw.get("error"):
        kw["error"] = truncate(redact_secrets(kw["error"]), 1000)
    _buffer.append(ToolCall(**kw))


def record_metric(name: str, value: float, labels: dict | None = None) -> None:
    _buffer.append(MetricPoint(ts=utcnow(), name=name, value=float(value), labels=labels or {}))


_NORMALIZE = [
    (re.compile(r"[0-9a-f]{16,}"), "<id>"),
    (re.compile(r"\d+(\.\d+)?"), "<n>"),
    (re.compile(r"'[^']{0,80}'"), "'<s>'"),
]


def error_signature(source: str, message: str) -> str:
    norm = message.strip().splitlines()[0][:200] if message.strip() else "vazio"
    for rx, rep in _NORMALIZE:
        norm = rx.sub(rep, norm)
    return sha256(f"{source}|{norm}")[:32]


def record_error(source: str, message: str, detail: str = "") -> None:
    msg = redact_secrets(message or "")
    _buffer.append(ErrorEvent(ts=utcnow(), source=source, signature=error_signature(source, msg),
                              message=truncate(msg, 1000), detail=truncate(redact_secrets(detail), 4000)))


async def flush() -> int:
    async with _lock:
        if not _buffer:
            return 0
        items = list(_buffer)
        _buffer.clear()
        try:
            async with session_scope() as s:
                s.add_all(items)
        except Exception as e:  # pragma: no cover - falha de banco
            log.warning("falha ao gravar telemetria: %s", e)
            _buffer[:0] = items
            return 0
        # o custo agora está no banco
        for i in items:
            if isinstance(i, LLMCall) and i.cost_usd:
                for d in _dims(i):
                    _pending[d] = max(0.0, _pending.get(d, 0.0) - i.cost_usd)
        return len(items)


async def _loop(interval: float) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            await flush()
        except Exception:  # pragma: no cover
            log.exception("telemetria")


def start_flusher(interval: float = 2.0) -> None:
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop(interval))


async def stop_flusher() -> None:
    global _task
    if _task:
        _task.cancel()
        try:
            await _task
        except (asyncio.CancelledError, Exception):
            pass
        _task = None
    await flush()


def reset() -> None:
    _buffer.clear()
    _pending.clear()
