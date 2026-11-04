"""Tokens de acesso (JWT curto) e de renovação (opacos, guardados como hash)."""

from __future__ import annotations

import secrets
from datetime import timedelta

import jwt

from ultron.config import get_settings
from ultron.utils import sha256, utcnow

ALGORITHM = "HS256"
ISSUER = "ultron"


def _signing_key() -> str:
    # deriva uma chave específica para JWT a partir da chave mestra
    return sha256("jwt:" + get_settings().resolved_secret_key())


def create_access_token(user_id: str, role: str) -> tuple[str, int]:
    s = get_settings()
    now = utcnow()
    exp = now + timedelta(minutes=s.access_token_minutes)
    payload = {
        "sub": user_id,
        "role": role,
        "iss": ISSUER,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "typ": "access",
    }
    return jwt.encode(payload, _signing_key(), algorithm=ALGORITHM), s.access_token_minutes * 60


def decode_access_token(token: str) -> dict:
    payload = jwt.decode(token, _signing_key(), algorithms=[ALGORITHM], issuer=ISSUER)
    if payload.get("typ") != "access":
        raise jwt.InvalidTokenError("tipo de token inválido")
    return payload


def new_refresh_token() -> tuple[str, str]:
    """Retorna (token em claro, hash para armazenar)."""
    token = secrets.token_urlsafe(48)
    return token, sha256(token)
