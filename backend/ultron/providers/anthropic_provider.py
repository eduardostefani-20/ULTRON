"""Adaptador Anthropic (Claude) usando o SDK oficial ``anthropic``.

Particularidades dos modelos atuais (Claude 5.x):
- não enviar ``temperature`` (rejeitado pela API);
- profundidade de raciocínio controlada por ``output_config.effort``;
- sem "prefill" de resposta: JSON é pedido via instrução de sistema;
- ``stop_reason == "refusal"`` é tratado como recusa (o roteador tenta outro provedor);
- Opus 5.5 / Sonnet 5.5 / Fable 5.1 usam ``fallbacks: "default"`` (fallback de recusa no servidor).
"""

from __future__ import annotations

from typing import Any

import anthropic

from ultron.providers.base import ChatRequest, ChatResult, ProviderError, split_system

FALLBACK_BETA = "server-side-fallback-2026-07-01"
FALLBACK_MODELS = {"claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5-1"}
EFFORT_MODELS_PREFIX = ("claude-opus-5", "claude-sonnet-5", "claude-haiku-5", "claude-fable-5", "claude-opus-4-")

JSON_INSTRUCTION = (
    "\n\nFORMATO OBRIGATÓRIO: responda apenas com um único objeto JSON válido, sem texto antes ou depois "
    "e sem blocos de código."
)


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str, *, client: Any | None = None, base_url: str | None = None):
        self.api_key = api_key
        if client is not None:
            self._client = client
        else:
            # base_url sempre explícita: variáveis de ambiente do host (ex.: ANTHROPIC_BASE_URL)
            # nunca devem redirecionar as chamadas nem as credenciais do ULTRON
            self._client = anthropic.AsyncAnthropic(api_key=api_key, max_retries=1, timeout=180.0,
                                                    base_url=base_url or "https://api.anthropic.com")

    async def chat(self, req: ChatRequest) -> ChatResult:
        system, convo = split_system(req.messages)
        if req.json_mode:
            system = (system or "") + JSON_INSTRUCTION
        params: dict[str, Any] = {
            "model": req.model,
            "max_tokens": req.max_tokens,
            "messages": [{"role": m.role, "content": m.content} for m in convo],
        }
        if system:
            params["system"] = system
        if req.effort and req.model.startswith(EFFORT_MODELS_PREFIX):
            params["output_config"] = {"effort": req.effort}
        try:
            client = self._client.with_options(timeout=req.timeout) if hasattr(self._client, "with_options") else self._client
            if req.model in FALLBACK_MODELS:
                try:
                    resp = await client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **params)
                except anthropic.BadRequestError as e:
                    if "fallback" not in str(e).lower():
                        raise
                    resp = await client.messages.create(**params)
            else:
                resp = await client.messages.create(**params)
        except anthropic.AuthenticationError as e:
            raise ProviderError("anthropic: chave de API inválida", status=401, auth=True) from e
        except anthropic.PermissionDeniedError as e:
            raise ProviderError("anthropic: chave sem permissão para este recurso", status=403, auth=True) from e
        except anthropic.NotFoundError as e:
            raise ProviderError(f"anthropic: modelo não encontrado ({req.model})", status=404) from e
        except anthropic.RateLimitError as e:
            raise ProviderError("anthropic: limite de requisições atingido", status=429, retryable=True) from e
        except anthropic.BadRequestError as e:
            raise ProviderError(f"anthropic: requisição rejeitada: {getattr(e, 'message', e)}", status=400) from e
        except anthropic.APIStatusError as e:
            raise ProviderError(f"anthropic: erro {e.status_code}", status=e.status_code,
                                retryable=e.status_code >= 500) from e
        except anthropic.APITimeoutError as e:
            raise ProviderError("anthropic: tempo esgotado", retryable=True) from e
        except anthropic.APIConnectionError as e:
            raise ProviderError("anthropic: falha de conexão", retryable=True) from e

        stop_reason = getattr(resp, "stop_reason", "") or ""
        if stop_reason == "refusal":
            details = getattr(resp, "stop_details", None)
            category = getattr(details, "category", None) if details else None
            raise ProviderError(f"anthropic: o modelo recusou a solicitação (categoria: {category})", refusal=True)
        text = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text")
        usage = getattr(resp, "usage", None)
        return ChatResult(
            text=text,
            model=getattr(resp, "model", req.model) or req.model,
            provider=self.name,
            tokens_in=int(getattr(usage, "input_tokens", 0) or 0),
            tokens_out=int(getattr(usage, "output_tokens", 0) or 0),
            finish_reason=stop_reason,
        )

    async def embed(self, texts: list[str], model: str) -> list[list[float]]:
        raise ProviderError("anthropic: embeddings não disponíveis neste provedor")

    async def list_models(self) -> list[str]:
        try:
            page = await self._client.models.list()
            ids = [m.id for m in getattr(page, "data", [])]
            return sorted(ids)
        except anthropic.AuthenticationError as e:
            raise ProviderError("anthropic: chave de API inválida", status=401, auth=True) from e
        except anthropic.APIConnectionError as e:
            raise ProviderError("anthropic: falha de conexão", retryable=True) from e
        except anthropic.APIStatusError as e:
            raise ProviderError(f"anthropic: erro {e.status_code}", status=e.status_code) from e
