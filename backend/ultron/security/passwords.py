"""Hash de senhas com Argon2id."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()

MIN_PASSWORD_LENGTH = 10


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def validate_password_strength(password: str) -> str | None:
    """Retorna mensagem de erro, ou None se a senha for aceitável."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"A senha precisa ter pelo menos {MIN_PASSWORD_LENGTH} caracteres."
    classes = sum(
        [
            any(c.islower() for c in password),
            any(c.isupper() for c in password),
            any(c.isdigit() for c in password),
            any(not c.isalnum() for c in password),
        ]
    )
    if classes < 2:
        return "Use pelo menos dois tipos de caracteres (letras, números, símbolos)."
    return None
