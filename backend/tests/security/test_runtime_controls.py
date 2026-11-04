"""Controles em execução: auditoria, configurações protegidas, sandbox e API."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

from ultron.db import session_scope
from ultron.evolution import sandbox
from ultron.governance import audit
from ultron.settings_store import SettingPermissionError, set_setting, system_set


async def test_audit_log_rejects_update_and_delete(app_env):
    await audit.record("teste", "evento.um", "x", {"a": 1})
    with pytest.raises(DatabaseError):
        async with session_scope() as s:
            await s.execute(text("UPDATE audit_log SET action='adulterado'"))
    with pytest.raises(DatabaseError):
        async with session_scope() as s:
            await s.execute(text("DELETE FROM audit_log"))
    async with session_scope() as s:
        assert (await audit.verify_chain(s))["valid"]


async def test_audit_chain_detects_tampering(app_env):
    for i in range(3):
        await audit.record("teste", f"evento.{i}", "x", {"i": i})
    async with session_scope() as s:
        # simula adulteração por alguém com acesso direto ao banco (remove o trigger)
        await s.execute(text("DROP TRIGGER audit_log_no_update"))
        await s.execute(text("UPDATE audit_log SET details='{\"i\": 99}' WHERE action='evento.1'"))
    async with session_scope() as s:
        res = await audit.verify_chain(s)
    assert not res["valid"] and res["broken_at"]


async def test_audit_redacts_secrets(app_env):
    await audit.record("teste", "evento.segredo", "x", {"chave": "sk-ant-" + "y" * 40})
    async with session_scope() as s:
        raw = (await s.execute(text("SELECT details FROM audit_log WHERE action='evento.segredo'"))).scalar_one()
    assert "yyyy" not in str(raw) and "REDACTED" in str(raw)


@pytest.mark.parametrize("key", ["publication.auto_publish_low_risk", "autonomy.granted_scopes", "budget.monthly_brl",
                                 "governance.x" if False else "budget.hard_stop"])
async def test_non_human_cannot_change_protected_settings(app_env, key):
    async with session_scope() as s:
        with pytest.raises(SettingPermissionError):
            await set_setting(s, key, True, actor="agent:developer", actor_is_human_owner=False)


async def test_auto_publish_requires_selftest_even_for_owner(app_env):
    async with session_scope() as s:
        with pytest.raises(SettingPermissionError):
            await set_setting(s, "publication.auto_publish_low_risk", True, actor="user:x", actor_is_human_owner=True)
        with pytest.raises(SettingPermissionError):
            await set_setting(s, "publication.safety_selftest", {"passed": True}, actor="user:x",
                              actor_is_human_owner=True)


async def test_system_can_only_disable_auto_publish(app_env):
    async with session_scope() as s:
        with pytest.raises(SettingPermissionError):
            await system_set(s, "publication.auto_publish_low_risk", True, "system")
        with pytest.raises(SettingPermissionError):
            await system_set(s, "autonomy.granted_scopes", ["publish"], "system")
        await system_set(s, "publication.auto_publish_low_risk", False, "system")


async def test_sandbox_env_has_no_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-nao-pode-vazar-123456")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db/prod")
    code = "import os,json;print(json.dumps(dict(os.environ)))"
    r = await sandbox.run([sys.executable, "-c", code], tmp_path, timeout=60, record=False,
                          extra_env={"MY_TOKEN": "abc", "SAFE": "1", "HTTPS_PROXY": "http://x"})
    sandbox.cleanup(r)
    assert r["exit_code"] == 0
    assert "sk-test" not in r["stdout"] and "postgresql" not in r["stdout"] and "MY_TOKEN" not in r["stdout"]
    assert "HTTPS_PROXY" not in r["stdout"] and '"SAFE": "1"' in r["stdout"]


@pytest.mark.skipif(not sandbox.capabilities()["unshare_net"], reason="kernel sem namespaces de rede")
async def test_sandbox_has_no_network(tmp_path):
    code = "import socket;socket.create_connection(('1.1.1.1',443),timeout=3);print('CONECTOU')"
    r = await sandbox.run([sys.executable, "-c", code], tmp_path, timeout=30, record=False)
    sandbox.cleanup(r)
    assert r["isolation"]["network"] == "isolated"
    assert "CONECTOU" not in r["stdout"] and r["exit_code"] != 0


async def test_sandbox_timeout_kills_process(tmp_path):
    r = await sandbox.run([sys.executable, "-c", "import time;time.sleep(30)"], tmp_path, timeout=2, record=False)
    sandbox.cleanup(r)
    assert r["timed_out"] and r["exit_code"] == -9


async def test_sandbox_temp_dirs_destroyed(tmp_path):
    r = await sandbox.run([sys.executable, "-c", "print('ok')"], tmp_path, timeout=30, record=False)
    tmp = Path(r["tmp"])
    assert tmp.exists()
    sandbox.cleanup(r)
    assert not tmp.exists()


@pytest.mark.parametrize("cmd", [["rm", "-rf", "/"], ["python", "-c", "print(1)"], ["git", "-c", "x=y", "log"],
                                 ["git", "push"], ["python", "-m", "pytest", "/etc"], ["ls", "../.."], ["bash"],
                                 ["git", "diff", "--output=/tmp/x"]])
def test_only_allowlisted_sandbox_commands(cmd):
    ok, _ = sandbox.is_allowed_command(cmd)
    assert not ok


async def test_every_api_route_requires_auth(app_env):
    app, client = app_env["app"], app_env["client"]
    public = {"/api/health", "/api/auth/status", "/api/auth/setup", "/api/auth/login", "/api/auth/refresh",
              "/api/auth/logout", "/api/openapi.json", "/api/docs", "/api/docs/oauth2-redirect"}
    checked = 0
    for path, ops in app.openapi()["paths"].items():
        if not path.startswith("/api/") or path in public:
            continue
        url = path.replace("{", "").replace("}", "")
        for m in ops:
            r = await client.request(m.upper(), url, json={})
            assert r.status_code == 401, f"{m} {path} respondeu {r.status_code} sem autenticação"
            checked += 1
    assert checked > 40


async def test_integration_keys_never_returned(client, headers):
    secret = "sk-ant-api03-" + "z" * 40
    r = await client.put("/api/integrations/anthropic", headers=headers, json={"api_key": secret})
    assert r.status_code == 200
    listing = (await client.get("/api/integrations", headers=headers)).text
    assert secret not in listing and "zzzz" * 3 not in listing
    async with session_scope() as s:
        raw = (await s.execute(text("SELECT encrypted_key FROM provider_credentials"))).scalar_one()
    assert secret not in raw  # cifrada em repouso
    audit_text = (await client.get("/api/audit", headers=headers)).text
    assert secret not in audit_text


async def test_settings_api_cannot_toggle_auto_publish(client, headers):
    r = await client.put("/api/settings", headers=headers, json={"values": {"publication.auto_publish_low_risk": True}})
    assert r.status_code == 400
    r = await client.post("/api/evolution/autopublish", headers=headers, json={"enabled": True, "password": "errada"})
    assert r.status_code == 403
    r = await client.post("/api/evolution/autopublish", headers=headers,
                          json={"enabled": True, "password": "Senha-Forte-2026"})
    assert r.status_code == 400 and "autoteste" in r.text


async def test_high_risk_approval_requires_password(client, headers):
    from ultron.governance.approvals import request_approval

    async with session_scope() as s:
        ap = await request_approval(s, kind="config", target_type="config", target_id="x", risk="high", title="teste")
        aid = ap.id
    r = await client.post(f"/api/approvals/{aid}/decide", headers=headers, json={"approve": True})
    assert r.status_code == 403
    r = await client.post(f"/api/approvals/{aid}/decide", headers=headers,
                          json={"approve": True, "password": "Senha-Forte-2026"})
    assert r.status_code == 200 and r.json()["status"] == "approved"


async def test_non_human_cannot_decide_approvals(app_env):
    from ultron.governance.approvals import ApprovalError, decide, request_approval

    async with session_scope() as s:
        ap = await request_approval(s, kind="publication", target_type="proposal", target_id="p1", risk="low",
                                    title="x")
        with pytest.raises(ApprovalError):
            await decide(s, ap.id, approve=True, decided_by="agent:developer", human=False)
