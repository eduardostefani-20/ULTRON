"""Implanta o ULTRON num Hugging Face Space (executado pelo GitHub Actions).

Variáveis: HF_TOKEN, ULTRON_DATABASE_URL, ULTRON_SETUP_TOKEN, ULTRON_GH_TOKEN, ULTRON_GITHUB_REPO,
ULTRON_GIT_BASE_BRANCH, ULTRON_SPACE_NAME (opcional, padrão "ultron").

Modos: ``deploy`` (testa o banco, cria/atualiza e reinicia) · ``check-db`` (só testa o banco) ·
``ping`` (mantém acordado).
"""

from __future__ import annotations

import os
import re
import secrets
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent


def space_url(user: str, name: str) -> str:
    return f"https://{re.sub(r'[^a-z0-9]+', '-', f'{user}-{name}'.lower()).strip('-')}.hf.space"


def stage_files(dest: Path) -> list[str]:
    for f in ("Dockerfile", "bootstrap.sh", "README.md"):
        shutil.copy(HERE / f, dest / f)
    shutil.copy(ROOT / "backend" / "requirements.txt", dest / "requirements.txt")
    return sorted(p.name for p in dest.iterdir())


def validate_database_url(url: str) -> list[str]:
    """Erros comuns no endereço do Supabase, explicados em português. Lista vazia = formato OK."""
    from urllib.parse import urlsplit

    url = (url or "").strip()
    if not url:
        return ["o segredo ULTRON_DATABASE_URL está vazio"]
    if "[YOUR-PASSWORD]" in url or "YOUR-PASSWORD" in url:
        return ["troque [YOUR-PASSWORD] pela senha do banco (sem os colchetes)"]
    if not url.startswith(("postgresql://", "postgres://")):
        return ["o endereço deve começar com postgresql:// (copie a URI em Supabase → Connect)"]
    rest = url.split("://", 1)[1]
    if rest.count("@") != 1:
        return ["a senha parece ter símbolos como @ # / ?; gere uma senha só com letras e números "
                "(Supabase → Project Settings → Database → Reset database password)"]
    try:
        parts = urlsplit(url)
        host, port = parts.hostname or "", parts.port or 5432
    except ValueError:
        return ["endereço inválido; a senha pode ter símbolos — gere uma só com letras e números"]
    errors = []
    if host.startswith("db.") and host.endswith(".supabase.co"):
        errors.append("esse é o endereço de conexão direta (só IPv6); em Supabase → Connect escolha "
                      "'Session pooler' e copie esse endereço")
    if port == 6543:
        errors.append("esse é o 'Transaction pooler' (porta 6543); escolha 'Session pooler' (porta 5432)")
    if not parts.password:
        errors.append("o endereço não contém a senha")
    return errors


def check_database(url: str) -> str:
    """Conecta de verdade ao banco e devolve a versão do PostgreSQL (ou encerra com explicação)."""
    import asyncio

    errors = validate_database_url(url)
    if errors:
        raise SystemExit("Banco de dados: " + "; ".join(errors))
    dsn = re.sub(r"[?&]pgbouncer=[^&]*", "", url.strip())

    async def probe() -> str:
        import asyncpg

        conn = await asyncpg.connect(dsn, timeout=20)
        try:
            version = await conn.fetchval("select version()")
            await conn.execute("create table if not exists ultron_conexao_teste (id int); "
                               "drop table ultron_conexao_teste;")  # confirma permissão de escrita
            return version.split(" on ")[0]
        finally:
            await conn.close()

    try:
        version = asyncio.run(probe())
    except Exception as e:
        msg = str(e).lower()
        hint = ""
        if "password" in msg or "authentication" in msg:
            hint = " → senha incorreta no endereço (passo 2, item 5 do guia)"
        elif "tenant" in msg or "not found" in msg:
            hint = " → usuário do pooler incorreto: copie de novo a URI 'Session pooler' (postgres.SEU_PROJETO)"
        elif "timeout" in msg or "connect" in msg:
            hint = " → o banco não respondeu; confira se o projeto do Supabase está ativo (não pausado)"
        raise SystemExit(f"Banco de dados: falha ao conectar ({e.__class__.__name__}: {str(e)[:200]}){hint}")
    print(f"Banco de dados conectado ✅ ({version}) — leitura e escrita OK")
    return version


def deploy(api, env: dict) -> str:
    user = api.whoami()["name"]
    name = env.get("ULTRON_SPACE_NAME") or "ultron"
    repo_id = f"{user}/{name}"
    existed = api.repo_exists(repo_id, repo_type="space")
    api.create_repo(repo_id, repo_type="space", space_sdk="docker", private=False, exist_ok=True)
    if not existed:
        # gerada uma única vez: protege o cofre de chaves; nunca é reescrita
        api.add_space_secret(repo_id, "ULTRON_SECRET_KEY", secrets.token_urlsafe(48))
    required = {"DATABASE_URL": "ULTRON_DATABASE_URL", "ULTRON_SETUP_TOKEN": "ULTRON_SETUP_TOKEN",
                "GITHUB_TOKEN": "ULTRON_GH_TOKEN"}
    for key, src in required.items():
        value = (env.get(src) or "").strip()
        if not value:
            raise SystemExit(f"segredo {src} ausente no GitHub (Settings → Secrets and variables → Actions)")
        api.add_space_secret(repo_id, key, value)
    # tudo como segredo (variáveis de Space público são visíveis)
    api.add_space_secret(repo_id, "ULTRON_GITHUB_REPO", env["ULTRON_GITHUB_REPO"])
    api.add_space_secret(repo_id, "ULTRON_GIT_BASE_BRANCH", env["ULTRON_GIT_BASE_BRANCH"])
    url = space_url(user, name)
    api.add_space_secret(repo_id, "ULTRON_PUBLIC_URL", url)
    with tempfile.TemporaryDirectory() as td:
        files = stage_files(Path(td))
        api.upload_folder(folder_path=td, repo_id=repo_id, repo_type="space",
                          commit_message=f"ULTRON {env.get('GITHUB_SHA', '')[:7]}".strip())
    try:  # baixa a versão nova do código (o inicializador clona o branch a cada início)
        api.restart_space(repo_id)
    except Exception as e:  # um build recém-disparado já fará isso
        print(f"aviso: reinício não necessário/possível agora: {e}")
    print(f"Space: https://huggingface.co/spaces/{repo_id}")
    print(f"ULTRON: {url}   (arquivos publicados no Space: {', '.join(files)})")
    return url


def ping(api, env: dict) -> None:
    user = api.whoami()["name"]
    url = space_url(user, env.get("ULTRON_SPACE_NAME") or "ultron") + "/api/health"
    try:
        with urllib.request.urlopen(url, timeout=60) as r:  # noqa: S310 - URL https fixa do Space
            print(f"{url} → HTTP {r.status}")
    except Exception as e:
        print(f"{url} → {e} (o Space pode estar iniciando)")


def main() -> int:
    env = dict(os.environ)
    mode = sys.argv[1] if len(sys.argv) > 1 else "deploy"
    if mode == "check-db":
        check_database(env.get("ULTRON_DATABASE_URL", ""))
        return 0
    from huggingface_hub import HfApi

    token = env.get("HF_TOKEN", "").strip()
    if not token:
        print("HF_TOKEN não configurado — implantação no Hugging Face ignorada.")
        return 0
    api = HfApi(token=token)
    if mode == "ping":
        ping(api, env)
    else:
        check_database(env.get("ULTRON_DATABASE_URL", ""))  # não implanta com o banco quebrado
        deploy(api, env)
    return 0


if __name__ == "__main__":
    sys.exit(main())
