"""Busca na web com cadeia de provedores: Tavily → Brave → Serper → SearXNG → Wikipedia → DuckDuckGo."""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, quote, unquote, urlsplit

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.ext.asyncio import AsyncSession

from ultron.providers.registry import load_credentials

log = logging.getLogger("ultron.search")
UA = {"User-Agent": "ULTRON-Research/0.1"}


@dataclass
class SearchHit:
    title: str
    url: str
    snippet: str
    provider: str


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", text or ""))).strip()


async def _tavily(key: str, q: str, n: int) -> list[SearchHit]:
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post("https://api.tavily.com/search", headers={"Authorization": f"Bearer {key}"},
                         json={"query": q, "max_results": n, "search_depth": "basic"})
        r.raise_for_status()
        return [SearchHit(x.get("title", ""), x.get("url", ""), _clean(x.get("content", ""))[:400], "tavily")
                for x in r.json().get("results", [])]


async def _brave(key: str, q: str, n: int) -> list[SearchHit]:
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get("https://api.search.brave.com/res/v1/web/search", params={"q": q, "count": n},
                        headers={"X-Subscription-Token": key, "Accept": "application/json"})
        r.raise_for_status()
        return [SearchHit(x.get("title", ""), x.get("url", ""), _clean(x.get("description", ""))[:400], "brave")
                for x in (r.json().get("web") or {}).get("results", [])]


async def _serper(key: str, q: str, n: int) -> list[SearchHit]:
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post("https://google.serper.dev/search", headers={"X-API-KEY": key}, json={"q": q, "num": n})
        r.raise_for_status()
        return [SearchHit(x.get("title", ""), x.get("link", ""), _clean(x.get("snippet", ""))[:400], "serper")
                for x in r.json().get("organic", [])]


async def _searxng(base: str, q: str, n: int) -> list[SearchHit]:
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(base.rstrip("/") + "/search", params={"q": q, "format": "json"}, headers=UA)
        r.raise_for_status()
        return [SearchHit(x.get("title", ""), x.get("url", ""), _clean(x.get("content", ""))[:400], "searxng")
                for x in r.json().get("results", [])[:n]]


async def wikipedia(q: str, n: int, lang: str = "pt") -> list[SearchHit]:
    async with httpx.AsyncClient(timeout=15, headers=UA) as c:
        r = await c.get(f"https://{lang}.wikipedia.org/w/api.php",
                        params={"action": "query", "list": "search", "srsearch": q, "format": "json", "srlimit": n})
        r.raise_for_status()
        out = []
        for x in r.json().get("query", {}).get("search", []):
            title = x.get("title", "")
            out.append(SearchHit(title, f"https://{lang}.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}",
                                 _clean(x.get("snippet", "")), "wikipedia"))
        return out


async def _duckduckgo(q: str, n: int) -> list[SearchHit]:
    async with httpx.AsyncClient(timeout=15, headers={"User-Agent": "Mozilla/5.0 (ULTRON)"}) as c:
        r = await c.post("https://html.duckduckgo.com/html/", data={"q": q})
        r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    for res in soup.select(".result")[: n * 2]:
        a = res.select_one("a.result__a")
        if not a or not a.get("href"):
            continue
        href = a["href"]
        if "uddg=" in href:
            href = unquote(parse_qs(urlsplit(href).query).get("uddg", [href])[0])
        if not href.startswith("http"):
            continue
        snip = res.select_one(".result__snippet")
        out.append(SearchHit(a.get_text(" ", strip=True), href, snip.get_text(" ", strip=True) if snip else "",
                             "duckduckgo"))
        if len(out) >= n:
            break
    return out


async def available_search_providers(session: AsyncSession) -> list[str]:
    creds = await load_credentials(session)
    chain = [p for p in ("tavily", "brave", "serper", "searxng") if p in creds]
    return chain + ["wikipedia", "duckduckgo"]


async def search(session: AsyncSession, query: str, max_results: int = 5) -> tuple[str, list[SearchHit], list[str]]:
    """Retorna (provedor usado, resultados, erros)."""
    creds = await load_credentials(session)
    errors: list[str] = []
    chain = []
    for p in ("tavily", "brave", "serper", "searxng"):
        if p in creds:
            chain.append(p)
    chain += ["duckduckgo", "wikipedia"] if not chain else ["wikipedia"]
    for p in chain:
        try:
            if p == "tavily":
                hits = await _tavily(creds[p].key, query, max_results)
            elif p == "brave":
                hits = await _brave(creds[p].key, query, max_results)
            elif p == "serper":
                hits = await _serper(creds[p].key, query, max_results)
            elif p == "searxng":
                hits = await _searxng(creds[p].base_url, query, max_results)
            elif p == "wikipedia":
                hits = await wikipedia(query, max_results)
            else:
                hits = await _duckduckgo(query, max_results)
            hits = [h for h in hits if h.url.startswith("http")]
            if hits:
                return p, hits[:max_results], errors
            errors.append(f"{p}: sem resultados")
        except Exception as e:
            errors.append(f"{p}: {e.__class__.__name__}: {str(e)[:150]}")
    return "", [], errors
