"""Ambiente experimental isolado (CÓDIGO DE GOVERNANÇA).

Camadas de isolamento (as disponíveis são detectadas e registradas em cada execução):
- processo separado em nova sessão, morto por grupo ao fim do tempo;
- limites de memória, CPU, tamanho de arquivo e descritores (setrlimit);
- ambiente LIMPO: nenhuma chave, token, senha ou DATABASE_URL é repassada;
- HOME, TMPDIR e diretório de dados temporários, destruídos ao final;
- rede: namespace de rede vazio via ``unshare -rn`` quando o kernel permite, ou contêiner
  Docker com ``--network none``; caso contrário a execução é marcada como SEM isolamento de rede
  (e a publicação automática fica bloqueada).
"""

from __future__ import annotations

import asyncio
import os
import resource
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET  # noqa: S405 - XML gerado localmente pelo pytest
from functools import lru_cache
from pathlib import Path

from ultron.config import get_settings
from ultron.db import session_scope
from ultron.models import SandboxRun
from ultron.utils import tail

OUTPUT_LIMIT = 20000
SAFE_ENV_KEYS = ("LANG", "LC_ALL", "TZ")
SANDBOX_UID = 65534  # "nobody": sem acesso aos arquivos do servidor (banco SQLite, chaves, workspace)


def _uid_mapped(uid: int) -> bool:
    """Dentro de um namespace de usuário (ex.: o próprio sandbox) só alguns UIDs existem."""
    try:
        for line in Path("/proc/self/uid_map").read_text().splitlines():
            inside, _outside, count = (int(x) for x in line.split())
            if inside <= uid < inside + count:
                return True
        return False
    except (OSError, ValueError):
        return True


def drops_privileges() -> bool:
    """Quando o servidor roda como root (contêineres), o código experimental roda como 'nobody'."""
    return (os.geteuid() == 0 and os.environ.get("ULTRON_SANDBOX_DROP_PRIVILEGES", "1") != "0"
            and os.environ.get("ULTRON_IN_SANDBOX") != "1" and _uid_mapped(SANDBOX_UID))


def _chown_tree(path: Path) -> None:
    for dirpath, dirnames, filenames in os.walk(path):
        for name in [*dirnames, *filenames]:
            try:
                os.lchown(os.path.join(dirpath, name), SANDBOX_UID, SANDBOX_UID)
            except OSError:
                pass
    try:
        os.lchown(path, SANDBOX_UID, SANDBOX_UID)
    except OSError:
        pass


def _ensure_traversable(path: Path) -> None:
    """Permite ao usuário do sandbox apenas ATRAVESSAR os diretórios-pai (sem listar nem ler arquivos)."""
    for parent in Path(path).resolve().parents:
        try:
            st = parent.stat()
            if st.st_uid == os.geteuid() and not st.st_mode & 0o001:
                os.chmod(parent, (st.st_mode & 0o7777) | 0o001)
        except OSError:
            continue


@lru_cache
def capabilities() -> dict:
    caps = {"unshare_net": False, "docker": False, "rlimits": True}
    if shutil.which("unshare"):
        try:
            r = subprocess.run(["unshare", "-rn", "true"], capture_output=True, timeout=10)
            caps["unshare_net"] = r.returncode == 0
        except Exception:
            caps["unshare_net"] = False
    if shutil.which("docker"):
        try:
            r = subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"], capture_output=True, timeout=10)
            caps["docker"] = r.returncode == 0
        except Exception:
            caps["docker"] = False
    return caps


def isolation_level() -> str:
    caps = capabilities()
    backend = get_settings().sandbox_backend
    if backend == "docker" and caps["docker"]:
        return "container"
    if caps["unshare_net"]:
        return "namespace"
    return "process"


def clean_env(tmp: Path, extra: dict | None = None) -> dict:
    bin_dir = str(Path(sys.executable).parent)
    env = {
        "PATH": f"{bin_dir}:/usr/local/bin:/usr/bin:/bin",
        "HOME": str(tmp / "home"),
        "TMPDIR": str(tmp / "tmp"),
        "LANG": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
        "PYTHONUNBUFFERED": "1",
        "ULTRON_ENV": "test",
        "ULTRON_DATA_DIR": str(tmp / "data"),
        "ULTRON_ENABLE_BACKGROUND": "false",
        "ULTRON_IN_SANDBOX": "1",
        "CI": "1",
        "NO_COLOR": "1",
    }
    for k in SAFE_ENV_KEYS:
        if k in os.environ and k not in env:
            env[k] = os.environ[k]
    for k, v in (extra or {}).items():
        up = k.upper()
        if any(s in up for s in ("KEY", "TOKEN", "SECRET", "PASSWORD", "DATABASE_URL", "PROXY")):
            continue  # nunca repassar segredos ou rotas de rede
        env[k] = v
    return env


