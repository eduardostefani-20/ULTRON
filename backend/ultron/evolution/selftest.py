"""Autoteste de segurança (CÓDIGO DE GOVERNANÇA).

Tenta DEMONSTRAR FALHAS nos próprios controles. A publicação automática de baixo risco só
pode ser ativada se todos os testes passarem; uma falha posterior a desativa.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from ultron.db import session_scope
from ultron.evolution import sandbox
from ultron.evolution.guard import apply_edits
from ultron.evolution.workspace import get_workspace
from ultron.governance import audit
from ultron.governance.audit import verify_chain
from ultron.governance.permissions import authorize_tool, validate_new_agent
from ultron.governance.policy import FileChange, assess_changes, check_agent_write
from ultron.tools.netguard import BlockedURL, validate_url
from ultron.utils import utcnow


async def run_selftest(actor: str) -> dict:
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "passed": bool(ok), "detail": detail[:500]})

    # 1. política: diff que toca governança é bloqueado
    a = assess_changes([FileChange("backend/ultron/governance/policy.py", "M", ["ALLOW_ALL = True"])])
    check("diff em governança é bloqueado", a.blocked, "; ".join(a.blocked_reasons))
    a = assess_changes([FileChange("docs/x.md", "A", ["token = 'ghp_" + "a" * 36 + "'"])])
    check("segredo em diff é bloqueado", a.blocked)
    a = assess_changes([FileChange("frontend/src/components/X.tsx", "A", ["eval(userInput)"])])
    check("código perigoso eleva o risco", a.level.value == "high")
    # 2. caminhos
    for bad in ("../etc/passwd", "/etc/passwd", "backend/ultron/security/vault.py", ".github/workflows/ci.yml",
                "backend/tests/security/test_x.py", "backend/.env", "a/../../x"):
        check(f"escrita negada: {bad}", not check_agent_write(bad).allowed)
    # 3. guardião: link simbólico para fora do workspace
    with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as outside:
        root = Path(td)
        (root / "docs").mkdir()
        os.symlink(outside, root / "docs" / "fora")
        applied, rejected = apply_edits(root, [{"path": "docs/fora/x.md", "action": "write", "content": "x"}])
        check("guardião bloqueia escape por symlink", not applied and not any(Path(outside).iterdir()))
        applied, _ = apply_edits(root, [{"path": "backend/ultron/governance/policy.py", "action": "write",
                                         "content": "x"}])
        check("guardião bloqueia escrita em governança", not applied)
    # 4. permissões
    check("ferramenta de publicação negada a agentes",
          not authorize_tool("x", "publish", ["x"], ["publish"], ["publish"]).allowed)
    check("escopo não concedido é negado",
          not authorize_tool("web_search", "external_access", ["web_search"], ["external_access"],
                             ["read_analyze"]).allowed)
    d = validate_new_agent(requested_scopes=["read_analyze", "develop_sandbox"], requested_tools=["read_file"],
                           creator_scopes=["read_analyze"], creator_tools=["read_file"], generation=1, budget_usd=0.05,
                           max_steps=4, existing_dynamic=0, purpose="agente de teste para verificar escalonamento")
    check("agente não cria agente com mais privilégios", not d.allowed, d.reason)
    d = validate_new_agent(requested_scopes=["read_analyze"], requested_tools=["read_file"],
                           creator_scopes=["read_analyze"], creator_tools=["read_file"], generation=2, budget_usd=0.05,
                           max_steps=4, existing_dynamic=0, purpose="agente de segunda geração para testar limite")
    check("limite de geração de agentes", not d.allowed, d.reason)
    # 5. rede (SSRF)
    for url in ("http://169.254.169.254/latest/meta-data", "http://127.0.0.1:8000/api", "file:///etc/passwd",
                "http://10.0.0.1/", "http://[::1]/", "http://user:pw@example.com/"):
        try:
            await validate_url(url)
            check(f"SSRF bloqueado: {url}", False)
        except BlockedURL:
            check(f"SSRF bloqueado: {url}", True)
    # 6. auditoria íntegra e configurações protegidas
    async with session_scope() as s:
        chain = await verify_chain(s)
        check("cadeia de auditoria íntegra", chain["valid"], chain["message"])
        from ultron.settings_store import SettingPermissionError, set_setting

        try:
            async with s.begin_nested():
                await set_setting(s, "publication.auto_publish_low_risk", True, actor="agent:x",
                                  actor_is_human_owner=False)
            check("agente não altera publicação automática", False)
        except SettingPermissionError:
            check("agente não altera publicação automática", True)
    # 7. sandbox: ambiente limpo e rede isolada
    with tempfile.TemporaryDirectory() as td:
        r = await sandbox.run([sys.executable, "-c", "import os,json;print(json.dumps(sorted(os.environ)))"],
                              Path(td), timeout=60, extra_env={"FAKE_API_KEY": "sk-should-not-pass",
                                                               "SAFE_VAR": "1"}, label="selftest:env", record=True)
        sandbox.cleanup(r)
        leaked = [k for k in r["stdout"].split('"') if any(x in k.upper() for x in ("KEY", "TOKEN", "SECRET",
                                                                                   "PASSWORD", "DATABASE_URL"))]
        check("sandbox não recebe segredos", r["exit_code"] == 0 and not leaked, f"vazou: {leaked}" if leaked else "ok")
        r = await sandbox.run([sys.executable, "-c", "import socket;socket.create_connection(('1.1.1.1',443),timeout=3)"
                               ";print('CONECTOU')"], Path(td), timeout=30, label="selftest:net", record=True)
        sandbox.cleanup(r)
        isolated = r["isolation"]["network"] == "isolated"
        check("sandbox sem acesso à rede", isolated and "CONECTOU" not in r["stdout"],
              f"isolamento: {r['isolation']['network']}")
        from ultron.config import get_settings

        secret_file = get_settings().data_dir / ".selftest-private"
        secret_file.parent.mkdir(parents=True, exist_ok=True)
        secret_file.write_text("conteudo-privado-do-servidor")
        os.chmod(secret_file, 0o600)
        r = await sandbox.run([sys.executable, "-c", f"print(open({str(secret_file)!r}).read())"], Path(td), timeout=30,
                              label="selftest:files", record=True)
        sandbox.cleanup(r)
        secret_file.unlink(missing_ok=True)
        check("sandbox não lê arquivos privados do servidor", "conteudo-privado" not in r["stdout"],
              f"usuário do sandbox: {r['isolation'].get('user')}")
        env_path = f"/proc/{os.getpid()}/environ"
        code = (f"import sys\ntry:\n    d = open({env_path!r}, 'rb').read()\n    print('LEU', len(d))\n"
                "except Exception as e:\n    print('NEGADO', type(e).__name__)")
        r = await sandbox.run([sys.executable, "-c", code], Path(td), timeout=30, label="selftest:environ", record=True)
        sandbox.cleanup(r)
        check("sandbox não lê o ambiente do servidor (chaves e banco)", "NEGADO" in r["stdout"],
              r["stdout"].strip()[:80])
    # 8. suíte de testes de segurança executada no sandbox, sobre o branch estável
    try:
        ws = await get_workspace()
        res = await sandbox.run_test_suite(ws, test_path="tests/security", label="selftest:security")
        check("suíte de testes de segurança", res["tests"] > 0 and res["failed"] == 0 and res["errors"] == 0,
              f"{res['passed']} passaram, {res['failed']} falharam, {res['errors']} erros")
    except Exception as e:
        check("suíte de testes de segurança", False, f"não executada: {e}")

    passed = all(c["passed"] for c in checks)
    details = {"checks": checks, "isolation": sandbox.isolation_level(), "capabilities": sandbox.capabilities()}
    async with session_scope() as s:
        from ultron.settings_store import record_selftest

        await record_selftest(s, passed, utcnow().isoformat() + "Z", details)
        await audit.record(actor, "security.selftest", "publication", {"passed": passed,
                                                                       "failed": [c["name"] for c in checks
                                                                                  if not c["passed"]]}, session=s)
    return {"passed": passed, **details}
