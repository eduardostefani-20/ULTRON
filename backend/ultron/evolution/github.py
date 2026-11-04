"""Integração com a API do GitHub (pull requests, merge, status de CI)."""

from __future__ import annotations

import re

import httpx

from ultron.config import get_settings

API = "https://api.github.com"


class GitHubError(RuntimeError):
    pass


def repo_slug(remote_url: str = "") -> str:
    s = get_settings()
    if s.github_repo:
        return s.github_repo
    m = re.search(r"github\.com[:/]([^/]+/[^/.]+)", remote_url or s.repo_url or "")
    return m.group(1) if m else ""


class GitHub:
    def __init__(self, token: str, slug: str, transport: httpx.AsyncBaseTransport | None = None):
        if not token or not slug:
            raise GitHubError("GitHub não configurado (token e repositório são necessários)")
        self.slug = slug
        self._headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                         "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "ULTRON"}
        self._transport = transport

    async def _req(self, method: str, path: str, **kw) -> dict | list:
        async with httpx.AsyncClient(base_url=API, headers=self._headers, timeout=30, transport=self._transport) as c:
            r = await c.request(method, path, **kw)
        if r.status_code >= 400:
            raise GitHubError(f"GitHub {method} {path}: {r.status_code} {r.text[:300]}")
        return r.json() if r.content else {}

    async def repo(self) -> dict:
        return await self._req("GET", f"/repos/{self.slug}")

    async def find_pr(self, head: str) -> dict | None:
        owner = self.slug.split("/")[0]
        prs = await self._req("GET", f"/repos/{self.slug}/pulls", params={"head": f"{owner}:{head}", "state": "open"})
        return prs[0] if prs else None

    async def create_pr(self, head: str, base: str, title: str, body: str) -> dict:
        existing = await self.find_pr(head)
        if existing:
            return existing
        return await self._req("POST", f"/repos/{self.slug}/pulls",
                               json={"head": head, "base": base, "title": title[:250], "body": body[:60000]})

    async def merge_pr(self, number: int, title: str, sha: str) -> dict:
        return await self._req("PUT", f"/repos/{self.slug}/pulls/{number}/merge",
                               json={"merge_method": "merge", "commit_title": title[:250], "sha": sha})

    async def checks(self, ref: str) -> dict:
        """Resume o estado de CI (check runs) de um commit: success | pending | failure | none."""
        data = await self._req("GET", f"/repos/{self.slug}/commits/{ref}/check-runs")
        runs = data.get("check_runs", []) if isinstance(data, dict) else []
        if not runs:
            return {"state": "none", "runs": []}
        states = [(r.get("status"), r.get("conclusion")) for r in runs]
        if any(st != "completed" for st, _ in states):
            state = "pending"
        elif all(c in ("success", "skipped", "neutral") for _, c in states):
            state = "success"
        else:
            state = "failure"
        return {"state": state, "runs": [{"name": r.get("name"), "status": r.get("status"),
                                          "conclusion": r.get("conclusion")} for r in runs]}


async def client_from_settings() -> GitHub | None:
    from ultron.evolution.workspace import get_workspace

    ws = await get_workspace(ensure=False)
    slug = repo_slug(ws.remote_url)
    if not ws.token or not slug:
        return None
    return GitHub(ws.token, slug)