def _limits(mem_mb: int, cpu_s: int, drop: bool):
    def apply() -> None:
        os.setsid()
        resource.setrlimit(resource.RLIMIT_AS, (mem_mb * 1024 * 1024, mem_mb * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s + 5))
        resource.setrlimit(resource.RLIMIT_FSIZE, (200 * 1024 * 1024, 200 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        try:
            resource.setrlimit(resource.RLIMIT_NOFILE, (1024, 1024))
        except (ValueError, OSError):
            pass
        if drop:
            os.setgroups([])
            os.setgid(SANDBOX_UID)
            os.setuid(SANDBOX_UID)

    return apply


async def run(cmd: list[str], cwd: Path, *, timeout: int | None = None, network: bool = False,
              mem_mb: int | None = None, extra_env: dict | None = None, label: str = "", proposal_id: str = "",
              record: bool = True, tmp_root: Path | None = None, owner_root: Path | None = None) -> dict:
    s = get_settings()
    timeout = timeout or s.sandbox_timeout_seconds
    mem_mb = mem_mb or max(1024, s.sandbox_memory_mb)
    level = isolation_level()
    tmp = Path(tempfile.mkdtemp(prefix="ultron-sbx-", dir=str(tmp_root) if tmp_root else None))
    for d in ("home", "tmp", "data"):
        (tmp / d).mkdir()
    env = clean_env(tmp, extra_env)
    drop = drops_privileges() and level != "container"
    if drop:
        _chown_tree(tmp)
        root_for_owner = Path(owner_root or cwd)
        _chown_tree(root_for_owner)
        _ensure_traversable(root_for_owner)
        _ensure_traversable(tmp)
    full = list(cmd)
    net_state = "allowed" if network else "none"
    if level == "container" and s.sandbox_docker_image:
        full = ["docker", "run", "--rm", "--network", "bridge" if network else "none", "--memory", f"{mem_mb}m",
                "--cpus", "1", "--pids-limit", "256", "-v", f"{cwd}:/work", "-w", "/work",
                *[x for k, v in env.items() for x in ("-e", f"{k}={v}")], s.sandbox_docker_image, *cmd]
        net_state = "isolated" if not network else "allowed"
    elif not network and level == "namespace":
        full = ["unshare", "-rn", "--", *cmd]
        net_state = "isolated"
    elif not network:
        net_state = "not_isolated"
    isolation = {"level": level, "network": net_state, "memory_mb": mem_mb, "timeout_s": timeout,
                 "clean_env": True, "user": "nobody" if drop else "server-user", "env_keys": sorted(env.keys())}
    t0 = time.monotonic()
    timed_out = False
    try:
        proc = await asyncio.create_subprocess_exec(
            *full, cwd=str(cwd), env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL, preexec_fn=_limits(mem_mb, timeout + 10, drop),
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            timed_out = True
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            out, err = await proc.communicate()
        code = proc.returncode if not timed_out else -9
    except FileNotFoundError as e:
        out, err, code = b"", str(e).encode(), 127
    duration = int((time.monotonic() - t0) * 1000)
    stdout = out.decode(errors="replace")
    stderr = err.decode(errors="replace")
    result = {"exit_code": code, "stdout": tail(stdout, OUTPUT_LIMIT), "stderr": tail(stderr, OUTPUT_LIMIT),
              "duration_ms": duration, "timed_out": timed_out, "isolation": isolation, "tmp": str(tmp)}
    if record:
        async with session_scope() as sess:
            row = SandboxRun(proposal_id=proposal_id, label=label[:60], command=cmd[:30],
                             status="timeout" if timed_out else ("ok" if code == 0 else "failed"), exit_code=code,
                             duration_ms=duration, stdout_tail=tail(stdout, 8000), stderr_tail=tail(stderr, 4000),
                             isolation=isolation)
            sess.add(row)
            await sess.flush()
            result["run_id"] = row.id
    return result


def cleanup(result: dict) -> None:
    tmp = result.get("tmp")
    if tmp and Path(tmp).name.startswith("ultron-sbx-"):
        shutil.rmtree(tmp, ignore_errors=True)


def parse_junit(path: Path) -> dict:
    out = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0, "time": 0.0, "failed_ids": [], "passed_ids": []}
    if not path.exists():
        return out
    try:
        root = ET.parse(path).getroot()  # noqa: S314 - arquivo gerado localmente pelo pytest
    except ET.ParseError:
        return out
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    for suite in suites:
        out["tests"] += int(suite.get("tests", 0))
        out["failures"] += int(suite.get("failures", 0))
        out["errors"] += int(suite.get("errors", 0))
        out["skipped"] += int(suite.get("skipped", 0))
        out["time"] += float(suite.get("time", 0) or 0)
        for case in suite.iter("testcase"):
            cid = f"{case.get('classname')}::{case.get('name')}"
            if case.find("failure") is not None or case.find("error") is not None:
                out["failed_ids"].append(cid)
            elif case.find("skipped") is None:
                out["passed_ids"].append(cid)
    out["passed"] = out["tests"] - out["failures"] - out["errors"] - out["skipped"]
    return out


async def run_test_suite(ws, *, ref: str | None = None, worktree: Path | None = None, test_path: str = "",
                         label: str = "tests", proposal_id: str = "") -> dict:
    """Executa a suíte pytest do backend em uma worktree, no sandbox."""
    created = False
    if worktree is None:
        ref = ref or await ws.head()
        worktree = await ws.detached_worktree(ref, f"sbx-{label}-{ref[:10]}")
        created = True
    backend = worktree / "backend"
    try:
        junit_dir = Path(tempfile.mkdtemp(prefix="ultron-junit-"))
        if drops_privileges():
            _chown_tree(junit_dir)
        junit = junit_dir / "junit.xml"
        target = test_path if test_path else "tests"
        if test_path and (".." in test_path or test_path.startswith("/")):
            return {"passed": 0, "failed": 0, "errors": 1, "exit_code": 2, "duration_ms": 0,
                    "isolation": {}, "output_tail": "caminho de teste inválido"}
        cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={junit}", target]
        if drops_privileges():
            _ensure_traversable(junit_dir)
        res = await run(cmd, backend, label=label, proposal_id=proposal_id,
                        extra_env={"PYTHONPATH": str(backend)}, owner_root=worktree)
        parsed = parse_junit(junit)
        shutil.rmtree(junit_dir, ignore_errors=True)
        cleanup(res)
        summary = {
            "passed": parsed.get("passed", 0), "failed": parsed["failures"], "errors": parsed["errors"],
            "skipped": parsed["skipped"], "tests": parsed["tests"], "time_s": round(parsed["time"], 2),
            "failed_ids": parsed["failed_ids"][:100], "passed_ids_count": len(parsed["passed_ids"]),
            "exit_code": res["exit_code"], "duration_ms": res["duration_ms"], "timed_out": res["timed_out"],
            "isolation": res["isolation"], "run_id": res.get("run_id"),
            "output_tail": tail(res["stdout"] + "\n" + res["stderr"], 6000),
        }
        if parsed["tests"] == 0 and res["exit_code"] not in (0, 5):
            summary["errors"] = max(1, summary["errors"])  # coleta falhou (erro de importação/sintaxe)
        if res.get("run_id"):
            async with session_scope() as sess:
                row = await sess.get(SandboxRun, res["run_id"])
                if row:
                    row.parsed = {k: v for k, v in summary.items() if k not in ("output_tail",)}
        return summary
    finally:
        if created:
            await ws.remove_worktree(worktree)


ALLOWED_COMMANDS: tuple[tuple[str, ...], ...] = (
    ("python", "-m", "pytest"),
    ("python", "-m", "ruff", "check"),
    ("python", "-m", "py_compile"),
    ("git", "log"),
    ("git", "diff"),
    ("git", "status"),
    ("git", "show"),
    ("ls",),
    ("wc",),
)


def is_allowed_command(cmd: list[str]) -> tuple[bool, str]:
    if not cmd:
        return False, "comando vazio"
    for prefix in ALLOWED_COMMANDS:
        if tuple(cmd[: len(prefix)]) == prefix:
            for arg in cmd[len(prefix):]:
                if arg.startswith("/") or ".." in arg or arg.startswith("--exec") or arg.startswith("--output"):
                    return False, f"argumento não permitido: {arg}"
                if prefix[0] == "git" and arg.startswith(("-c", "--upload-pack", "--ext-diff")):
                    return False, f"opção git não permitida: {arg}"
            return True, ""
    return False, "comando fora da lista permitida (pytest, ruff, py_compile, git log/diff/status/show, ls, wc)"


async def run_allowed_command(ws, cmd: list[str], *, ref: str | None = None) -> dict:
    ok, reason = is_allowed_command(cmd)
    if not ok:
        return {"exit_code": 126, "output": f"NEGADO: {reason}", "isolation": {"network": "n/a"}}
    real = [sys.executable, *cmd[1:]] if cmd[0] == "python" else cmd
    ref = ref or await ws.head()
    wt = await ws.detached_worktree(ref, f"sbx-cmd-{int(time.time())}")
    try:
        cwd = wt / "backend" if cmd[0] == "python" else wt
        res = await run(real, cwd, timeout=300, label="command", extra_env={"PYTHONPATH": str(wt / "backend")},
                        owner_root=wt)
        cleanup(res)
        return {"exit_code": res["exit_code"], "output": tail(res["stdout"] + "\n" + res["stderr"], 8000),
                "isolation": res["isolation"]}
    finally:
        await ws.remove_worktree(wt)
