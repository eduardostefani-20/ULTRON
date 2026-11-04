"""Autenticação: configuração inicial do proprietário, login, renovação e logout."""

from __future__ import annotations

import hmac
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ultron.api.deps import auth_limiter, client_ip, current_user
from ultron.config import get_settings
from ultron.db import get_session
from ultron.governance import audit
from ultron.models import RefreshToken, User
from ultron.security.passwords import hash_password, validate_password_strength, verify_password
from ultron.security.tokens import create_access_token, new_refresh_token
from ultron.utils import sha256, utcnow

router = APIRouter(prefix="/api/auth", tags=["auth"])
MAX_FAILED = 5
LOCK_MINUTES = 15


class SetupIn(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=200)
    name: str = Field(default="", max_length=120)
    setup_token: str = Field(default="", max_length=500)


class LoginIn(BaseModel):
    email: str = Field(max_length=255)
    password: str = Field(max_length=200)


class RefreshIn(BaseModel):
    refresh_token: str = Field(max_length=500)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(max_length=200)
    new_password: str = Field(max_length=200)


def user_out(u: User) -> dict:
    return {"id": u.id, "email": u.email, "name": u.name, "role": u.role}


async def _issue(session: AsyncSession, user: User, request: Request) -> dict:
    access, expires = create_access_token(user.id, user.role)
    token, token_hash = new_refresh_token()
    session.add(RefreshToken(user_id=user.id, token_hash=token_hash,
                             expires_at=utcnow() + timedelta(days=get_settings().refresh_token_days),
                             user_agent=(request.headers.get("user-agent") or "")[:255]))
    await session.flush()
    return {"access_token": access, "refresh_token": token, "token_type": "bearer", "expires_in": expires,
            "user": user_out(user)}


@router.get("/status")
async def auth_status(session: AsyncSession = Depends(get_session)):
    s = get_settings()
    n = (await session.execute(select(func.count()).select_from(User))).scalar_one()
    return {"setup_required": n == 0, "setup_token_required": bool(s.setup_token) or s.is_production,
            "setup_token_configured": bool(s.setup_token)}


@router.post("/setup")
async def setup(body: SetupIn, request: Request, session: AsyncSession = Depends(get_session)):
    auth_limiter.check(f"setup:{client_ip(request)}")
    s = get_settings()
    n = (await session.execute(select(func.count()).select_from(User))).scalar_one()
    if n > 0:
        raise HTTPException(409, "o proprietário já foi configurado")
    if s.is_production and not s.setup_token:
        raise HTTPException(400, "defina ULTRON_SETUP_TOKEN no painel da hospedagem antes da configuração inicial")
    if s.setup_token and not hmac.compare_digest(body.setup_token.encode(), s.setup_token.encode()):
        await audit.record(f"ip:{client_ip(request)}", "auth.setup_denied", body.email, {}, session=session)
        raise HTTPException(403, "token de configuração inválido")
    err = validate_password_strength(body.password)
    if err:
        raise HTTPException(400, err)
    email = body.email.strip().lower()
    if "@" not in email:
        raise HTTPException(400, "e-mail inválido")
    user = User(email=email, name=body.name.strip() or email.split("@")[0], password_hash=hash_password(body.password),
                role="owner")
    session.add(user)
    await session.flush()
    await audit.record(f"user:{user.id}", "auth.owner_created", email, {}, session=session)
    return await _issue(session, user, request)


@router.post("/login")
async def login(body: LoginIn, request: Request, session: AsyncSession = Depends(get_session)):
    ip = client_ip(request)
    auth_limiter.check(f"login:{ip}")
    email = body.email.strip().lower()
    user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    now = utcnow()
    if user and user.locked_until and user.locked_until > now:
        raise HTTPException(423, "conta temporariamente bloqueada por excesso de tentativas — aguarde 15 minutos")
    if user is None or not verify_password(body.password, user.password_hash):
        if user is not None:
            user.failed_logins = (user.failed_logins or 0) + 1
            if user.failed_logins >= MAX_FAILED:
                user.locked_until = now + timedelta(minutes=LOCK_MINUTES)
                user.failed_logins = 0
        await audit.record(f"ip:{ip}", "auth.login_failed", email, {}, session=session)
        await session.commit()
        raise HTTPException(401, "e-mail ou senha incorretos")
    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = now
    await audit.record(f"user:{user.id}", "auth.login", email, {"ip": ip}, session=session)
    return await _issue(session, user, request)


@router.post("/refresh")
async def refresh(body: RefreshIn, request: Request, session: AsyncSession = Depends(get_session)):
    auth_limiter.check(f"refresh:{client_ip(request)}")
    row = (await session.execute(select(RefreshToken).where(RefreshToken.token_hash == sha256(body.refresh_token)))
           ).scalar_one_or_none()
    if row is None or row.revoked_at is not None or row.expires_at < utcnow():
        if row is not None and row.revoked_at is not None:
            # reuso de token revogado: possível roubo — revoga todas as sessões do usuário
            others = (await session.execute(select(RefreshToken).where(RefreshToken.user_id == row.user_id,
                                                                       RefreshToken.revoked_at.is_(None)))).scalars()
            for o in others:
                o.revoked_at = utcnow()
            await audit.record("system", "auth.refresh_reuse_detected", row.user_id, {}, session=session)
            await session.commit()
        raise HTTPException(401, "sessão inválida — entre novamente")
    user = await session.get(User, row.user_id)
    if user is None:
        raise HTTPException(401, "usuário não encontrado")
    row.revoked_at = utcnow()  # rotação
    return await _issue(session, user, request)


@router.post("/logout")
async def logout(body: RefreshIn, session: AsyncSession = Depends(get_session)):
    row = (await session.execute(select(RefreshToken).where(RefreshToken.token_hash == sha256(body.refresh_token)))
           ).scalar_one_or_none()
    if row and row.revoked_at is None:
        row.revoked_at = utcnow()
    return {"ok": True}


@router.get("/me")
async def me(user: User = Depends(current_user)):
    return user_out(user)


@router.post("/change-password")
async def change_password(body: ChangePasswordIn, user: User = Depends(current_user),
                          session: AsyncSession = Depends(get_session)):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(400, "senha atual incorreta")
    err = validate_password_strength(body.new_password)
    if err:
        raise HTTPException(400, err)
    user.password_hash = hash_password(body.new_password)
    tokens = (await session.execute(select(RefreshToken).where(RefreshToken.user_id == user.id,
                                                               RefreshToken.revoked_at.is_(None)))).scalars()
    for t in tokens:
        t.revoked_at = utcnow()
    await audit.record(f"user:{user.id}", "auth.password_changed", user.email, {}, session=session)
    return {"ok": True, "message": "senha alterada; entre novamente nos outros dispositivos"}
