"""Integrações: chaves de provedores (cifradas, nunca devolvidas ao frontend)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ultron.api.common import iso
from ultron.api.deps import current_user, owner
from ultron.db import get_session
from ultron.governance import audit
from ultron.models import ProviderCredential, User
from ultron.providers import registry
from ultron.providers.catalog import PROVIDERS, TIERS, default_model, models_for
from ultron.providers.router import health
from ultron.security.vault import encrypt_secret, mask
from ultron.utils import utcnow

router = APIRouter(prefix="/api/integrations", tags=["integrations"])


class CredentialIn(BaseModel):
    api_key: str | None = Field(default=None, max_length=500)
    base_url: str | None = Field(default=None, max_length=500)
    enabled: bool = True
    models: dict[str, str] | None = None


@router.get("")
async def list_integrations(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    creds = await registry.load_credentials(session)
    rows = {r.provider: r for r in (await session.execute(select(ProviderCredential))).scalars().all()}
    hs = health.snapshot()
    out = []
    for pid, info in PROVIDERS.items():
        c = creds.get(pid)
        r = rows.get(pid)
        configured_models = (r.meta or {}).get("models", {}) if r else {}
        out.append({
            "id": pid, "name": info.name, "kind": info.kind, "key_url": info.key_url, "note": info.note,
            "key_required": info.key_required, "configured": c is not None, "source": c.source if c else None,
            "last4": (r.last4 if r and c and c.source == "integrations" else (mask(c.key) if c else "")),
            "base_url": (r.base_url if r else "") or info.base_url, "enabled": r.enabled if r else bool(c),
            "last_test_at": iso(r.last_test_at) if r else None, "last_test_ok": r.last_test_ok if r else None,
            "last_test_message": r.last_test_message if r else "",
            "models": {t: configured_models.get(t) or default_model(pid, t) for t in TIERS} if info.kind == "llm" else {},
            "catalog": [{"id": m.id, "tier": m.tier, "input_per_m": m.input_per_m, "output_per_m": m.output_per_m,
                         "context": m.context} for m in models_for(pid)],
            "health": hs.get(pid),
        })
    return out


@router.put("/{provider}")
async def save_integration(provider: str, body: CredentialIn, user: User = Depends(owner),
                           session: AsyncSession = Depends(get_session)):
    info = PROVIDERS.get(provider)
    if info is None:
        raise HTTPException(404, "provedor desconhecido")
    r = (await session.execute(select(ProviderCredential).where(ProviderCredential.provider == provider))
         ).scalar_one_or_none()
    if r is None:
        if info.key_required and not body.api_key:
            raise HTTPException(400, "informe a chave de API")
        r = ProviderCredential(provider=provider)
        session.add(r)
    if body.api_key:
        key = body.api_key.strip()
        if len(key) < 8:
            raise HTTPException(400, "chave muito curta")
        r.encrypted_key = encrypt_secret(key)
        r.last4 = mask(key)
    if body.base_url is not None:
        url = body.base_url.strip()
        if url and not url.startswith(("https://", "http://")):
            raise HTTPException(400, "URL base inválida")
        r.base_url = url
    if provider in ("ollama", "searxng") and not (r.base_url or info.base_url):
        raise HTTPException(400, "informe a URL do servidor")
    r.enabled = body.enabled
    if body.models is not None:
        r.meta = {**(r.meta or {}), "models": {k: v.strip() for k, v in body.models.items() if k in TIERS and v.strip()}}
    r.updated_at = utcnow()
    await session.flush()
    registry.invalidate()
    health.reset()
    if provider == "github":
        from ultron.evolution.workspace import reset_workspace

        reset_workspace()  # o workspace passa a usar o novo token
    await audit.record(f"user:{user.id}", "integration.saved", provider,
                       {"key_changed": bool(body.api_key), "enabled": body.enabled}, session=session)
    return {"ok": True}


@router.delete("/{provider}")
async def delete_integration(provider: str, user: User = Depends(owner), session: AsyncSession = Depends(get_session)):
    r = (await session.execute(select(ProviderCredential).where(ProviderCredential.provider == provider))
         ).scalar_one_or_none()
    if r is None:
        raise HTTPException(404, "integração não configurada pela interface")
    await session.delete(r)
    registry.invalidate()
    await audit.record(f"user:{user.id}", "integration.deleted", provider, {}, session=session)
    return {"ok": True}


@router.post("/{provider}/test")
async def test_integration(provider: str, user: User = Depends(owner), session: AsyncSession = Depends(get_session)):
    info = PROVIDERS.get(provider)
    if info is None:
        raise HTTPException(404, "provedor desconhecido")
    cred = await registry.get_credential(session, provider)
    if cred is None:
        raise HTTPException(400, "provedor não configurado")
    ok, message, extra = False, "", {}
    try:
        if info.kind == "llm":
            prov = registry.build_llm_provider(cred)
            models = await prov.list_models()
            ok, message = True, f"conexão OK — {len(models)} modelos disponíveis"
            extra["models"] = models[:200]
        elif info.kind == "search":
            from ultron.research.search import search

            used, hits, errs = await search(session, "ULTRON inteligência artificial", 3)
            ok = used == provider and bool(hits)
            message = f"{len(hits)} resultados via {used}" if hits else "; ".join(errs)
        elif provider == "github":
            from ultron.evolution.github import GitHub, repo_slug

            slug = repo_slug()
            if not slug:
                raise ValueError("defina ULTRON_GITHUB_REPO (ex.: usuario/ULTRON) no ambiente do servidor")
            repo = await GitHub(cred.key, slug).repo()
            perms = repo.get("permissions") or {}
            ok = bool(perms.get("push"))
            message = f"repositório {repo.get('full_name')} — escrita {'permitida' if ok else 'NÃO permitida'}"
    except Exception as e:
        message = f"{e.__class__.__name__}: {str(e)[:300]}"
    r = (await session.execute(select(ProviderCredential).where(ProviderCredential.provider == provider))
         ).scalar_one_or_none()
    if r:
        r.last_test_at, r.last_test_ok, r.last_test_message = utcnow(), ok, message[:1000]
    return {"ok": ok, "message": message, **extra}
