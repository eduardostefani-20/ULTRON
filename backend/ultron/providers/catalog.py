"""Catálogo de provedores e modelos (capacidades e preços de referência).

Preços em USD por 1 milhão de tokens. São valores de REFERÊNCIA e podem ser sobrescritos em
Configurações → Roteamento (routing.price_overrides). Modelos não catalogados usam um preço
conservador para que o controle de orçamento nunca subestime gastos.
"""

from __future__ import annotations

from dataclasses import dataclass, field

UNKNOWN_PRICE = (3.0, 15.0)


@dataclass(frozen=True)
class ModelSpec:
    provider: str
    id: str
    tier: str  # fast | balanced | premium | embedding
    context: int
    input_per_m: float
    output_per_m: float
    json: bool = True
    reasoning: bool = False
    strengths: tuple[str, ...] = field(default_factory=tuple)
    dims: int = 0


@dataclass(frozen=True)
class ProviderInfo:
    id: str
    name: str
    kind: str  # llm | search | vcs
    base_url: str = ""
    key_url: str = ""
    note: str = ""
    key_required: bool = True
    openai_compatible: bool = False


PROVIDERS: dict[str, ProviderInfo] = {
    "anthropic": ProviderInfo("anthropic", "Anthropic Claude", "llm", "https://api.anthropic.com",
                              "https://console.anthropic.com/settings/keys",
                              "Haiku 5.5 é muito econômico; Opus 5.5 para tarefas críticas."),
    "openai": ProviderInfo("openai", "OpenAI", "llm", "https://api.openai.com/v1",
                           "https://platform.openai.com/api-keys", openai_compatible=True),
    "gemini": ProviderInfo("gemini", "Google Gemini", "llm", "https://generativelanguage.googleapis.com",
                           "https://aistudio.google.com/apikey", "Camada gratuita SEM cartão (com limites de uso)."),
    "xai": ProviderInfo("xai", "xAI Grok", "llm", "https://api.x.ai/v1", "https://console.x.ai",
                        openai_compatible=True),
    "deepseek": ProviderInfo("deepseek", "DeepSeek", "llm", "https://api.deepseek.com/v1",
                             "https://platform.deepseek.com/api_keys", "Muito barato.", openai_compatible=True),
    "groq": ProviderInfo("groq", "Groq", "llm", "https://api.groq.com/openai/v1", "https://console.groq.com/keys",
                         "Rápido; camada gratuita SEM cartão.", openai_compatible=True),
    "openrouter": ProviderInfo("openrouter", "OpenRouter", "llm", "https://openrouter.ai/api/v1",
                               "https://openrouter.ai/keys", "Centenas de modelos; alguns gratuitos (sufixo :free).",
                               openai_compatible=True),
    "mistral": ProviderInfo("mistral", "Mistral", "llm", "https://api.mistral.ai/v1",
                            "https://console.mistral.ai/api-keys", openai_compatible=True),
    "ollama": ProviderInfo("ollama", "Modelos locais (Ollama)", "llm", "http://localhost:11434",
                           "https://ollama.com", "Custo zero; requer servidor próprio com Ollama.",
                           key_required=False, openai_compatible=True),
    "tavily": ProviderInfo("tavily", "Tavily (busca web)", "search", "https://api.tavily.com",
                           "https://app.tavily.com", "1.000 buscas/mês gratuitas."),
    "brave": ProviderInfo("brave", "Brave Search API", "search", "https://api.search.brave.com",
                          "https://api-dashboard.search.brave.com"),
    "serper": ProviderInfo("serper", "Serper (Google)", "search", "https://google.serper.dev", "https://serper.dev"),
    "searxng": ProviderInfo("searxng", "SearXNG (auto-hospedado)", "search", "", "https://docs.searxng.org",
                            key_required=False),
    "github": ProviderInfo("github", "GitHub", "vcs", "https://api.github.com",
                           "https://github.com/settings/personal-access-tokens/new",
                           "Token fine-grained com acesso Contents/Pull requests ao repositório do ULTRON."),
}

