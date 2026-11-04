"""Serviço unificado de modelos: orçamento → cache → roteamento → chamada → fallback → telemetria.

Nenhum módulo chama provedores diretamente: tudo passa por aqui, garantindo medição de
custos, limites e registro de falhas.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from ultron import telemetry
from ultron.db import session_scope
from ultron.llm.budget import BudgetContext, BudgetExceeded, check
from ultron.models import ResponseCache
from ultron.providers import registry
from ultron.providers.base import ChatMessage, ChatRequest, ProviderError
from ultron.providers.catalog import compute_cost
from ultron.providers.router import ModelChoice, TaskProfile, health, rank
from ultron.utils import canonical_json, estimate_tokens, extract_json, sha256, utcnow


class NoProviderConfigured(Exception):
    def __init__(self) -> None:
        super().__init__(
            "Nenhum provedor de IA configurado. Abra Integrações e adicione pelo menos uma chave "
            "(ex.: Anthropic, OpenAI ou Gemini)."
        )


class AllProvidersFailed(Exception):
    def __init__(self, errors: list[str]):
        super().__init__("Todos os provedores falharam: " + " | ".join(errors[-4:]))
        self.errors = errors


@dataclass
class LLMResult:
    text: str
    provider: str
    model: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: int
    cached: bool = False
    attempts: list[str] = field(default_factory=list)

    def json(self):
        return extract_json(self.text)


def _cache_key(choice: ModelChoice, messages: list[ChatMessage], max_tokens: int, json_mode: bool) -> str:
    return sha256(canonical_json({"p": choice.provider, "m": choice.model, "msgs": [[m.role, m.content] for m in messages],
                                  "mt": max_tokens, "j": json_mode}))


async def _settings(session: AsyncSession) -> dict:
    from ultron.settings_store import get_many

    return await get_many(session, "routing.")


async def available_choices(session: AsyncSession, profile: TaskProfile) -> list[ModelChoice]:
    handles = await registry.get_llm_handles(session)
    st = await _settings(session)
    return rank(profile, handles, preferred=st.get("routing.preferred_providers") or [],
                disabled_models=st.get("routing.disabled_models") or [],
                price_overrides=st.get("routing.price_overrides") or {})


async def complete(
    messages: list[ChatMessage],
    profile: TaskProfile | None = None,
    *,
    ctx: BudgetContext | None = None,
    max_tokens: int = 2048,
    cache: bool = False,
    effort: str | None = None,
    timeout: float = 150.0,
    choices: list[ModelChoice] | None = None,
    max_attempts: int = 3,
) -> LLMResult:
    profile = profile or TaskProfile()
    ctx = ctx or BudgetContext()
    # sessões curtas: nenhuma transação fica aberta durante a chamada ao modelo
    async with session_scope() as session:
        if choices is None:
            handles = await registry.get_llm_handles(session)
            if not handles:
                raise NoProviderConfigured()
            choices = await available_choices(session, profile)
        st = await _settings(session)
    overrides = st.get("routing.price_overrides") or {}
    cache_ttl = int(st.get("routing.cache_ttl_minutes") or 0)
    if not choices:
        raise AllProvidersFailed(["todos os provedores configurados estão temporariamente indisponíveis "
                                  "(circuit breaker aberto) ou desativados"])

    errors: list[str] = []
    prompt_tokens = sum(estimate_tokens(m.content) for m in messages)
    for choice in choices[:max_attempts]:
        est_cost, _ = compute_cost(choice.provider, choice.model, prompt_tokens, min(max_tokens, 1500), overrides)
        key = _cache_key(choice, messages, max_tokens, profile.json) if cache and cache_ttl else None
        async with session_scope() as session:
            await check(session, est_cost, ctx, choice.provider, choice.model)
            if key:
                row = await session.get(ResponseCache, key)
                if row is not None and row.expires_at > utcnow():
                    row.hits += 1
                    telemetry.record_llm_call(provider=choice.provider, model=choice.model, purpose=ctx.purpose,
                                              agent_id=ctx.agent_id, mission_id=ctx.mission_id,
                                              cycle_id=ctx.cycle_id, cached=True, success=True)
                    return LLMResult(row.response["text"], choice.provider, choice.model, 0, 0, 0.0, 0, cached=True,
                                     attempts=[f"{choice.provider}:{choice.model} (cache)"])

        req = ChatRequest(messages=messages, model=choice.model, max_tokens=max_tokens, json_mode=profile.json,
                          effort=effort, timeout=timeout)
        for retry in range(2):
            t0 = time.monotonic()
            try:
                res = await choice.handle.provider.chat(req)
            except ProviderError as e:
                latency = int((time.monotonic() - t0) * 1000)
                telemetry.record_llm_call(provider=choice.provider, model=choice.model, purpose=ctx.purpose,
                                          agent_id=ctx.agent_id, mission_id=ctx.mission_id,
                                          cycle_id=ctx.cycle_id, success=False, latency_ms=latency, error=str(e))
                telemetry.record_error(f"llm:{choice.provider}", str(e))
                if e.retryable and retry == 0:
                    await asyncio.sleep(1.5)
                    continue
                health.failure(choice.provider, choice.model, str(e), auth=e.auth,
                               model_only=(e.status == 404 or e.refusal))
                errors.append(str(e))
                break
            except Exception as e:  # erro inesperado do adaptador
                health.failure(choice.provider, choice.model, repr(e))
                telemetry.record_error(f"llm:{choice.provider}", repr(e))
                errors.append(f"{choice.provider}: {e!r}")
                break
            latency = int((time.monotonic() - t0) * 1000)
            cost, known = compute_cost(choice.provider, choice.model, res.tokens_in, res.tokens_out, overrides)
            health.success(choice.provider, choice.model, latency)
            telemetry.record_llm_call(provider=choice.provider, model=choice.model, purpose=ctx.purpose,
                                      agent_id=ctx.agent_id, mission_id=ctx.mission_id, cycle_id=ctx.cycle_id,
                                      tokens_in=res.tokens_in, tokens_out=res.tokens_out, cost_usd=cost,
                                      latency_ms=latency, success=True, price_known=known)
            ctx.run_spent_usd += cost
            if not res.text.strip():
                errors.append(f"{choice.provider}: resposta vazia ({res.finish_reason})")
                break
            if key:
                async with session_scope() as session:
                    await session.merge(ResponseCache(key=key, model=f"{choice.provider}:{choice.model}",
                                                      response={"text": res.text}, created_at=utcnow(),
                                                      expires_at=utcnow() + timedelta(minutes=cache_ttl), hits=0))
            return LLMResult(res.text, choice.provider, choice.model, res.tokens_in, res.tokens_out, cost,
                             latency, attempts=errors + [f"{choice.provider}:{choice.model}"])
    raise AllProvidersFailed(errors)


async def complete_json(messages: list[ChatMessage], profile: TaskProfile | None = None, **kw) -> tuple[object, LLMResult]:
    """Chamada que exige JSON; tenta reparar uma vez se a resposta vier malformada."""
    profile = profile or TaskProfile()
    profile.json = True
    res = await complete(messages, profile, **kw)
    try:
        return res.json(), res
    except ValueError:
        repair = messages + [
            ChatMessage("assistant", res.text[:4000]),
            ChatMessage("user", "Sua resposta não era JSON válido. Reenvie APENAS o objeto JSON válido, sem comentários."),
        ]
        kw.pop("cache", None)
        res2 = await complete(repair, profile, **kw)
        res2.cost_usd += res.cost_usd
        return res2.json(), res2


async def purge_cache() -> int:
    async with session_scope() as s:
        r = await s.execute(delete(ResponseCache).where(ResponseCache.expires_at < utcnow()))
        return r.rowcount or 0


__all__ = ["complete", "complete_json", "LLMResult", "NoProviderConfigured", "AllProvidersFailed", "BudgetExceeded",
           "BudgetContext", "TaskProfile", "ChatMessage"]
