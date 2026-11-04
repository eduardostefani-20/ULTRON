"""Fixtures de teste.

O FakeProvider existe SOMENTE nos testes (nunca é registrado em produção) e permite validar
toda a orquestração sem chamar APIs pagas.
"""

from __future__ import annotations

import os
import subprocess
import textwrap
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

os.environ.setdefault("ULTRON_ENV", "test")
os.environ["ULTRON_ENABLE_BACKGROUND"] = "false"

from ultron.providers.base import ChatRequest, ChatResult  # noqa: E402


class FakeProvider:
    def __init__(self, name: str = "fake", responder: Callable[[ChatRequest], str] | None = None,
                 fail: Exception | None = None):
        self.name = name
        self.responder = responder or (lambda req: '{"thought": "ok", "final": "resposta de teste"}')
        self.fail = fail
        self.calls: list[ChatRequest] = []

    async def chat(self, req: ChatRequest) -> ChatResult:
        self.calls.append(req)
        if self.fail:
            raise self.fail
        text = self.responder(req)
        return ChatResult(text=text, model=req.model, provider=self.name, tokens_in=100, tokens_out=50)

    async def embed(self, texts, model):
        return [[0.0] * 8 for _ in texts]

    async def list_models(self):
        return [f"{self.name}-fast", f"{self.name}-balanced", f"{self.name}-premium"]


def install_fake(*providers: FakeProvider) -> None:
    from ultron.providers import registry
    from ultron.providers.registry import ProviderHandle

    registry.set_override({p.name: ProviderHandle(p.name, p, {"fast": f"{p.name}-fast", "balanced": f"{p.name}-balanced",
                                                              "premium": f"{p.name}-premium"}, "override")
                           for p in providers})


def last_user(req: ChatRequest) -> str:
    return [m.content for m in req.messages if m.role == "user"][-1]


def system_of(req: ChatRequest) -> str:
    return "\n".join(m.content for m in req.messages if m.role == "system")


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True,
                   capture_output=True)


@pytest.fixture
def mini_repo(tmp_path) -> Path:
    """Repositório git mínimo com a estrutura do ULTRON e uma suíte de testes rápida."""
    root = tmp_path / "src_repo"
    (root / "backend" / "tests" / "security").mkdir(parents=True)
    (root / "backend" / "app").mkdir(parents=True)
    (root / "docs").mkdir()
    (root / "backend" / "app" / "__init__.py").write_text("")
    (root / "backend" / "app" / "calc.py").write_text(textwrap.dedent('''
        """Calculadora de exemplo."""


        def soma(a, b):
            return a + b
    '''))
    (root / "backend" / "tests" / "test_calc.py").write_text(textwrap.dedent('''
        from app.calc import soma


        def test_soma():
            assert soma(2, 3) == 5
    '''))
    (root / "backend" / "tests" / "security" / "test_basic.py").write_text("def test_guard():\n    assert True\n")
    (root / "README.md").write_text("# mini\n")
    _git("init", "-q", "-b", "main", cwd=root)
    _git("add", "-A", cwd=root)
    _git("commit", "-q", "-m", "inicial", cwd=root)
    return root


async def _reset_postgres(url: str) -> None:
    import asyncpg

    from ultron.config import normalize_database_url

    dsn = normalize_database_url(url).replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    finally:
        await conn.close()


def is_postgres() -> bool:
    return bool(os.environ.get("ULTRON_TEST_DATABASE_URL"))


@pytest.fixture
async def app_env(tmp_path, monkeypatch, mini_repo):
    """Aplicação completa com banco novo (migrações reais) e workspace apontando para o mini repo."""
    data = tmp_path / "data"
    monkeypatch.setenv("ULTRON_DATA_DIR", str(data))
    monkeypatch.setenv("ULTRON_REPO_SOURCE_DIR", str(mini_repo))
    monkeypatch.setenv("ULTRON_WORKSPACE_DIR", str(tmp_path / "ws"))
    for k in ("DATABASE_URL", "GITHUB_TOKEN", "ULTRON_REPO_URL", "ULTRON_GITHUB_REPO", "ULTRON_SETUP_TOKEN",
              "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    pg_url = os.environ.get("ULTRON_TEST_DATABASE_URL")
    if pg_url:  # mesma suíte contra PostgreSQL (CI e validação para Supabase)
        await _reset_postgres(pg_url)
        monkeypatch.setenv("DATABASE_URL", pg_url)
    from ultron import telemetry
    from ultron.api.deps import auth_limiter
    from ultron.config import reset_settings_cache
    from ultron.evolution.workspace import reset_workspace
    from ultron.llm import budget
    from ultron.main import create_app
    from ultron.providers import registry
    from ultron.providers.router import health

    reset_settings_cache()
    reset_workspace()
    registry.set_override(None)
    health.reset()
    telemetry.reset()
    budget.clear_cache()
    auth_limiter.reset()
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://ultron.test", timeout=120) as client:
            yield {"app": app, "client": client, "data": data, "repo": mini_repo}
    registry.set_override(None)
    reset_workspace()
    reset_settings_cache()


@pytest.fixture
async def client(app_env) -> httpx.AsyncClient:
    return app_env["client"]


@pytest.fixture
async def auth(client) -> dict:
    r = await client.post("/api/auth/setup", json={"email": "dono@ultron.dev", "password": "Senha-Forte-2026",
                                                   "name": "Dono"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}", "_refresh": r.json()["refresh_token"]}


@pytest.fixture
def headers(auth) -> dict:
    return {"Authorization": auth["Authorization"]}
