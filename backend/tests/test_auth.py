"""Autenticação e sessão."""

from __future__ import annotations

import pytest


async def test_setup_once_and_login(client):
    r = await client.post("/api/auth/setup", json={"email": "a@b.com", "password": "fraca"})
    assert r.status_code == 400
    r = await client.post("/api/auth/setup", json={"email": "a@b.com", "password": "Senha-Forte-2026"})
    assert r.status_code == 200
    r = await client.post("/api/auth/setup", json={"email": "x@y.com", "password": "Senha-Forte-2026"})
    assert r.status_code == 409
    assert (await client.get("/api/auth/status")).json()["setup_required"] is False
    r = await client.post("/api/auth/login", json={"email": "A@B.com", "password": "Senha-Forte-2026"})
    assert r.status_code == 200 and r.json()["user"]["role"] == "owner"


async def test_setup_token_enforced(client, monkeypatch):
    from ultron.config import reset_settings_cache

    monkeypatch.setenv("ULTRON_SETUP_TOKEN", "token-secreto-123")
    reset_settings_cache()
    r = await client.post("/api/auth/setup", json={"email": "a@b.com", "password": "Senha-Forte-2026",
                                                   "setup_token": "errado"})
    assert r.status_code == 403
    r = await client.post("/api/auth/setup", json={"email": "a@b.com", "password": "Senha-Forte-2026",
                                                   "setup_token": "token-secreto-123"})
    assert r.status_code == 200
    monkeypatch.delenv("ULTRON_SETUP_TOKEN")
    reset_settings_cache()


async def test_lockout_after_failed_attempts(client, auth):
    for _ in range(5):
        r = await client.post("/api/auth/login", json={"email": "dono@ultron.dev", "password": "errada"})
        assert r.status_code == 401
    r = await client.post("/api/auth/login", json={"email": "dono@ultron.dev", "password": "Senha-Forte-2026"})
    assert r.status_code == 423


async def test_refresh_rotation_and_reuse_detection(client, auth):
    old = auth["_refresh"]
    r = await client.post("/api/auth/refresh", json={"refresh_token": old})
    assert r.status_code == 200
    new = r.json()["refresh_token"]
    # reutilizar o token antigo (possível roubo) revoga todas as sessões
    assert (await client.post("/api/auth/refresh", json={"refresh_token": old})).status_code == 401
    assert (await client.post("/api/auth/refresh", json={"refresh_token": new})).status_code == 401


@pytest.mark.parametrize("token", ["", "abc", "Bearer x.y.z"])
async def test_invalid_tokens_rejected(client, auth, token):
    r = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


async def test_change_password_revokes_sessions(client, auth, headers):
    r = await client.post("/api/auth/change-password", headers=headers,
                          json={"current_password": "Senha-Forte-2026", "new_password": "Outra-Senha-2027"})
    assert r.status_code == 200
    assert (await client.post("/api/auth/refresh", json={"refresh_token": auth["_refresh"]})).status_code == 401


async def test_admin_password_reset(client, auth):
    from ultron.admin import reset_password

    assert "pelo menos" in await reset_password("dono@ultron.dev", "curta")
    assert "redefinida" in await reset_password("dono@ultron.dev", "Nova-Senha-Forte-1")
    r = await client.post("/api/auth/login", json={"email": "dono@ultron.dev", "password": "Nova-Senha-Forte-1"})
    assert r.status_code == 200
    assert (await client.post("/api/auth/refresh", json={"refresh_token": auth["_refresh"]})).status_code == 401


async def test_github_token_from_integrations_has_priority(client, headers, monkeypatch):
    from ultron.admin import github_token
    from ultron.config import reset_settings_cache

    monkeypatch.setenv("GITHUB_TOKEN", "ghp_do_ambiente_antigo_0000000000000000")
    reset_settings_cache()
    assert await github_token() == "ghp_do_ambiente_antigo_0000000000000000"
    r = await client.put("/api/integrations/github", headers=headers,
                         json={"api_key": "github_pat_novo_salvo_no_app_123456789012345"})
    assert r.status_code == 200
    from ultron.providers import registry

    registry.invalidate()
    assert await github_token() == "github_pat_novo_salvo_no_app_123456789012345"