MODELS: list[ModelSpec] = [
    # Anthropic (preços oficiais de referência)
    ModelSpec("anthropic", "claude-haiku-5-5", "fast", 1_000_000, 0.10, 0.50, strengths=("chat", "classify", "summarize")),
    ModelSpec("anthropic", "claude-sonnet-5-5", "balanced", 1_000_000, 2.00, 10.00,
              strengths=("code", "chat", "plan", "critique")),
    ModelSpec("anthropic", "claude-opus-5-5", "premium", 1_000_000, 4.00, 20.00, reasoning=True,
              strengths=("code", "plan", "critique", "research", "reasoning")),
    # OpenAI
    ModelSpec("openai", "gpt-5-nano", "fast", 400_000, 0.05, 0.40, reasoning=True, strengths=("classify", "summarize")),
    ModelSpec("openai", "gpt-5-mini", "balanced", 400_000, 0.25, 2.00, reasoning=True, strengths=("chat", "code", "plan")),
    ModelSpec("openai", "gpt-5", "premium", 400_000, 1.25, 10.00, reasoning=True,
              strengths=("code", "reasoning", "plan", "critique")),
    ModelSpec("openai", "text-embedding-3-small", "embedding", 8_000, 0.02, 0.0, dims=1536),
    # Google Gemini
    ModelSpec("gemini", "gemini-2.5-flash-lite", "fast", 1_000_000, 0.10, 0.40, strengths=("classify", "summarize", "chat")),
    ModelSpec("gemini", "gemini-2.5-flash", "balanced", 1_000_000, 0.30, 2.50, strengths=("research", "chat", "summarize")),
    ModelSpec("gemini", "gemini-2.5-pro", "premium", 1_000_000, 1.25, 10.00, reasoning=True,
              strengths=("research", "reasoning", "code")),
    ModelSpec("gemini", "gemini-embedding-001", "embedding", 2_048, 0.15, 0.0, dims=768),
    # xAI
    ModelSpec("xai", "grok-4-fast-non-reasoning", "fast", 2_000_000, 0.20, 0.50, strengths=("chat", "research")),
    ModelSpec("xai", "grok-4-fast-reasoning", "balanced", 2_000_000, 0.20, 0.50, reasoning=True, strengths=("reasoning",)),
    ModelSpec("xai", "grok-4", "premium", 256_000, 3.00, 15.00, reasoning=True, strengths=("reasoning", "research")),
    # DeepSeek
    ModelSpec("deepseek", "deepseek-chat", "balanced", 128_000, 0.28, 0.42, strengths=("code", "chat")),
    ModelSpec("deepseek", "deepseek-reasoner", "premium", 128_000, 0.28, 0.42, reasoning=True, strengths=("reasoning",)),
    # Groq
    ModelSpec("groq", "llama-3.1-8b-instant", "fast", 128_000, 0.05, 0.08, strengths=("classify",)),
    ModelSpec("groq", "llama-3.3-70b-versatile", "balanced", 128_000, 0.59, 0.79, strengths=("chat",)),
    ModelSpec("groq", "openai/gpt-oss-120b", "premium", 128_000, 0.15, 0.75, reasoning=True, strengths=("reasoning", "code")),
    # Mistral
    ModelSpec("mistral", "mistral-small-latest", "fast", 128_000, 0.10, 0.30, strengths=("chat",)),
    ModelSpec("mistral", "mistral-medium-latest", "balanced", 128_000, 0.40, 2.00, strengths=("chat", "code")),
    ModelSpec("mistral", "mistral-large-latest", "premium", 128_000, 2.00, 6.00, strengths=("reasoning",)),
    ModelSpec("mistral", "mistral-embed", "embedding", 8_000, 0.10, 0.0, dims=1024),
    # OpenRouter (exemplos; qualquer modelo do OpenRouter pode ser configurado)
    ModelSpec("openrouter", "google/gemini-2.5-flash-lite", "fast", 1_000_000, 0.10, 0.40),
    ModelSpec("openrouter", "deepseek/deepseek-chat", "balanced", 128_000, 0.30, 0.90, strengths=("code",)),
    ModelSpec("openrouter", "anthropic/claude-sonnet-5.5", "premium", 1_000_000, 2.00, 10.00, strengths=("code",)),
]

