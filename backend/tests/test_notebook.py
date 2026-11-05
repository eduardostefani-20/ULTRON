"""Instalação no notebook: endereço do túnel para o celular e scripts de iniciar/atualizar."""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import tarfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"


class _FakeTunnelClient:
    hostname = "palavras-de-teste.trycloudflare.com"
    calls: list[str] = []

    def __init__(self, **kwargs):
        assert kwargs.get("trust_env") is False  # chamada interna nunca passa por proxy

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url):
        _FakeTunnelClient.calls.append(url)
        hostname = self.hostname

        class R:
            def json(self):
                return {"hostname": hostname}
        return R()


async def test_access_info_shows_only_valid_tunnel_address(client, headers, monkeypatch):
    from ultron.api import settings as api_settings
    from ultron.config import reset_settings_cache

    assert (await client.get("/api/system/access")).status_code == 401
    r = await client.get("/api/system/access", headers=headers)
    assert r.json() == {"tunnel_url": None, "tunnel_configured": False}

    monkeypatch.setenv("ULTRON_TUNNEL_METRICS_URL", "http://tunnel:2000/quicktunnel")
    reset_settings_cache()
    monkeypatch.setattr(api_settings.httpx, "AsyncClient", _FakeTunnelClient)
    r = await client.get("/api/system/access", headers=headers)
    assert r.json()["tunnel_url"] == "https://palavras-de-teste.trycloudflare.com"
    assert _FakeTunnelClient.calls[-1] == "http://tunnel:2000/quicktunnel"

    for bad in ("evil.example.com", "x.trycloudflare.com.evil.com", "a b.trycloudflare.com", "javascript:alert(1)"):
        monkeypatch.setattr(_FakeTunnelClient, "hostname", bad)
        r = await client.get("/api/system/access", headers=headers)
        assert r.json()["tunnel_url"] is None, bad


def test_notebook_files_are_consistent():
    compose = (ROOT / "docker-compose.yml").read_text()
    assert "name: ultron" in compose  # o volume de dados não depende do nome da pasta
    assert "seccomp=unconfined" in compose  # sandbox consegue isolar a rede (unshare)
    assert "ULTRON_TUNNEL_METRICS_URL: http://tunnel:2000/quicktunnel" in compose
    assert "--metrics 0.0.0.0:2000" in compose
    for n in ("INICIAR", "ATUALIZAR", "PARAR"):
        bat = (ROOT / f"{n}-ULTRON.bat").read_bytes()
        assert b"\r\n" in bat and b"\n" not in bat.replace(b"\r\n", b""), "o .bat precisa de CRLF"
        assert f"scripts\\windows\\{n.lower()}.ps1".encode() in bat
    for ps1 in (SCRIPTS / "windows").glob("*.ps1"):
        assert ps1.read_bytes().startswith(b"\xef\xbb\xbf"), f"{ps1.name} sem BOM (acentos no PowerShell 5.1)"
    attrs = (ROOT / ".gitattributes").read_text()
    assert "*.bat -text" in attrs and "*.ps1 -text" in attrs


@pytest.mark.parametrize("script", ["comum.sh", "iniciar.sh", "parar.sh", "atualizar.sh"])
def test_shell_scripts_have_valid_syntax(script):
    r = subprocess.run(["bash", "-n", str(SCRIPTS / script)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


# ---------------------------------------------------------------- atualizador (Mac/Linux) de ponta a ponta

SHA1 = "a" * 40
SHA2 = "b" * 40


def _tarball(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, content in files.items():
            data = content.encode()
            info = tarfile.TarInfo(f"dono-ULTRON-1234567/{name}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


@pytest.fixture
def fake_github():
    state = {"sha": SHA1, "requests": []}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            state["requests"].append(self.path)
            if self.path == "/api/health":
                return self._send(b'{"status":"ok"}')
            if self.headers.get("Authorization") != "Bearer tok-123":
                return self._send(b"{}", 401)
            if self.path == "/repos/dono/ULTRON/commits/main":
                assert self.headers.get("Accept") == "application/vnd.github.sha"
                return self._send(state["sha"].encode())
            if self.path == f"/repos/dono/ULTRON/tarball/{state['sha']}":
                return self._send(_tarball({"docker-compose.yml": "name: ultron\n", "backend/novo.py": "x = 1\n",
                                            ".github/workflows/ci.yml": "on: push\n"}))
            return self._send(b"{}", 404)

        def _send(self, body: bytes, code: int = 200):
            self.send_response(code)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    state["url"] = f"http://127.0.0.1:{srv.server_address[1]}"
    yield state
    srv.shutdown()


@pytest.mark.skipif(not shutil.which("bash") or not shutil.which("curl") or not shutil.which("tar"),
                    reason="bash/curl/tar indisponíveis")
def test_update_script_mirrors_code_keeps_env_and_skips_when_current(tmp_path, fake_github):
    proj = tmp_path / "ULTRON"
    shutil.copytree(SCRIPTS, proj / "scripts")
    (proj / "backend").mkdir()
    (proj / "backend" / "antigo.py").write_text("removido no GitHub\n")
    env_text = (
        "ULTRON_GITHUB_REPO=dono/ULTRON\nULTRON_GIT_BASE_BRANCH=main\nULTRON_SECRET_KEY=nao-mudar\nCOMPOSE_PROFILES=celular\n")
    (proj / ".env").write_text(env_text)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    calls = tmp_path / "docker-calls.log"
    (bindir / "docker").write_text(f"""#!/usr/bin/env bash
echo "$*" >> "{calls}"
case "$*" in
  "info") exit 0 ;;
  *"github-token"*) echo "tok-123" ;;
  *"logs tunnel"*) echo "INF |  https://nova-url-teste.trycloudflare.com  |" ;;
esac
exit 0
""")
    (bindir / "docker").chmod(0o755)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "ULTRON_GITHUB_API": fake_github["url"],
           "ULTRON_URL_LOCAL": fake_github["url"]}
    env.pop("HTTPS_PROXY", None)
    env.pop("HTTP_PROXY", None)
    env["NO_PROXY"] = "127.0.0.1,localhost"

    def run():
        return subprocess.run(["bash", str(proj / "scripts" / "atualizar.sh")], env=env, capture_output=True,
                              text=True, timeout=120)

    r = run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert (proj / "backend" / "novo.py").exists()
    assert not (proj / "backend" / "antigo.py").exists()  # pasta de código espelhada
    assert (proj / ".github" / "workflows" / "ci.yml").exists()
    assert (proj / "scripts" / "atualizar.sh").exists()  # pastas ausentes no pacote são mantidas
    assert (proj / ".env").read_text() == env_text  # configuração e chave preservadas
    assert (proj / ".versao").read_text().strip() == SHA1
    assert "compose up -d --build" in calls.read_text()
    assert "tok-123" not in "".join(p.read_text(errors="ignore") for p in proj.rglob("*") if p.is_file())

    calls.write_text("")
    r = run()
    assert r.returncode == 0 and "versão mais recente" in r.stdout, r.stdout + r.stderr
    assert "compose up" not in calls.read_text()

    fake_github["sha"] = SHA2
    r = run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert (proj / ".versao").read_text().strip() == SHA2
    assert "https://nova-url-teste.trycloudflare.com" in r.stdout
