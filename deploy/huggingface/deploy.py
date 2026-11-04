"""Implanta o ULTRON num Hugging Face Space (executado pelo GitHub Actions).

Variáveis: HF_TOKEN, ULTRON_DATABASE_URL, ULTRON_SETUP_TOKEN, ULTRON_GH_TOKEN, ULTRON_GITHUB_REPO,
ULTRON_GIT_BASE_BRANCH, ULTRON_SPACE_NAME (opcional, padrão "ultron").

Modos: ``python deploy.py deploy`` (cria/atualiza e reinicia) · ``python deploy.py ping`` (mantém acordado).
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
    from huggingface_hub import HfApi

    env = dict(os.environ)
    token = env.get("HF_TOKEN", "").strip()
    if not token:
        print("HF_TOKEN não configurado — implantação no Hugging Face ignorada.")
        return 0
    api = HfApi(token=token)
    mode = sys.argv[1] if len(sys.argv) > 1 else "deploy"
    if mode == "ping":
        ping(api, env)
    else:
        deploy(api, env)
    return 0


if __name__ == "__main__":
    sys.exit(main())
