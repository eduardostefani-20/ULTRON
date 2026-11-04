"""Diagnóstico de instalação: ``python -m ultron.doctor``

Verifica configuração, banco, git, workspace, sandbox e provedores, e explica o que falta.
Pode ser executado no "Shell" do painel da hospedagem (Render, Railway) ou num VPS.
"""

from __future__ import annotations

import asyncio
import shutil
import sys

from ultron.config import get_settings

OK, WARN, FAIL = "✅", "⚠️ ", "❌"


async def run() -> int:
    s = get_settings()
    problems = 0

    def line(icon: str, text: str, hint: str = "") -> None:
        nonlocal problems
        if icon == FAIL:
            problems += 1
        print(f"{icon} {text}" + (f"\n     → {hint}" if hint else ""))

    print(f"ULTRON doctor — ambiente: {s.env}\n")
    try:
        s.resolved_secret_key()
        line(OK if s.secret_key else WARN, "Chave mestra " + ("definida no ambiente" if s.secret_key else
             "gerada localmente (data/secret.key)"), "" if s.secret_key else "Em produção defina ULTRON_SECRET_KEY.")
    except RuntimeError as e:
        line(FAIL, str(e))
    if s.is_production and not s.setup_token:
        line(WARN, "ULTRON_SETUP_TOKEN não definido", "Necessário para criar a conta do proprietário em produção.")
    url = s.resolved_database_url
    try:
        from sqlalchemy import text

        from ultron.db import init_engine, session_scope

        init_engine(url)
        async with session_scope() as sess:
            await sess.execute(text("SELECT 1"))
        line(OK, f"Banco de dados acessível ({'PostgreSQL' if 'postgresql' in url else 'SQLite'})")
    except Exception as e:
        line(FAIL, f"Banco de dados inacessível: {e.__class__.__name__}: {str(e)[:200]}", "Confira DATABASE_URL.")
    line(OK if shutil.which("git") else FAIL, "git instalado" if shutil.which("git") else "git ausente",
         "" if shutil.which("git") else "A autoevolução precisa do git (a imagem Docker já inclui).")
    from ultron.evolution import sandbox

    caps = sandbox.capabilities()
    line(OK if caps["unshare_net"] or caps["docker"] else WARN,
         f"Sandbox: isolamento '{sandbox.isolation_level()}' · rede {'isolada' if caps['unshare_net'] else 'NÃO isolada'}"
         f" · usuário {'nobody' if sandbox.drops_privileges() else 'do servidor'}",
         "" if caps["unshare_net"] else "Sem isolamento de rede a publicação automática fica bloqueada (aprovação humana "
                                        "continua funcionando). Valide também pelo CI do GitHub.")
    if s.github_repo or s.repo_url:
        line(OK, f"Repositório configurado: {s.github_repo or s.repo_url}")
    else:
        line(WARN, "ULTRON_GITHUB_REPO não definido", "Defina usuario/ULTRON para a autoevolução clonar e publicar.")
    try:
        from ultron.db import session_scope
        from ultron.providers import registry

        async with session_scope() as sess:
            handles = await registry.get_llm_handles(sess)
        if handles:
            line(OK, f"Provedores de IA: {', '.join(sorted(handles))}")
        else:
            line(WARN, "Nenhum provedor de IA configurado", "Adicione uma chave em Integrações no app.")
    except Exception as e:
        msg = "banco ainda não migrado (o servidor aplica as migrações ao iniciar)" if "no such table" in str(e) \
            or "does not exist" in str(e) else f"{e.__class__.__name__}: {str(e)[:150]}"
        line(WARN, f"Provedores não verificados: {msg}")
    frontend = s.frontend_dir / "index.html"
    line(OK if frontend.exists() else WARN, "Interface compilada encontrada" if frontend.exists() else
         f"Interface não encontrada em {s.frontend_dir}", "" if frontend.exists() else "Rode 'npm run build' em frontend/.")
    print(f"\n{'Tudo certo.' if not problems else f'{problems} problema(s) bloqueante(s).'}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
