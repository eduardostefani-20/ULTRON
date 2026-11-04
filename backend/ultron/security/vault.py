"""Cofre de segredos: cifra chaves de API em repouso (Fernet/AES-128-CBC + HMAC).

A chave de cifragem é derivada da ULTRON_SECRET_KEY via HKDF. Segredos nunca são
devolvidos ao frontend — apenas os 4 últimos caracteres para identificação.
"""

from __future__ import annotations

import base64

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from ultron.config import get_settings


def _fernet() -> Fernet:
    master = get_settings().resolved_secret_key().encode()
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=b"ultron-vault-v1", info=b"provider-keys").derive(
        master
    )
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(token: str) -> str:
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        # chave mestra mudou: o segredo não pode ser recuperado
        return ""


def mask(value: str) -> str:
    if not value:
        return ""
    return value[-4:] if len(value) > 8 else "****"
