"""Adaptador para APIs compatíveis com OpenAI (OpenAI, xAI, DeepSeek, Groq, OpenRouter,
Mistral, Ollama, LM Studio...)."""

from __future__ import annotations

import httpx

from ultron.providers.base import ChatRequest, ChatResult, ProviderError, classify_http_error, split_system
from ultron.providers.catalog import get_model

# provedores que aceitam response_format={"type": "json_object"}
_JSON_MODE = {"openai", "xai", "deepseek", "groq", "mistral", "openrouter", "ollama"}


class OpenAICompatProvider:
    def __init__(self, name: str, base_url: str, api_key: str = "", *, transport: httpx.AsyncBaseTransport | None = None,
                 extra_headers: dict | None = None):
        self.name = name
        base = base_url.rstrip("/")
        if name == "ollama" and not base.endswith("/v1"):
            base = base + "/v1"
        self.base_url = base
        self.api_key = api_key
        self._transport = transport
        self._headers = {"Content-Type": "application/json", **(extra_headers or {})}
        if api_key:
            self._headers["Authorization"] = f"Bearer {api_key}"
        if name == "openrouter":
            self._headers.setdefault("X-Title", "ULTRON")

    def _client(self, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.base_url, headers=self._headers, timeout=timeout,
                                 transport=self._transport)

    async def chat(self, req: ChatRequest) -> ChatResult:
        system, convo = split_system(req.messages)
        messages = ([{"role": "system", "content": system}] if system else []) + [
            {"role": m.role, "content": m.content} for m in convo
        ]
        spec = get_model(self.name, req.model)
        body: dict = {"model": req.model, "messages": messages}
        if self.name == "openai":
            body["max_completion_tokens"] = req.max_tokens
        else:
            body["max_tokens"] = req.max_tokens
        reasoning = bool(spec and spec.reasoning)
        if req.temperature is not None and not reasoning:
            body["temperature"] = req.temperature
        if reasoning and self.name == "openai" and req.effort:
            body["reasoning_effort"] = {"low": "minimal", "medium": "low", "high": "medium"}.get(req.effort, "low")
        if req.json_mode and self.name in _JSON_MODE:
            body["response_format"] = {"type": "json_object"}
        try:
            async with self._client(req.timeout) as client:
                resp = await client.post("/chat/completions", json=body)
        except httpx.TimeoutException as e:
            raise ProviderError(f"{self.name}: tempo esgotado ({e.__class__.__name__})", retryable=True) from e
        except httpx.HTTPError as e:
            raise ProviderError(f"{self.name}: falha de rede ({e.__class__.__name__}: {e})", retryable=True) from e
        if resp.status_code >= 400:
            # alguns provedores rejeitam response_format; repete sem ele uma vez
            if resp.status_code == 400 and "response_format" in body and "response_format" in resp.text:
                body.pop("response_format")
                async with self._client(req.timeout) as client:
                    resp = await client.post("/chat/completions", json=body)
            if resp.status_code >= 400:
                raise classify_http_error(resp.status_code, resp.text, self.name)
        data = resp.json()
        try:
            choice = data["choices"][0]
            text = choice["message"].get("content") or ""
        except (KeyError, IndexError, TypeError) as e:
            raise ProviderError(f"{self.name}: resposta inesperada", retryable=True) from e
        usage = data.get("usage") or {}
        return ChatResult(
            text=text,
            model=data.get("model") or req.model,
            provider=self.name,
            tokens_in=int(usage.get("prompt_tokens") or 0),
            tokens_out=int(usage.get("completion_tokens") or 0),
            finish_reason=choice.get("finish_reason") or "",
        )

    async def embed(self, texts: list[str], model: str) -> list[list[float]]:
        async with self._client(60) as client:
            try:
                resp = await client.post("/embeddings", json={"model": model, "input": texts})
            except httpx.HTTPError as e:
                raise ProviderError(f"{self.name}: falha de rede em embeddings", retryable=True) from e
        if resp.status_code >= 400:
            raise classify_http_error(resp.status_code, resp.text, self.name)
        data = resp.json()
        items = sorted(data.get("data", []), key=lambda d: d.get("index", 0))
        return [d["embedding"] for d in items]

    async def list_models(self) -> list[str]:
        async with self._client(20) as client:
            try:
                resp = await client.get("/models")
            except httpx.HTTPError as e:
                raise ProviderError(f"{self.name}: não foi possível conectar ({e.__class__.__name__})",
                                    retryable=True) from e
        if resp.status_code >= 400:
            raise classify_http_error(resp.status_code, resp.text, self.name)
        data = resp.json()
        return sorted(str(m.get("id")) for m in data.get("data", []) if m.get("id"))
