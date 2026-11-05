"""Configuração central do ULTRON (variáveis de ambiente).

Toda configuração sensível vive apenas no backend. O frontend nunca recebe chaves.
"""

from __future__ import annotations

import os
import secrets
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent


def normalize_database_url(url: str) -> str:
    """Converte URLs comuns de provedores (Render, Supabase, Heroku) para drivers assíncronos.

    - ``postgres://`` e ``postgresql://`` → ``postgresql+asyncpg://``
    - ``sslmode=require`` → ``ssl=require`` (asyncpg não aceita ``sslmode``)
    - ``sqlite://`` → ``sqlite+aiosqlite://``
    """
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://") :]
    if url.startswith("sqlite://") and not url.startswith("sqlite+aiosqlite://"):
        url = "sqlite+aiosqlite://" + url[len("sqlite://") :]
    if url.startswith("postgresql+asyncpg://"):
        parts = urlsplit(url)
        query = dict(parse_qsl(parts.query))
        if "sslmode" in query:
            mode = query.pop("sslmode")
            if mode in ("require", "verify-ca", "verify-full", "prefer"):
                query["ssl"] = "require" if mode == "prefer" else mode
        # parâmetros do pgbouncer/supabase que o asyncpg não entende
        query.pop("pgbouncer", None)
        url = urlunsplit(parts._replace(query=urlencode(query)))
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: str = Field(default="development", alias="ULTRON_ENV")
    data_dir: Path = Field(default=BACKEND_DIR / "data", alias="ULTRON_DATA_DIR")
    database_url: str = Field(default="", alias="DATABASE_URL")
    secret_key: str = Field(default="", alias="ULTRON_SECRET_KEY")
    setup_token: str = Field(default="", alias="ULTRON_SETUP_TOKEN")

    cors_origins: str = Field(default="", alias="ULTRON_CORS_ORIGINS")
    frontend_dir: Path = Field(default=REPO_ROOT / "frontend" / "out", alias="ULTRON_FRONTEND_DIR")
    public_url: str = Field(default="", alias="ULTRON_PUBLIC_URL")

    access_token_minutes: int = Field(default=60, alias="ULTRON_ACCESS_TOKEN_MINUTES")
    refresh_token_days: int = Field(default=30, alias="ULTRON_REFRESH_TOKEN_DAYS")

    # Repositório do próprio ULTRON (para autoevolução)
    repo_url: str = Field(default="", alias="ULTRON_REPO_URL")
    repo_source_dir: Path = Field(default=REPO_ROOT, alias="ULTRON_REPO_SOURCE_DIR")
    workspace_dir: Path | None = Field(default=None, alias="ULTRON_WORKSPACE_DIR")
    git_base_branch: str = Field(default="", alias="ULTRON_GIT_BASE_BRANCH")
    github_token: str = Field(default="", alias="GITHUB_TOKEN")
    github_repo: str = Field(default="", alias="ULTRON_GITHUB_REPO")  # ex.: usuario/ULTRON

    # Orçamento
    monthly_budget_brl: float = Field(default=100.0, alias="ULTRON_MONTHLY_BUDGET_BRL")
    usd_brl_rate: float = Field(default=5.5, alias="ULTRON_USD_BRL_RATE")

    # Execução em segundo plano
    enable_background: bool = Field(default=True, alias="ULTRON_ENABLE_BACKGROUND")
    scheduler_tick_seconds: int = Field(default=30, alias="ULTRON_SCHEDULER_TICK_SECONDS")
    # internal: ciclos de autoevolução rodam neste servidor · github: rodam no GitHub Actions
    # (ideal para hospedagens gratuitas fracas; o servidor só atende interface, chat e missões)
    evolution_runner: str = Field(default="internal", alias="ULTRON_EVOLUTION_RUNNER")

    # Sandbox
    sandbox_backend: str = Field(default="auto", alias="ULTRON_SANDBOX_BACKEND")  # auto|process|docker
    sandbox_memory_mb: int = Field(default=1024, alias="ULTRON_SANDBOX_MEMORY_MB")
    sandbox_timeout_seconds: int = Field(default=600, alias="ULTRON_SANDBOX_TIMEOUT_SECONDS")
    sandbox_docker_image: str = Field(default="", alias="ULTRON_SANDBOX_DOCKER_IMAGE")

    # Chaves de provedores podem vir do ambiente OU da tela Integrações (armazenadas cifradas)
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    xai_api_key: str = Field(default="", alias="XAI_API_KEY")
    deepseek_api_key: str = Field(default="", alias="DEEPSEEK_API_KEY")
    groq_api_key: str = Field(default="", alias="GROQ_API_KEY")
    openrouter_api_key: str = Field(default="", alias="OPENROUTER_API_KEY")
    mistral_api_key: str = Field(default="", alias="MISTRAL_API_KEY")
    ollama_base_url: str = Field(default="", alias="OLLAMA_BASE_URL")
    tavily_api_key: str = Field(default="", alias="TAVILY_API_KEY")
    brave_api_key: str = Field(default="", alias="BRAVE_API_KEY")
    serper_api_key: str = Field(default="", alias="SERPER_API_KEY")
    searxng_url: str = Field(default="", alias="SEARXNG_URL")

    @property
    def is_production(self) -> bool:
        return self.env.lower() in ("production", "prod")

    @property
    def is_test(self) -> bool:
        return self.env.lower() == "test"

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return normalize_database_url(self.database_url)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return f"sqlite+aiosqlite:///{(self.data_dir / 'ultron.db').as_posix()}"

    @property
    def resolved_workspace_dir(self) -> Path:
        return self.workspace_dir or (self.data_dir / "workspace")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def resolved_secret_key(self) -> str:
        """Chave mestra para JWT e cofre de segredos.

        Em produção é obrigatória (ULTRON_SECRET_KEY). Em desenvolvimento é gerada uma vez
        e persistida em ``data/secret.key`` com permissão 600.
        """
        if self.secret_key:
            return self.secret_key
        if self.is_production:
            raise RuntimeError(
                "ULTRON_SECRET_KEY é obrigatória em produção. Configure-a no painel da hospedagem."
            )
        self.data_dir.mkdir(parents=True, exist_ok=True)
        key_file = self.data_dir / "secret.key"
        if key_file.exists():
            return key_file.read_text().strip()
        key = secrets.token_urlsafe(48)
        key_file.write_text(key)
        os.chmod(key_file, 0o600)
        return key


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
