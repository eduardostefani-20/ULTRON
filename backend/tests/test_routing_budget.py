"""Roteamento, fallback, circuit breaker, cache e orçamento."""

from __future__ import annotations

import pytest

from tests.conftest import FakeProvider, install_fake
from ultron import telemetry
from ultron.db import session_scope
from ultron.llm import budget
from ultron.llm.budget import BudgetContext, BudgetExceeded
from ultron.llm.service import AllProvidersFailed, ChatMessage, NoProviderConfigured, TaskProfile, complete
from ultron.providers.base import ProviderError
from ultron.providers.registry import ProviderHandle
from ultron.providers.router import TaskProfile as TP
from ultron.providers.router import diverse, health, rank


def _h(name, models):
    return ProviderHandle(name, FakeProvider(name), models, "override")


def test_fast_tier_prefers_cheaper_model():
    handles = {"anthropic": _h("anthropic", {"fast": "claude-haiku-5-5", "balanced": "claude-sonnet-5-5"}),
               "openai": _h("openai", {"fast": "gpt-5", "balanced": "gpt-5"})}
    ranked = rank(TP(task="classify", tier="fast"), handles)
    assert ranked[0].model == "claude-haiku-5-5"


def test_preferred_provider_and_diversity():
    handles = {p: _h(p, {"balanced": f"{p}-m"}) for p in ("a", "b", "c")}
    ranked = rank(TP(tier="balanced"), handles, preferred=["c"])
    assert ranked[0].provider == "c"
    assert len({c.provider for c in diverse(ranked, 3)}) == 3


def test_circuit_breaker_excludes_failing_provider():
    health.reset()
    handles = {"a": _h("a", {"balanced": "m"}), "b": _h("b", {"balanced": "m"})}
    for _ in range(3):
        health.failure("a", "m", "erro 500")
    assert [c.provider for c in rank(TP(), handles)] == ["b"]
    health.reset()


async def test_no_provider_configured_is_explicit(app_env):
    with pytest.raises(NoProviderConfigured):
        await complete([ChatMessage("user", "oi")])


async def test_fallback_to_second_provider(app_env):
    bad = FakeProvider("ruim", fail=ProviderError("ruim: erro 500", retryable=False, status=500))
    good = FakeProvider("bom", responder=lambda r: "funcionou")
    install_fake(bad, good)
    # força o ruim em primeiro lugar
    async with session_scope() as s:
        from ultron.settings_store import set_setting

        await set_setting(s, "routing.preferred_providers", ["ruim", "bom"], actor="user:x", actor_is_human_owner=True)
    res = await complete([ChatMessage("user", "oi")], TaskProfile())
    assert res.text == "funcionou" and res.provider == "bom"
    assert any("ruim" in a for a in res.attempts)
    await telemetry.flush()
    snap_calls = len(bad.calls)
    assert snap_calls == 1


async def test_all_providers_failing(app_env):
    install_fake(FakeProvider("x", fail=ProviderError("x: quebrado")))
    with pytest.raises(AllProvidersFailed):
        await complete([ChatMessage("user", "oi")])


async def test_cache_avoids_second_call(app_env):
    p = FakeProvider("c", responder=lambda r: "resposta cacheada")
    install_fake(p)
    msgs = [ChatMessage("user", "pergunta determinística")]
    r1 = await complete(msgs, cache=True)
    r2 = await complete(msgs, cache=True)
    assert r1.text == r2.text and r2.cached and len(p.calls) == 1


async def test_cost_is_recorded(app_env):
    install_fake(FakeProvider("f"))
    res = await complete([ChatMessage("user", "x")], ctx=BudgetContext(purpose="teste"))
    assert res.cost_usd > 0  # preço conservador para modelo desconhecido
    await telemetry.flush()
    budget.clear_cache()
    async with session_scope() as s:
        st = await budget.status(s)
    assert st["spent_usd"] == pytest.approx(res.cost_usd, rel=1e-3)


async def test_monthly_budget_blocks_calls(app_env):
    install_fake(FakeProvider("f"))
    async with session_scope() as s:
        from ultron.settings_store import set_setting

        await set_setting(s, "budget.monthly_brl", 0.0001, actor="user:x", actor_is_human_owner=True)
    with pytest.raises(BudgetExceeded) as e:
        await complete([ChatMessage("user", "x")])
    assert e.value.scope == "monthly"


async def test_agent_run_budget(app_env):
    install_fake(FakeProvider("f"))
    ctx = BudgetContext(agent_id="a", run_budget_usd=0.0000001)
    with pytest.raises(BudgetExceeded) as e:
        await complete([ChatMessage("user", "x")], ctx=ctx)
    assert e.value.scope == "agent_run"


async def test_evolution_budget_share_auto_pauses(app_env):
    install_fake(FakeProvider("f"))
    async with session_scope() as s:
        from ultron.settings_store import set_setting

        await set_setting(s, "budget.monthly_brl", 0.01, actor="user:x", actor_is_human_owner=True)
    with pytest.raises(BudgetExceeded) as e:
        await complete([ChatMessage("user", "x")], ctx=BudgetContext(purpose="evolution.plan"))
    assert e.value.scope in ("evolution", "monthly")
    async with session_scope() as s:
        from ultron.settings_store import get_setting

        if e.value.scope == "evolution":
            assert await get_setting(s, "evolution.paused") is True
