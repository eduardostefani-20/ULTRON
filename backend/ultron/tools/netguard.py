"""Proteção de rede para acesso externo (CÓDIGO DE GOVERNANÇA).

- Somente http/https, portas 80/443 (ou explicitamente permitidas).
- Bloqueia IPs privados, loopback, link-local, metadados de nuvem e endereços reservados
  (proteção contra SSRF), inclusive após resolução DNS e redirecionamentos.
- Limita tamanho e tempo das respostas.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx

MAX_BYTES = 2_000_000
MAX_REDIRECTS = 4
ALLOWED_PORTS = {80, 443, None}
BLOCKED_HOSTS = {"metadata.google.internal", "metadata", "instance-data", "localhost"}
USER_AGENT = "ULTRON-Research/0.1 (+assistente pessoal)"


class BlockedURL(Exception):
    pass


@dataclass
class FetchResult:
    status_code: int
    url: str
    content_type: str
    content: bytes
    truncated: bool = False

    @property
    def text(self) -> str:
        enc = "utf-8"
        if "charset=" in self.content_type:
            enc = self.content_type.split("charset=")[-1].split(";")[0].strip() or "utf-8"
        try:
            return self.content.decode(enc, errors="replace")
        except LookupError:
            return self.content.decode("utf-8", errors="replace")

    def json(self):
        import json

        return json.loads(self.content)


def _ip_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or (isinstance(ip, ipaddress.IPv4Address) and ip in ipaddress.ip_network("100.64.0.0/10"))
    )


async def validate_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise BlockedURL("apenas URLs http/https são permitidas")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise BlockedURL("URL sem host")
    if parts.username or parts.password:
        raise BlockedURL("credenciais embutidas na URL não são permitidas")
    if host in BLOCKED_HOSTS or host.endswith(".internal") or host.endswith(".local"):
        raise BlockedURL(f"host bloqueado: {host}")
    if parts.port not in ALLOWED_PORTS:
        raise BlockedURL(f"porta não permitida: {parts.port}")
    try:
        ip = ipaddress.ip_address(host)
        if _ip_blocked(ip):
            raise BlockedURL(f"endereço IP interno bloqueado: {host}")
        return url
    except ValueError:
        pass
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, parts.port or (443 if parts.scheme == "https" else 80),
                                       type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise BlockedURL(f"não foi possível resolver o host {host}") from e
    for info in infos:
        addr = info[4][0]
        try:
            if _ip_blocked(ipaddress.ip_address(addr.split("%")[0])):
                raise BlockedURL(f"{host} resolve para endereço interno ({addr}) — bloqueado")
        except ValueError:
            continue
    return url


async def safe_get(url: str, *, timeout: float = 15.0, headers: dict | None = None,
                   transport: httpx.AsyncBaseTransport | None = None, max_bytes: int = MAX_BYTES) -> FetchResult:
    """GET com validação a cada redirecionamento e limite de tamanho."""
    current = url
    hdrs = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,application/json,text/plain;q=0.9"}
    hdrs.update(headers or {})
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, transport=transport) as client:
        for _ in range(MAX_REDIRECTS + 1):
            await validate_url(current)
            async with client.stream("GET", current, headers=hdrs) as resp:
                if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("location"):
                    current = urljoin(current, resp.headers["location"])
                    continue
                chunks: list[bytes] = []
                total = 0
                truncated = False
                async for chunk in resp.aiter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        truncated = True
                        break
                    chunks.append(chunk)
                return FetchResult(resp.status_code, current, resp.headers.get("content-type", ""),
                                   b"".join(chunks), truncated)
        raise BlockedURL("redirecionamentos demais")
