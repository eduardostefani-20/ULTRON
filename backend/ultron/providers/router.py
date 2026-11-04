"""Roteamento de modelos: escolhe o modelo por tarefa, qualidade, custo, saúde e contexto.

Mantém um circuit breaker por provedor/modelo e uma média móvel de latência. Retorna uma
lista ordenada de candidatos, usada como cadeia de fallback.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

from ultron.providers.catalog import TIERS, get_model, price_for
from ultron.providers.registry import ProviderHandle

# afinidade de provedor por tipo de tarefa (pequeno bônus; nunca decisivo sozinho)
TASK_AFFINITY: dict[str, dict[str, float]] = {
    "code": {"anthropic": 1.0, "openai": 0.8, "deepseek": 0.6},
    "plan": {"anthropic": 0.8, "openai": 0.8, "gemini": 0.4},
    "critique": {"anthropic": 0.8, "openai": 0.6, "gemini": 0.5, "xai": 0.4},
    "research": {"gemini": 0.9, "xai": 0.6, "openai": 0.5, "anthropic": 0.5},
    "summarize": {"gemini": 0.6, "anthropic": 0.4},
    "classify": {"gemini": 0.4, "groq": 0.4, "anthropic": 0.4},
    "chat": {"anthropic": 0.5, "openai": 0.5, "gemini": 0.4},
}

# peso do custo por camada de qualidade (rápida = custo importa muito)
COST_WEIGHT = {"fast": 1.2, "balanced": 0.6, "premium": 0.2}


@dataclass
class TaskProfile:
    task: str = "chat"
    tier: str = "balanced"
    json: bool = False
    min_context: int = 0
    prefer_provider: str | None = None
    exclude_providers: set[str] = field(default_factory=set)
    exclude_models: set[str] = field(default_factory=set)


@dataclass
class ModelChoice:
    provider: str
    model: str
    tier: str
    score: float
    handle: ProviderHandle


@dataclass
class _Health:
    consecutive_failures: int = 0
    open_until: float = 0.0
    last_error: str = ""
    latency_ema_ms: float = 0.0
    calls: int = 0
    failures: int = 0
    auth_failed: bool = False


class HealthTracker:
    def __init__(self) -> None:
        self._h: dict[str, _Health] = {}

    def _get(self, key: str) -> _Health:
        return self._h.setdefault(key, _Health())

    def is_open(self, provider: str, model: str) -> bool:
        now = time.monotonic()
        for key in (provider, f"{provider}:{model}"):
            h = self._h.get(key)
            if h and h.open_until > now:
                return True
        return False

    def success(self, provider: str, model: str, latency_ms: float) -> None:
        for key in (provider, f"{provider}:{model}"):
            h = self._get(key)
            h.calls += 1
            h.consecutive_failures = 0
            h.open_until = 0.0
            h.auth_failed = False
            h.latency_ema_ms = latency_ms if h.latency_ema_ms == 0 else 0.8 * h.latency_ema_ms + 0.2 * latency_ms

    def failure(self, provider: str, model: str, error: str, *, auth: bool = False, model_only: bool = False) -> None:
        keys = [f"{provider}:{model}"] if model_only else [provider, f"{provider}:{model}"]
        for key in keys:
            h = self._get(key)
            h.calls += 1
            h.failures += 1
            h.consecutive_failures += 1
            h.last_error = error[:300]
            if auth:
                h.auth_failed = True
                h.open_until = time.monotonic() + 1800
            elif h.consecutive_failures >= 3:
                h.open_until = time.monotonic() + 300

    def snapshot(self) -> dict:
        now = time.monotonic()
        return {
            k: {
                "open": v.open_until > now,
                "open_for_s": max(0, int(v.open_until - now)),
                "consecutive_failures": v.consecutive_failures,
                "last_error": v.last_error,
                "latency_ema_ms": round(v.latency_ema_ms),
                "calls": v.calls,
                "failures": v.failures,
                "auth_failed": v.auth_failed,
            }
            for k, v in self._h.items()
            if ":" not in k
        }

    def latency(self, provider: str) -> float:
        h = self._h.get(provider)
        return h.latency_ema_ms if h else 0.0

    def reset(self) -> None:
        self._h.clear()


health = HealthTracker()


def _resolve_model(handle: ProviderHandle, tier: str) -> tuple[str, str] | None:
    if tier in handle.models:
        return handle.models[tier], tier
    # usa a camada mais próxima disponível
    idx = TIERS.index(tier) if tier in TIERS else 1
    for d in (1, -1, 2, -2):
        j = idx + d
        if 0 <= j < len(TIERS) and TIERS[j] in handle.models:
            return handle.models[TIERS[j]], TIERS[j]
    return None


def rank(profile: TaskProfile, handles: dict[str, ProviderHandle], *, preferred: list[str] | None = None,
         disabled_models: list[str] | None = None, price_overrides: dict | None = None) -> list[ModelChoice]:
    preferred = preferred or []
    disabled = set(disabled_models or [])
    out: list[ModelChoice] = []
    for pid, handle in handles.items():
        if pid in profile.exclude_providers:
            continue
        resolved = _resolve_model(handle, profile.tier)
        if not resolved:
            continue
        model, tier = resolved
        if model in profile.exclude_models or f"{pid}:{model}" in disabled:
            continue
        if health.is_open(pid, model):
            continue
        spec = get_model(pid, model)
        if profile.min_context and spec and spec.context < profile.min_context:
            continue
        score = 3.0 if tier == profile.tier else 1.0
        pin, pout, known = price_for(pid, model, price_overrides)
        blended = (pin + 3 * pout) / 4
        score -= COST_WEIGHT.get(profile.tier, 0.6) * math.log10(1 + blended * 10) / 2
        if not known:
            score -= 0.3
        score += TASK_AFFINITY.get(profile.task, {}).get(pid, 0.0)
        if spec and profile.task in spec.strengths:
            score += 0.3
        if pid in preferred:
            score += 2.0 - 0.3 * preferred.index(pid)
        if profile.prefer_provider == pid:
            score += 5.0
        lat = health.latency(pid)
        if lat > 15000:
            score -= 0.5
        out.append(ModelChoice(pid, model, tier, round(score, 3), handle))
    out.sort(key=lambda c: c.score, reverse=True)
    return out


def diverse(choices: list[ModelChoice], n: int) -> list[ModelChoice]:
    """Seleciona até n modelos de provedores distintos (para o Conselho)."""
    seen: set[str] = set()
    picked: list[ModelChoice] = []
    for c in choices:
        if c.provider in seen:
            continue
        seen.add(c.provider)
        picked.append(c)
        if len(picked) >= n:
            break
    return picked
