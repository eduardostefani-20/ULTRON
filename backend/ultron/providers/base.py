"""Contratos comuns a todos os provedores de IA."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class ChatMessage:
    role: str  # system | user | assistant
    content: str


@dataclass
class ChatRequest:
    messages: list[ChatMessage]
    model: str
    max_tokens: int = 2048
    temperature: float | None = None
    json_mode: bool = False
    effort: str | None = None  # low | medium | high (quando o provedor suporta)
    timeout: float = 120.0


@dataclass
class ChatResult:
    text: str
    model: str
    provider: str
    tokens_in: int = 0
    tokens_out: int = 0
    finish_reason: str = ""
    extra: dict = field(default_factory=dict)


class ProviderError(Exception):
    def __init__(self, message: str, *, retryable: bool = False, status: int | None = None, auth: bool = False,
                 refusal: bool = False):
        super().__init__(message)
        self.retryable = retryable
        self.status = status
        self.auth = auth
        self.refusal = refusal


class LLMProvider(Protocol):
    name: str

    async def chat(self, req: ChatRequest) -> ChatResult: ...

    async def embed(self, texts: list[str], model: str) -> list[list[float]]: ...

    async def list_models(self) -> list[str]: ...


def split_system(messages: list[ChatMessage]) -> tuple[str, list[ChatMessage]]:
    """Separa instruções de sistema e normaliza a alternância user/assistant."""
    system = "\n\n".join(m.content for m in messages if m.role == "system").strip()
    convo: list[ChatMessage] = []
    for m in messages:
        if m.role == "system":
            continue
        role = "assistant" if m.role == "assistant" else "user"
        if convo and convo[-1].role == role:
            convo[-1] = ChatMessage(role, convo[-1].content + "\n\n" + m.content)
        else:
            convo.append(ChatMessage(role, m.content))
    if not convo or convo[0].role != "user":
        convo.insert(0, ChatMessage("user", "(início da conversa)"))
    return system, convo


def classify_http_error(status: int, body: str, provider: str) -> ProviderError:
    snippet = (body or "")[:300]
    if status in (401, 403):
        return ProviderError(f"{provider}: credencial inválida ou sem permissão ({status})", status=status, auth=True)
    if status == 429:
        return ProviderError(f"{provider}: limite de requisições/cota ({snippet})", status=status, retryable=True)
    if status >= 500:
        return ProviderError(f"{provider}: erro do servidor {status}", status=status, retryable=True)
    if status == 404:
        return ProviderError(f"{provider}: modelo ou endpoint não encontrado ({snippet})", status=status)
    return ProviderError(f"{provider}: requisição rejeitada {status}: {snippet}", status=status)
