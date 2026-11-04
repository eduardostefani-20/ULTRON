"""Dependências da API: autenticação por Bearer token."""

from __future__ import annotations

import time
from collections import defaultdict, deque

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from ultron.db import get_session
from ultron.models import User
from ultron.security.tokens import decode_access_token

bearer = HTTPBearer(auto_error=False)


async def current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer),
                       session: AsyncSession = Depends(get_session)) -> User:
    if creds is None or not creds.credentials:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "autenticação necessária",
                            headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = decode_access_token(creds.credentials)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "sessão expirada", headers={"WWW-Authenticate": "Bearer"})
    except jwt.InvalidTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token inválido", headers={"WWW-Authenticate": "Bearer"})
    user = await session.get(User, payload.get("sub"))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "usuário não encontrado")
    return user


async def owner(user: User = Depends(current_user)) -> User:
    if user.role != "owner":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "apenas o proprietário pode executar esta ação")
    return user


class RateLimiter:
    def __init__(self, limit: int, window_s: float):
        self.limit = limit
        self.window = window_s
        self.hits: dict[str, deque] = defaultdict(deque)

    def check(self, key: str) -> None:
        now = time.monotonic()
        q = self.hits[key]
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.limit:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "muitas tentativas — aguarde um minuto")
        q.append(now)

    def reset(self) -> None:
        self.hits.clear()


auth_limiter = RateLimiter(10, 60)


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "?")
