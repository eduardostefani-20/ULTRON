"""Workspace de desenvolvimento: clone próprio do repositório do ULTRON + git worktrees isoladas.

A versão em execução NUNCA é alterada diretamente. Experimentos acontecem em branches
``evolution/*`` dentro de worktrees separadas; a publicação é um merge controlado.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from ultron.config import get_settings
from ultron.governance.policy import FileChange, normalize_rel_path, path_matches

log = logging.getLogger("ultron.workspace")

GIT_AUTHOR = ("ULTRON", "ultron@users.noreply.github.com")
READ_DENY = ("**/.env", "**/.env.*", ".env", "**/secret.key", ".git/**", "**/.git/**", "backend/data/**",
             "**/*.pem", "**/*.key")
SKIP_DIRS = {".git", "node_modules", ".next", "out", ".venv", "venv", "__pycache__", "data", ".pytest_cache",
             ".ruff_cache", "dist", "build", ".mypy_cache"}


class GitError(RuntimeError):
    pass


@dataclass
class GitResult:
    code: int
    out: str
    err: str


def _auth_header(token: str) -> str:
    raw = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return f"http.https://github.com/.extraheader=AUTHORIZATION: basic {raw}"


async def git(*args: str, cwd: Path, token: str = "", check: bool = True, timeout: float = 300) -> GitResult:
    cmd = ["git"]
    if token:
        cmd += ["-c", _auth_header(token)]
    cmd += ["-c", f"user.name={GIT_AUTHOR[0]}", "-c", f"user.email={GIT_AUTHOR[1]}", "-c", "core.hooksPath=/dev/null",
            *args]
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    proc = await asyncio.create_subprocess_exec(*cmd, cwd=str(cwd), stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.PIPE, env=env)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        raise GitError(f"git {' '.join(args[:2])}: tempo esgotado") from None
    res = GitResult(proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace"))
    if check and res.code != 0:
        safe_err = res.err.replace(token, "***") if token else res.err
        raise GitError(f"git {' '.join(args[:3])} falhou ({res.code}): {safe_err.strip()[:500]}")
    return res


class GitWorkspace:
    def __init__(self, root: Path, base_branch: str = "", remote_url: str = "", token: str = "") -> None:
        self.root = root
        self.base_branch = base_branch
        self.remote_url = remote_url
        self.token = token
        self.worktrees_dir = root.parent / "worktrees"
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ preparo

    @property
    def ready(self) -> bool:
        return (self.root / ".git").exists()

    async def ensure(self, source: str = "") -> None:
        """Clona o repositório se necessário (do GitHub com token ou de um diretório local)."""
        async with self._lock:
            if self.ready:
                return
            self.root.parent.mkdir(parents=True, exist_ok=True)
            src = self.remote_url or source
            if not src:
                raise GitError("nenhuma origem configurada para o workspace (ULTRON_REPO_URL ou diretório local)")
            await git("clone", "--no-hardlinks", src, str(self.root), cwd=self.root.parent,
                      token=self.token if src.startswith("https://github.com") else "", timeout=600)
            if not self.base_branch:
                self.base_branch = await self.current_branch()

    async def current_branch(self) -> str:
        r = await git("rev-parse", "--abbrev-ref", "HEAD", cwd=self.root)
        return r.out.strip()

    async def has_remote(self) -> bool:
        r = await git("remote", cwd=self.root, check=False)
        return "origin" in r.out.split()

    async def sync(self) -> dict:
        """Atualiza o branch base com o remoto (fast-forward apenas)."""
        info = {"fetched": False, "fast_forwarded": False, "diverged": False}
        if not await self.has_remote():
            return info
        r = await git("fetch", "origin", self.base_branch, cwd=self.root, token=self.token, check=False, timeout=300)
        if r.code != 0:
            info["error"] = r.err.strip()[:300]
            return info
        info["fetched"] = True
        await git("checkout", self.base_branch, cwd=self.root)
        ff = await git("merge", "--ff-only", f"origin/{self.base_branch}", cwd=self.root, check=False)
        if ff.code == 0:
            info["fast_forwarded"] = "Already up to date" not in ff.out
        else:
            info["diverged"] = True
        return info

    async def head(self, ref: str | None = None) -> str:
        r = await git("rev-parse", ref or self.base_branch, cwd=self.root)
        return r.out.strip()

    async def tree(self, ref: str) -> str:
        r = await git("rev-parse", f"{ref}^{{tree}}", cwd=self.root)
        return r.out.strip()

    # ------------------------------------------------------------------ worktrees

    async def create_worktree(self, branch: str, base_ref: str | None = None) -> Path:
        path = self.worktrees_dir / re.sub(r"[^A-Za-z0-9_.-]", "_", branch)
        if path.exists():
            await self.remove_worktree(path)
        self.worktrees_dir.mkdir(parents=True, exist_ok=True)
        exists = (await git("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", cwd=self.root,
                            check=False)).code == 0
        if exists:
            await git("worktree", "add", str(path), branch, cwd=self.root)
        else:
            await git("worktree", "add", "-b", branch, str(path), base_ref or self.base_branch, cwd=self.root)
        return path

    async def detached_worktree(self, ref: str, name: str) -> Path:
        path = self.worktrees_dir / re.sub(r"[^A-Za-z0-9_.-]", "_", name)
        if path.exists():
            await self.remove_worktree(path)
        self.worktrees_dir.mkdir(parents=True, exist_ok=True)
        await git("worktree", "add", "--detach", str(path), ref, cwd=self.root)
        return path

    async def remove_worktree(self, path: Path) -> None:
        await git("worktree", "remove", "--force", str(path), cwd=self.root, check=False)
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
        await git("worktree", "prune", cwd=self.root, check=False)

    async def commit_all(self, worktree: Path, message: str) -> str | None:
        await git("add", "-A", cwd=worktree)
        st = await git("status", "--porcelain", cwd=worktree)
        if not st.out.strip():
            return None
        await git("commit", "-m", message, "--author", f"{GIT_AUTHOR[0]} <{GIT_AUTHOR[1]}>", cwd=worktree)
        return (await git("rev-parse", "HEAD", cwd=worktree)).out.strip()

    async def delete_branch(self, branch: str) -> None:
        await git("branch", "-D", branch, cwd=self.root, check=False)

    async def branches(self, prefix: str = "") -> list[dict]:
        r = await git("for-each-ref", "--format=%(refname:short)|%(objectname:short)|%(committerdate:iso8601)|"
                      "%(subject)", "refs/heads", cwd=self.root)
        out = []
        for line in r.out.splitlines():
            parts = line.split("|", 3)
            if len(parts) == 4 and parts[0].startswith(prefix):
                out.append({"name": parts[0], "sha": parts[1], "date": parts[2], "subject": parts[3]})
        return out

    async def log(self, ref: str | None = None, n: int = 20) -> list[dict]:
        r = await git("log", ref or self.base_branch, f"-{n}", "--format=%h|%an|%ad|%s", "--date=iso", cwd=self.root,
                      check=False)
        out = []
        for line in r.out.splitlines():
            p = line.split("|", 3)
            if len(p) == 4:
                out.append({"sha": p[0], "author": p[1], "date": p[2], "subject": p[3]})
        return out

    # ------------------------------------------------------------------ diffs

    async def diff_changes(self, base: str, head: str) -> list[FileChange]:
        """Mudanças reais calculadas pelo git (base da classificação de risco)."""
        ns = await git("diff", "--name-status", "-M", f"{base}..{head}", cwd=self.root)
        changes: dict[str, FileChange] = {}
        for line in ns.out.splitlines():
            parts = line.split("\t")
            if not parts or not parts[0]:
                continue
            status = parts[0][0]
            if status == "R" and len(parts) >= 3:
                changes[parts[2]] = FileChange(parts[2], "R", old_path=parts[1])
            elif len(parts) >= 2:
                changes[parts[1]] = FileChange(parts[1], status)
        patch = await git("diff", "-U0", "--no-color", "-M", f"{base}..{head}", cwd=self.root)
        current: FileChange | None = None
        for line in patch.out.splitlines():
            if line.startswith("+++ "):
                path = line[4:]
                path = path[2:] if path.startswith("b/") else path
                current = changes.get(path)
            elif line.startswith("--- "):
                continue
            elif current is not None and line.startswith("+"):
                current.added_lines.append(line[1:])
            elif current is not None and line.startswith("-"):
                current.removed_count += 1
        # arquivos removidos: conta as linhas removidas
        for ch in changes.values():
            if ch.status == "D" and ch.removed_count == 0:
                ch.removed_count = 1
        return list(changes.values())

    async def diff_text(self, base: str, head: str, max_chars: int = 60000) -> str:
        r = await git("diff", "--no-color", "-M", "--stat", "-p", f"{base}..{head}", cwd=self.root)
        return r.out[:max_chars]

    # ------------------------------------------------------------------ merge / revert / push

    async def merge_into_base(self, branch: str, message: str) -> str:
        await git("checkout", self.base_branch, cwd=self.root)
        await git("merge", "--no-ff", "-m", message, branch, cwd=self.root)
        return await self.head()

    async def revert_merge(self, merge_sha: str, message: str) -> str:
        await git("checkout", self.base_branch, cwd=self.root)
        parents = (await git("rev-list", "--parents", "-n", "1", merge_sha, cwd=self.root)).out.split()
        args = ["revert", "--no-edit"]
        if len(parents) > 2:
            args += ["-m", "1"]
        await git(*args, merge_sha, cwd=self.root)
        await git("commit", "--amend", "-m", message, cwd=self.root, check=False)
        return await self.head()

    async def push(self, ref: str, *, force: bool = False) -> bool:
        if not self.token or not await self.has_remote():
            return False
        args = ["push", "origin", ref] + (["--force-with-lease"] if force else [])
        await git(*args, cwd=self.root, token=self.token, timeout=300)
        return True

    # ------------------------------------------------------------------ leitura segura

    def _safe_path(self, rel: str, base: Path | None = None) -> Path:
        root = (base or self.root).resolve()
        norm = normalize_rel_path(rel) if rel not in ("", ".") else "."
        if norm is None:
            raise PermissionError(f"caminho inválido: {rel!r}")
        if norm != "." and path_matches(norm, READ_DENY):
            raise PermissionError("leitura bloqueada: arquivo sensível ou interno")
        target = (root / norm).resolve()
        if target != root and root not in target.parents:
            raise PermissionError("caminho fora do workspace")
        return target

    def read_text(self, rel: str, max_chars: int = 12000, base: Path | None = None) -> str:
        p = self._safe_path(rel, base)
        if not p.is_file():
            return f"arquivo não encontrado: {rel}"
        if p.stat().st_size > 2_000_000:
            return "arquivo grande demais para leitura"
        text = p.read_text(errors="replace")
        if len(text) > max_chars:
            return text[:max_chars] + f"\n…[arquivo truncado: {len(text)} caracteres no total]"
        return text

    def list_dir(self, rel: str = ".") -> list[str]:
        p = self._safe_path(rel)
        if not p.is_dir():
            return []
        out = []
        for child in sorted(p.iterdir()):
            if child.name in SKIP_DIRS or child.name.startswith(".env"):
                continue
            out.append(f"{child.relative_to(self.root.resolve())}{'/' if child.is_dir() else ''}")
        return out

    def iter_files(self, base: Path | None = None, exts: tuple[str, ...] | None = None):
        root = (base or self.root).resolve()
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for f in filenames:
                if exts and not f.endswith(exts):
                    continue
                full = Path(dirpath) / f
                rel = full.relative_to(root).as_posix()
                if path_matches(rel, READ_DENY):
                    continue
                yield rel, full

    def grep(self, pattern: str, glob: str = "", max_hits: int = 60) -> list[str]:
        try:
            rx = re.compile(pattern)
        except re.error as e:
            return [f"regex inválida: {e}"]
        hits: list[str] = []
        glob_rx = None
        if glob:
            glob_rx = re.compile("^" + re.escape(glob).replace(r"\*", ".*") + "$")
        for rel, full in self.iter_files(exts=(".py", ".ts", ".tsx", ".js", ".md", ".json", ".toml", ".yml", ".yaml",
                                               ".css", ".html", ".txt", ".sh")):
            if glob_rx and not glob_rx.match(Path(rel).name) and not glob_rx.match(rel):
                continue
            try:
                for i, line in enumerate(full.read_text(errors="replace").splitlines(), 1):
                    if rx.search(line):
                        hits.append(f"{rel}:{i}: {line.strip()[:200]}")
                        if len(hits) >= max_hits:
                            return hits
            except OSError:
                continue
        return hits


_workspace: GitWorkspace | None = None


async def get_workspace(ensure: bool = True) -> GitWorkspace:
    global _workspace
    s = get_settings()
    if _workspace is None:
        token = s.github_token
        if not token:
            try:
                from ultron.db import session_scope
                from ultron.providers.registry import get_credential

                async with session_scope() as sess:
                    cred = await get_credential(sess, "github")
                token = cred.key if cred else ""
            except Exception:
                token = ""
        remote = s.repo_url
        if not remote and s.github_repo:
            remote = f"https://github.com/{s.github_repo}.git"
        _workspace = GitWorkspace(s.resolved_workspace_dir / "repo", s.git_base_branch, remote, token)
    if ensure and not _workspace.ready:
        await _workspace.ensure(str(s.repo_source_dir))
    if ensure and not _workspace.base_branch:
        _workspace.base_branch = await _workspace.current_branch()
    return _workspace


def reset_workspace() -> None:
    global _workspace
    _workspace = None
