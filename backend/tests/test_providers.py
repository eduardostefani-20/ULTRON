"""Adaptadores de provedores: formato real das requisições/respostas (sem chamar APIs pagas)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from ultron.providers.anthropic_provider import FALLBACK_BETA, AnthropicProvider
from ultron.providers.base import ChatMessage, ChatRequest, ProviderError, split_system
from ultron.providers.catalog import compute_cost, price_for
from ultron.providers.gemini import GeminiProvider
from ultron.providers.openai_compat import OpenAICompatProvider


def test_split_system_merges_and_starts_with_user():
    system, convo = split_system([ChatMessage("system", "regra"), ChatMessage("assistant", "oi"),
                                  ChatMessage("user", "a"), ChatMessage("user", "b")])
    assert system == "regra"
    assert [m.role for m in convo] == ["user", "assistant", "user"]
    assert convo[-1].content == "a\n\nb"


async def test_openai_request_format_and_parsing():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(200, json={"model": "gpt-5-mini", "choices": [{"message": {"content": "olá"},
                                                                            "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": 12, "completion_tokens": 3}})

    p = OpenAICompatProvider("openai", "https://api.openai.com/v1", "sk-x", transport=httpx.MockTransport(handler))
    r = await p.chat(ChatRequest([ChatMessage("system", "s"), ChatMessage("user", "json?")], "gpt-5-mini",
                                 max_tokens=99, temperature=0.3, json_mode=True))
    assert r.text == "olá" and r.tokens_in == 12 and r.tokens_out == 3
    body = seen["body"]
    assert body["max_completion_tokens"] == 99 and "max_tokens" not in body
    assert "temperature" not in body  # modelo de raciocínio não aceita temperature
    assert body["response_format"] == {"type": "json_object"}
    assert body["messages"][0] == {"role": "system", "content": "s"}
    assert seen["auth"] == "Bearer sk-x"


async def test_openai_compatible_errors_are_classified():
    def handler(request):
        return httpx.Response(401, json={"error": "bad key"})

    p = OpenAICompatProvider("deepseek", "https://api.deepseek.com/v1", "k", transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError) as e:
        await p.chat(ChatRequest([ChatMessage("user", "x")], "deepseek-chat"))
    assert e.value.auth and not e.value.retryable


async def test_ollama_uses_v1_path():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}], "usage": {}})

    p = OpenAICompatProvider("ollama", "http://localhost:11434", "", transport=httpx.MockTransport(handler))
    await p.chat(ChatRequest([ChatMessage("user", "x")], "llama3.2"))
    assert seen["url"] == "http://localhost:11434/v1/chat/completions"


async def test_gemini_parsing_excludes_thoughts_and_counts_tokens():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        seen["key"] = request.headers["x-goog-api-key"]
        return httpx.Response(200, json={
            "candidates": [{"content": {"parts": [{"text": "pensando...", "thought": True}, {"text": "resposta"}]},
                            "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 20, "candidatesTokenCount": 5, "thoughtsTokenCount": 7}})

    p = GeminiProvider("AIza-test", transport=httpx.MockTransport(handler))
    r = await p.chat(ChatRequest([ChatMessage("system", "sys"), ChatMessage("user", "oi")], "gemini-2.5-flash",
                                 json_mode=True, effort="low"))
    assert r.text == "resposta" and r.tokens_in == 20 and r.tokens_out == 12
    assert seen["body"]["systemInstruction"]["parts"][0]["text"] == "sys"
    assert seen["body"]["generationConfig"]["responseMimeType"] == "application/json"
    assert seen["body"]["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 0}
    assert seen["key"] == "AIza-test"


async def test_gemini_block_is_refusal():
    def handler(request):
        return httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}})

    p = GeminiProvider("k", transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError) as e:
        await p.chat(ChatRequest([ChatMessage("user", "x")], "gemini-2.5-flash"))
    assert e.value.refusal


class _FakeMessages:
    def __init__(self, resp):
        self.resp = resp
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return self.resp


class _FakeAnthropic:
    def __init__(self, resp):
        self.messages = _FakeMessages(resp)
        self.beta = SimpleNamespace(messages=_FakeMessages(resp))


def _resp(text="ok", stop="end_turn"):
    return SimpleNamespace(content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)],
                           stop_reason=stop, stop_details=None, model="claude-haiku-5-5",
                           usage=SimpleNamespace(input_tokens=30, output_tokens=9))


async def test_anthropic_request_shape():
    fake = _FakeAnthropic(_resp("olá"))
    p = AnthropicProvider("k", client=fake)
    r = await p.chat(ChatRequest([ChatMessage("system", "regras"), ChatMessage("user", "oi")], "claude-haiku-5-5",
                                 temperature=0.7, json_mode=True, effort="low"))
    kw = fake.messages.kwargs
    assert r.text == "olá" and r.tokens_in == 30 and r.tokens_out == 9
    assert "temperature" not in kw  # rejeitado pela API atual
    assert kw["output_config"] == {"effort": "low"}
    assert "JSON" in kw["system"] and kw["messages"] == [{"role": "user", "content": "oi"}]


async def test_anthropic_opus_uses_server_side_fallback():
    fake = _FakeAnthropic(_resp())
    p = AnthropicProvider("k", client=fake)
    await p.chat(ChatRequest([ChatMessage("user", "oi")], "claude-opus-5-5"))
    kw = fake.beta.messages.kwargs
    assert kw["fallbacks"] == "default" and kw["betas"] == [FALLBACK_BETA]


async def test_anthropic_refusal_raises():
    p = AnthropicProvider("k", client=_FakeAnthropic(_resp("", stop="refusal")))
    with pytest.raises(ProviderError) as e:
        await p.chat(ChatRequest([ChatMessage("user", "x")], "claude-haiku-5-5"))
    assert e.value.refusal


def test_pricing_known_unknown_and_override():
    assert price_for("anthropic", "claude-haiku-5-5")[:2] == (0.10, 0.50)
    pin, pout, known = price_for("openai", "modelo-desconhecido")
    assert not known and pin >= 3.0  # conservador
    assert price_for("ollama", "qualquer") == (0.0, 0.0, True)
    cost, _ = compute_cost("anthropic", "claude-opus-5-5", 1_000_000, 1_000_000)
    assert cost == pytest.approx(24.0)
    assert price_for("x", "y", {"x:y": {"input": 1, "output": 2}}) == (1.0, 2.0, True)


def test_suggest_models_replaces_missing_with_best_available():
    from ultron.providers.catalog import suggest_models

    available = ["gemini-3.0-flash", "gemini-3.0-flash-lite", "gemini-3.0-pro-preview", "gemini-3.0-pro",
                 "gemini-embedding-002", "gemini-3.0-flash-image", "gemini-2.0-flash"]
    out = suggest_models("gemini", available, {"fast": "gemini-2.5-flash-lite", "balanced": "gemini-2.0-flash",
                                                "premium": "gemini-2.5-pro"})
    assert out == {"fast": "gemini-3.0-flash-lite", "balanced": "gemini-2.0-flash", "premium": "gemini-3.0-pro"}
    groq = suggest_models("groq", ["llama-3.1-8b-instant", "llama-3.3-70b-versatile", "openai/gpt-oss-120b",
                                   "whisper-large-v3"], {"fast": "x", "balanced": "y", "premium": "z"})
    assert groq == {"fast": "llama-3.1-8b-instant", "balanced": "llama-3.3-70b-versatile",
                    "premium": "openai/gpt-oss-120b"}
