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