_BY_KEY = {(m.provider, m.id): m for m in MODELS}

TIERS = ("fast", "balanced", "premium")


def get_model(provider: str, model_id: str) -> ModelSpec | None:
    return _BY_KEY.get((provider, model_id))


def models_for(provider: str) -> list[ModelSpec]:
    return [m for m in MODELS if m.provider == provider]


def default_model(provider: str, tier: str) -> str | None:
    for m in MODELS:
        if m.provider == provider and m.tier == tier:
            return m.id
    return None


def embedding_model(provider: str) -> ModelSpec | None:
    for m in MODELS:
        if m.provider == provider and m.tier == "embedding":
            return m
    return None


def price_for(provider: str, model_id: str, overrides: dict | None = None) -> tuple[float, float, bool]:
    """Retorna (preço entrada, preço saída, preço_conhecido)."""
    if provider == "ollama":
        return 0.0, 0.0, True
    key = f"{provider}:{model_id}"
    if overrides and key in overrides:
        o = overrides[key]
        return float(o.get("input", UNKNOWN_PRICE[0])), float(o.get("output", UNKNOWN_PRICE[1])), True
    spec = get_model(provider, model_id)
    if spec:
        return spec.input_per_m, spec.output_per_m, True
    return UNKNOWN_PRICE[0], UNKNOWN_PRICE[1], False


def compute_cost(provider: str, model_id: str, tokens_in: int, tokens_out: int, overrides: dict | None = None
                 ) -> tuple[float, bool]:
    pin, pout, known = price_for(provider, model_id, overrides)
    return tokens_in / 1e6 * pin + tokens_out / 1e6 * pout, known


# Palavras-chave por camada para escolher modelos disponíveis quando os padrões não existem na conta.
TIER_HINTS: dict[str, dict[str, tuple[tuple[str, ...], tuple[str, ...]]]] = {  # (precisa conter, não pode conter)
    "gemini": {"fast": (("flash-lite",), ()), "balanced": (("flash",), ("lite",)), "premium": (("pro",), ())},
    "anthropic": {"fast": (("haiku",), ()), "balanced": (("sonnet",), ()), "premium": (("opus",), ())},
    "groq": {"fast": (("instant",), ()), "balanced": (("versatile",), ()), "premium": (("120b",), ())},
    "openai": {"fast": (("nano",), ()), "balanced": (("mini",), ("nano",)), "premium": (("gpt-",), ("mini", "nano"))},
    "mistral": {"fast": (("small",), ()), "balanced": (("medium",), ()), "premium": (("large",), ())},
    "deepseek": {"fast": (("chat",), ()), "balanced": (("chat",), ()), "premium": (("reasoner",), ())},
}
_NON_CHAT = ("embed", "tts", "audio", "image", "imagen", "veo", "whisper", "guard", "live", "aqa", "moderation",
             "transcribe", "realtime", "search", "computer", "robotics", "learnlm")


def _version_key(model_id: str) -> tuple:
    import re

    nums = [int(n) for n in re.findall(r"\d+", model_id)]
    unstable = any(w in model_id for w in ("preview", "exp", "beta", "alpha"))
    return (not unstable, nums, -len(model_id))


def suggest_models(provider: str, available: list[str], current: dict[str, str | None]) -> dict[str, str]:
    """Mantém os modelos configurados que existem; troca os ausentes pelo melhor equivalente disponível."""
    hints = TIER_HINTS.get(provider)
    avail = [m for m in available if not any(w in m.lower() for w in _NON_CHAT)]
    out: dict[str, str] = {}
    for tier in TIERS:
        cur = current.get(tier)
        if cur and cur in available:
            out[tier] = cur
            continue
        if not hints or not avail:
            if cur:
                out[tier] = cur
            continue
        must, must_not = hints[tier]
        cands = [m for m in avail if all(w in m.lower() for w in must) and not any(w in m.lower() for w in must_not)]
        if cands:
            out[tier] = sorted(cands, key=_version_key, reverse=True)[0]
        elif cur:
            out[tier] = cur
    return out
