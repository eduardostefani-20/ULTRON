"""Scripts de implantação na Oracle Cloud: sintaxe e comportamento do atualizador."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ORACLE = ROOT / "deploy" / "oracle"
pytestmark = pytest.mark.skipif(not shutil.which("bash") or not shutil.which("git") or not shutil.which("flock"),
                                reason="bash/git/flock indisponíveis")


def _git(*args, cwd):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True,
                   capture_output=True)


@pytest.mark.parametrize("script", ["cloud-init.sh", "update.sh"])
def test_scripts_have_valid_syntax(script):
    r = subprocess.run(["bash", "-n", str(ORACLE / script)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_cloud_init_refuses_unfilled_token():
    text = (ORACLE / "cloud-init.sh").read_text()
    assert 'COLE_AQUI*|"") echo "ERRO' in text


@pytest.fixture
def deploy(tmp_path):
    """Simula a VM: repositório 'origin', cópia de implantação e comandos docker/iptables falsos."""
    origin = tmp_path / "origin"
    origin.mkdir()
    _git("init", "-q", "-b", "main", cwd=origin)
    (origin / "deploy" / "oracle").mkdir(parents=True)
    shutil.copy(ORACLE / "update.sh", origin / "deploy" / "oracle" / "update.sh")
    (origin / ".gitignore").write_text(".env\n")
    (origin / "app.txt").write_text("v1\n")
    _git("add", "-A", cwd=origin)
    _git("commit", "-q", "-m", "v1", cwd=origin)
    vm = tmp_path / "vm"
    _git("clone", "-q", str(origin), str(vm), cwd=tmp_path)
    (vm / "deploy" / "oracle" / ".env").write_text("ULTRON_GIT_BASE_BRANCH=main\nGITHUB_TOKEN=ghp_tokenfalso123\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls.log"
    state = tmp_path / "running"
    (bin_dir / "docker").write_text(
        f'#!/bin/bash\necho "docker $*" >> {calls}\n'
        f'if [[ "$*" == *"ps --status running"* ]]; then [ -f {state} ] && echo ultron; exit 0; fi\n'
        f'if [[ "$*" == *" up -d"* ]]; then touch {state}; fi\nexit 0\n')
    (bin_dir / "iptables").write_text(f'#!/bin/bash\necho "iptables $*" >> {calls}\nexit 0\n')
    for f in bin_dir.iterdir():
        f.chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "ULTRON_DIR": str(vm),
           "ULTRON_LOCK": str(tmp_path / "lock")}
    env.pop("ULTRON_FORCE", None)
    return {"origin": origin, "vm": vm, "calls": calls, "env": env}


def _run(d, **extra):
    return subprocess.run(["bash", str(d["vm"] / "deploy" / "oracle" / "update.sh")], env={**d["env"], **extra},
                          capture_output=True, text=True, timeout=60)


def test_update_deploys_only_when_needed_and_never_stores_token(deploy):
    r = _run(deploy)  # nada rodando ainda → implanta
    assert r.returncode == 0, r.stderr
    log = deploy["calls"].read_text()
    assert "up -d --build" in log
    assert "DOCKER-USER -d 169.254.169.254" in log  # metadados bloqueados para os containers
    deploy["calls"].write_text("")
    r = _run(deploy)  # já atualizado e rodando → não faz nada
    assert r.returncode == 0 and "up -d" not in deploy["calls"].read_text()
    (deploy["origin"] / "app.txt").write_text("v2\n")
    _git("commit", "-qam", "v2", cwd=deploy["origin"])
    r = _run(deploy)  # código novo (ex.: melhoria publicada) → reconstrói
    assert r.returncode == 0 and "up -d --build" in deploy["calls"].read_text()
    assert (deploy["vm"] / "app.txt").read_text() == "v2\n"
    assert (deploy["vm"] / "deploy" / "oracle" / ".env").exists()  # configuração preservada
    git_config = (deploy["vm"] / ".git" / "config").read_text()
    assert "ghp_tokenfalso123" not in git_config and "extraheader" not in git_config


def _load_hf_deploy():
    import importlib.util

    spec = importlib.util.spec_from_file_location("hf_deploy", ROOT / "deploy" / "huggingface" / "deploy.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeHf:
    def __init__(self, exists=False):
        self.exists = exists
        self.secrets: dict[str, str] = {}
        self.uploaded: list[str] = []
        self.created = None
        self.restarted = False

    def whoami(self):
        return {"name": "Eduardo_Stefani"}

    def repo_exists(self, repo_id, repo_type=None):
        return self.exists

    def create_repo(self, repo_id, **kw):
        self.created = (repo_id, kw)

    def add_space_secret(self, repo_id, key, value):
        self.secrets[key] = value

    def upload_folder(self, *, folder_path, repo_id, repo_type, commit_message):
        self.uploaded = sorted(p.name for p in Path(folder_path).iterdir())

    def restart_space(self, repo_id):
        self.restarted = True


HF_ENV = {"ULTRON_DATABASE_URL": "postgresql://u:p@host:5432/postgres", "ULTRON_SETUP_TOKEN": "frase",
          "ULTRON_GH_TOKEN": "github_pat_x", "ULTRON_GITHUB_REPO": "eduardostefani-20/ULTRON",
          "ULTRON_GIT_BASE_BRANCH": "main"}


def test_hf_deploy_creates_public_bootstrap_space_without_code():
    mod = _load_hf_deploy()
    api = FakeHf(exists=False)
    url = mod.deploy(api, HF_ENV)
    assert url == "https://eduardo-stefani-ultron.hf.space"
    assert api.created[1]["space_sdk"] == "docker" and api.created[1]["private"] is False
    assert api.uploaded == ["Dockerfile", "README.md", "bootstrap.sh", "requirements.txt"]  # só o inicializador
    assert "ULTRON_SECRET_KEY" in api.secrets and api.secrets["GITHUB_TOKEN"] == "github_pat_x"
    assert api.secrets["DATABASE_URL"].startswith("postgresql://") and api.restarted


def test_hf_deploy_never_rotates_secret_key_and_requires_secrets():
    mod = _load_hf_deploy()
    api = FakeHf(exists=True)
    mod.deploy(api, HF_ENV)
    assert "ULTRON_SECRET_KEY" not in api.secrets  # chave mestra não é trocada (dados cifrados continuam legíveis)
    with pytest.raises(SystemExit, match="ULTRON_DATABASE_URL"):
        mod.deploy(FakeHf(), {**HF_ENV, "ULTRON_DATABASE_URL": ""})


def test_hf_bootstrap_has_valid_syntax():
    r = subprocess.run(["bash", "-n", str(ROOT / "deploy" / "huggingface" / "bootstrap.sh")], capture_output=True)
    assert r.returncode == 0
