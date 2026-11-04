"""Adaptador Google Gemini (API generativelanguage v1beta)."""

from __future__ import annotations

import httpx

from ultron.providers.base import ChatRequest, ChatResult, ProviderError, classify_http_error, split_system

BASE = "https://generativelanguage.googleapis.com/v1beta"


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str, *, transport: httpx.AsyncBaseTransport | None = None, base_url: str = ""):
        self.api_key = api_key
        self.base = (base_url.rstrip("/") + "/v1beta") if base_url and "googleapis" not in base_url else BASE
        self._transport = transport

    def _client(self, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=timeout, transport=self._transport,
                                 headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"})

    async def chat(self, req: ChatRequest) -> ChatResult:
        system, convo = split_system(req.messages)
        body: dict = {
            "contents": [
                {"role": "model" if m.role == "assistant" else "user", "parts": [{"text": m.content}]} for m in convo
            ],
            "generationConfig": {"maxOutputTokens": req.max_tokens},
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        if req.temperature is not None:
            body["generationConfig"]["temperature"] = req.temperature
        if req.json_mode:
            body["generationConfig"]["responseMimeType"] = "application/json"
        if req.effort == "low" and "2.5-flash" in req.model:
            body["generationConfig"]["thinkingConfig"] = {"thinkingBudget": 0}
        url = f"{self.base}/models/{req.model}:generateContent"
        try:
            async with self._client(req.timeout) as client:
                resp = await client.post(url, json=body)
        except httpx.TimeoutException as e:
            raise ProviderError("gemini: tempo esgotado", retryable=True) from e
        except httpx.HTTPError as e:
            raise ProviderError(f"gemini: falha de rede ({e.__class__.__name__})", retryable=True) from e
        if resp.status_code >= 400:
            if resp.status_code == 400 and "API key not valid" in resp.text:
                raise ProviderError("gemini: chave de API inválida", status=400, auth=True)
            raise classify_http_error(resp.status_code, resp.text, self.name)
        data = resp.json()
        feedback = data.get("promptFeedback") or {}
        if feedback.get("blockReason"):
            raise ProviderError(f"gemini: solicitação bloqueada ({feedback['blockReason']})", refusal=True)
        cands = data.get("candidates") or []
        if not cands:
            raise ProviderError("gemini: resposta sem candidatos", retryable=True)
        parts = (cands[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        finish = cands[0].get("finishReason", "")
        if finish == "SAFETY" and not text:
            raise ProviderError("gemini: resposta bloqueada por segurança", refusal=True)
        usage = data.get("usageMetadata") or {}
        out_tokens = int(usage.get("candidatesTokenCount") or 0) + int(usage.get("thoughtsTokenCount") or 0)
        return ChatResult(text=text, model=data.get("modelVersion") or req.model, provider=self.name,
                          tokens_in=int(usage.get("promptTokenCount") or 0), tokens_out=out_tokens,
                          finish_reason=finish)

    async def embed(self, texts: list[str], model: str) -> list[list[float]]:
        url = f"{self.base}/models/{model}:batchEmbedContents"
        body = {"requests": [{"model": f"models/{model}", "content": {"parts": [{"text": t}]},
                              "outputDimensionality": 768} for t in texts]}
        try:
            async with self._client(60) as client:
                resp = await client.post(url, json=body)
        except httpx.HTTPError as e:
            raise ProviderError("gemini: falha de rede em embeddings", retryable=True) from e
        if resp.status_code >= 400:
            raise classify_http_error(resp.status_code, resp.text, self.name)
        return [e["values"] for e in resp.json().get("embeddings", [])]

    async def list_models(self) -> list[str]:
        try:
            async with self._client(20) as client:
                resp = await client.get(f"{self.base}/models", params={"pageSize": 200})
        except httpx.HTTPError as e:
            raise ProviderError(f"gemini: não foi possível conectar ({e.__class__.__name__})", retryable=True) from e
        if resp.status_code >= 400:
            if "API key not valid" in resp.text:
                raise ProviderError("gemini: chave de API inválida", status=400, auth=True)
            raise classify_http_error(resp.status_code, resp.text, self.name)
        out = []
        for m in resp.json().get("models", []):
            if "generateContent" in (m.get("supportedGenerationMethods") or []) or "embedContent" in (
                m.get("supportedGenerationMethods") or []
            ):
                out.append(str(m.get("name", "")).removeprefix("models/"))
        return sorted(out)
