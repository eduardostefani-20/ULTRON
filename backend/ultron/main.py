"""Aplicação FastAPI do ULTRON (API + interface estática + processos em segundo plano)."""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ultron import __version__, telemetry
from ultron.config import BACKEND_DIR, get_settings
from ultron.db import dispose_engine, init_engine, session_scope

log = logging.getLogger("ultron")


def run_migrations() -> None:
    from alembic.config import Config

    from alembic import command

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", get_settings().resolved_database_url)
    command.upgrade(cfg, "head")


async def bootstrap() -> None:
    import ultron.tools.registry  # noqa: F401 - registra ferramentas
    from ultron.agents.factory import seed_builtin_agents
    from ultron.governance.integrity import check_and_record

    await asyncio.to_thread(run_migrations)
    async with session_scope() as s:
        await seed_builtin_agents(s)
        info = await check_and_record(s)
        if info["missing"]:
            log.error("arquivos de governança ausentes: %s", info["missing"])


def harden_data_dir() -> None:
    """Arquivos do servidor privados por padrão; o diretório de dados é apenas atravessável para que o
    sandbox (usuário 'nobody') alcance as worktrees sem conseguir ler banco, chaves ou memórias."""
    import os

    os.umask(0o077)
    d = get_settings().data_dir
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o711)  # noqa: S103 - somente travessia (x), sem leitura/listagem por outros
        for f in d.iterdir():
            if f.is_file() and (f.suffix in (".db", ".key") or ".db-" in f.name):
                os.chmod(f, 0o600)
    except OSError:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    harden_data_dir()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    s.resolved_secret_key()  # falha cedo em produção sem chave
    init_engine()
    await bootstrap()
    telemetry.start_flusher()
    background = s.enable_background and not s.is_test
    if background:
        from ultron.evolution.scheduler import scheduler
        from ultron.missions.engine import worker

        app.state.worker_task = asyncio.create_task(worker.run_forever())
        scheduler.start()
        log.info("ULTRON %s iniciado com scheduler e worker de missões", __version__)
    yield
    if background:
        from ultron.evolution.scheduler import scheduler
        from ultron.missions.engine import worker

        await worker.stop()
        await scheduler.stop()
    await telemetry.stop_flusher()
    await dispose_engine()


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}
CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data: blob:; connect-src 'self' https:; font-src 'self' data:; frame-ancestors 'none'; "
       "base-uri 'self'; form-action 'self'")


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="ULTRON", version=__version__, lifespan=lifespan,
                  docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)

    origins = s.cors_origin_list
    if origins:
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=False,
                           allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                           allow_headers=["Authorization", "Content-Type"])

    @app.middleware("http")
    async def observe(request: Request, call_next):
        from ultron.evolution.observability import api_stats

        t0 = time.monotonic()
        try:
            response = await call_next(request)
        except Exception as e:
            telemetry.record_error("api", f"{e.__class__.__name__}: {e}", request.url.path)
            api_stats.add(500, (time.monotonic() - t0) * 1000)
            log.exception("erro não tratado em %s", request.url.path)
            return JSONResponse({"detail": "erro interno — registrado para diagnóstico"}, status_code=500)
        if request.url.path.startswith("/api/"):
            api_stats.add(response.status_code, (time.monotonic() - t0) * 1000)
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        if not request.url.path.startswith("/api/"):
            response.headers.setdefault("Content-Security-Policy", CSP)
        return response

    from ultron.api import agents, auth, chat, evolution, integrations, knowledge, settings

    for r in (auth.router, chat.router, agents.router, knowledge.router, evolution.router, integrations.router,
              settings.router):
        app.include_router(r)

    frontend = Path(s.frontend_dir)
    if frontend.exists() and (frontend / "index.html").exists():
        app.mount("/_next", StaticFiles(directory=frontend / "_next"), name="next-assets")

        @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
        async def spa(path: str):
            if path.startswith("api/"):
                return JSONResponse({"detail": "não encontrado"}, status_code=404)
            target = (frontend / path).resolve()
            if frontend.resolve() not in target.parents and target != frontend.resolve():
                return JSONResponse({"detail": "não encontrado"}, status_code=404)
            for cand in (target, target / "index.html", Path(str(target) + ".html")):
                if cand.is_file():
                    return FileResponse(cand)
            return FileResponse(frontend / "index.html")
    else:
        @app.get("/", include_in_schema=False)
        async def root():
            return {"service": "ULTRON", "version": __version__, "docs": "/api/docs",
                    "frontend": "interface não compilada neste servidor (veja docs/INSTALACAO_CELULAR.md)"}

    return app


app = create_app()
