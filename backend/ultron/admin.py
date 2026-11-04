"""Administração pelo Shell da hospedagem.

    python -m ultron.admin reset-password seu@email.com

Pede a nova senha sem exibi-la, revoga todas as sessões e registra na auditoria.
"""

from __future__ import annotations

import asyncio
import getpass
import sys

from sqlalchemy import select


async def reset_password(email: str, password: str) -> str:
    from ultron.db import init_engine, session_scope
    from ultron.governance import audit
    from ultron.models import RefreshToken, User
    from ultron.security.passwords import hash_password, validate_password_strength
    from ultron.utils import utcnow

    err = validate_password_strength(password)
    if err:
        return err
    init_engine()
    async with session_scope() as s:
        user = (await s.execute(select(User).where(User.email == email.strip().lower()))).scalar_one_or_none()
        if user is None:
            return "usuário não encontrado"
        user.password_hash = hash_password(password)
        user.failed_logins = 0
        user.locked_until = None
        for t in (await s.execute(select(RefreshToken).where(RefreshToken.user_id == user.id,
                                                             RefreshToken.revoked_at.is_(None)))).scalars():
            t.revoked_at = utcnow()
        await audit.record("admin:shell", "auth.password_reset", user.email, {}, session=s)
    return "senha redefinida; todas as sessões foram encerradas"


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] != "reset-password":
        print(__doc__)
        return 2
    pw = getpass.getpass("Nova senha: ")
    if pw != getpass.getpass("Repita a nova senha: "):
        print("as senhas não conferem")
        return 1
    print(asyncio.run(reset_password(argv[2], pw)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
