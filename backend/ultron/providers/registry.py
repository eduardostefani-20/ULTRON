"""Registro de provedores ativos: combina chaves do ambiente e da tela Integrações."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ultron.config import get_settings
from ultron.models import ProviderCredential
from ultron.providers.anthropic_provider import AnthropicProvider
from ultron.providers.base import LLMProvider
from ultron.providers.catalog import PROVIDERS, TIERS, default_model, embedding_model
from ultron.providers.gemini import GeminiProvider
from ultron.providers.openai_compat import OpenAICompatProvider
from ultron.security.vault import decrypt_secret

ENV_KEYS = {
    "openai": "openai_api_key",
    "anthropic": "anthropic_api_key",
    "gemini": "gemini_api_key",
    "xai": "xai_api_key",
    "deepseek": "deepseek_api_key",
    "groq": "groq_api_key",
    "openrouter": "openrouter_api_key",
    "mistral": "mistral_api_key",
    "tavily": "tavily_api_key",
    "brave": "brave_api_key",
    "serper": "serper_api_key",
    "github": "github_token",
}


@dataclass
class ProviderHandle:
    id: str
    provider: LLMProvider
    models: dict[str, str]  # tier -> model id
    source: str  # env | integrations | override
    embedding: str | None = None
    extra_models: list[str] = field(default_factory=list)


@dataclass
class Credential:
    provider: str
    key: str
    base_url: str
    source: str
    meta: dict


_override: dict[str, ProviderHandle] | None = None
_cache: tuple[float, dict[str, ProviderHandle]] | None = None
_version = 0


def set_override(handles: dict[str, ProviderHandle] | None) -> None:
    """Usado em testes para injetar provedores falsos (nunca em produção)."""
    global _override
    _override = handles
    invalidate()


def invalidate() -> None:
    global _cache, _version
    _cache = None
    _version += 1


async def load_credentials(session: AsyncSession) -> dict[str, Credential]:
    s = get_settings()
    creds: dict[str, Credential] = {}
    for pid, attr in ENV_KEYS.items():
        val = getattr(s, attr, "")
        if val:
            creds[pid] = Credential(pid, val, PROVIDERS[pid].base_url, "env", {})
    if s.ollama_base_url:
        creds["ollama"] = Credential("ollama", "", s.ollama_base_url, "env", {})
    if s.searxng_url:
        creds["searxng"] = Credential("searxng", "", s.searxng_url, "env", {})
    rows = (await session.execute(select(ProviderCredential))).scalars().all()
    for r in rows:
        if not r.enabled:
            creds.pop(r.provider, None)
            continue
        key = decrypt_secret(r.encrypted_key) if r.encrypted_key else ""
        info = PROVIDERS.get(r.provider)
        if info is None:
            continue
        if info.key_required and not key:
            continue
        creds[r.provider] = Credential(r.provider, key, r.base_url or info.base_url, "integrations", r.meta or {})
    return creds


def build_llm_provider(cred: Credential) -> LLMProvider | None:
    info = PROVIDERS.get(cred.provider)
    if info is None or info.kind != "llm":
        return None
    if cred.provider == "anthropic":
        return AnthropicProvider(cred.key, base_url=cred.base_url)
    if cred.provider == "gemini":
        return GeminiProvider(cred.key, base_url=cred.base_url)
    if info.openai_compatible:
        return OpenAICompatProvider(cred.provider, cred.base_url or info.base_url, cred.key)
    return None


def _tier_models(cred: Credential) -> dict[str, str]:
    configured = (cred.meta or {}).get("models") or {}
    out: dict[str, str] = {}
    for tier in TIERS:
        m = configured.get(tier) or default_model(cred.provider, tier)
        if m:
            out[tier] = m
    if not out and configured.get("default"):
        out = {t: configured["default"] for t in TIERS}
    if cred.provider == "ollama" and not out:
        m = (cred.meta or {}).get("default_model") or "llama3.2"
        out = {t: m for t in TIERS}
    return out


async def get_llm_handles(session: AsyncSession) -> dict[str, ProviderHandle]:
    global _cache
    if _override is not None:
        return dict(_override)
    if _cache and time.monotonic() - _cache[0] < 30:
        return dict(_cache[1])
    creds = await load_credentials(session)
    handles: dict[str, ProviderHandle] = {}
    for pid, cred in creds.items():
        prov = build_llm_provider(cred)
        if prov is None:
            continue
        models = _tier_models(cred)
        if not models:
            continue
        emb = embedding_model(pid)
        handles[pid] = ProviderHandle(pid, prov, models, cred.source, emb.id if emb else None)
    _cache = (time.monotonic(), handles)
    return dict(handles)


async def get_credential(session: AsyncSession, provider: str) -> Credential | None:
    creds = await load_credentials(session)
    return creds.get(provider)
