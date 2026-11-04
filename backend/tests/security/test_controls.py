"""Testes que TENTAM QUEBRAR os controles de segurança do ULTRON."""

from __future__ import annotations

import os

import httpx
import pytest

from ultron.evolution.guard import apply_edits
from ultron.governance.permissions import authorize_tool, sanitize_granted_scopes, validate_new_agent
from ultron.governance.policy import FileChange, Risk, assess_changes, check_agent_write, path_risk
from ultron.tools.netguard import BlockedURL, safe_get, validate_url

# ------------------------------------------------------------------ política de caminhos

@pytest.mark.parametrize("path", [
    "backend/ultron/governance/policy.py", "backend/ultron/governance/novo.py", "backend/ultron/security/vault.py",
    "backend/ultron/evolution/sandbox.py", "backend/ultron/evolution/evaluation.py", "backend/ultron/evolution/guard.py",
    "backend/ultron/evolution/publisher.py", "backend/ultron/evolution/selftest.py", "backend/ultron/settings_store.py",
    "backend/ultron/llm/budget.py", "backend/ultron/tools/netguard.py", "backend/tests/security/test_controls.py",
    ".github/workflows/ci.yml", "deploy/oracle/update.sh", "deploy/oracle/cloud-init.sh", "CODEOWNERS", ".env", "backend/.env", "frontend/.env.local", ".git/config",
    "../fora.py", "/etc/passwd", "backend/../../x", "a\\b.py", "x\x00.py", "backend/data/ultron.db",
    "frontend/public/logo.png",
])
def test_agent_cannot_write_protected_or_unsafe_paths(path):
    assert not check_agent_write(path).allowed


@pytest.mark.parametrize("path,status,expected", [
    ("docs/guia.md", "A", Risk.LOW),
    ("frontend/src/components/Card.tsx", "M", Risk.LOW),
    ("backend/tests/test_novo.py", "A", Risk.LOW),
    ("backend/tests/test_existente.py", "M", Risk.MEDIUM),  # alterar teste existente não é baixo risco
    ("docs/velho.md", "D", Risk.MEDIUM),
    ("backend/ultron/agents/runtime.py", "M", Risk.MEDIUM),
    ("backend/ultron/api/auth.py", "M", Risk.HIGH),
    ("backend/pyproject.toml", "M", Risk.HIGH),
    ("backend/alembic/versions/0002_x.py", "A", Risk.HIGH),
    ("Dockerfile", "M", Risk.HIGH),
    ("frontend/package.json", "M", Risk.HIGH),
])
def test_risk_classification(path, status, expected):
    assert path_risk(path, status) == expected


def test_diff_touching_governance_is_blocked_even_if_small():
    a = assess_changes([FileChange("backend/ultron/governance/policy.py", "M", ["x = 1"])])
    assert a.blocked


def test_rename_out_of_protected_path_is_blocked():
    a = assess_changes([FileChange("docs/policy.py", "R", ["x"], old_path="backend/ultron/governance/policy.py")])
    assert a.blocked


def test_secret_in_diff_is_blocked():
    a = assess_changes([FileChange("docs/nota.md", "A", ["chave: sk-ant-" + "x" * 40])])
    assert a.blocked


@pytest.mark.parametrize("line", ["import subprocess", "eval(x)", "os.system('ls')", "requests.get(u, verify=False)",
                                  "os.environ['X']", "pickle.loads(b)", "shutil.rmtree('/')"])
def test_dangerous_code_in_low_risk_area_becomes_high(line):
    a = assess_changes([FileChange("frontend/src/components/X.tsx" if "os." not in line else "backend/tests/test_x.py",
                                   "A", [line])])
    assert a.level == Risk.HIGH


def test_large_change_is_not_low_risk():
    a = assess_changes([FileChange(f"docs/d{i}.md", "A", ["linha"] * 50) for i in range(12)])
    assert a.level != Risk.LOW


def test_empty_diff_is_blocked():
    assert assess_changes([]).blocked


# ------------------------------------------------------------------ guardião de escrita

def test_guard_rejects_symlink_escape(tmp_path):
    root = tmp_path / "wt"
    outside = tmp_path / "fora"
    (root / "docs").mkdir(parents=True)
    outside.mkdir()
    os.symlink(outside, root / "docs" / "link")
    applied, rejected = apply_edits(root, [{"path": "docs/link/pwn.md", "action": "write", "content": "x"}])
    assert not applied and rejected
    assert not any(outside.iterdir())


def test_guard_rejects_overwriting_symlinked_file(tmp_path):
    root = tmp_path / "wt"
    (root / "docs").mkdir(parents=True)
    target = tmp_path / "segredo.txt"
    target.write_text("original")
    os.symlink(target, root / "docs" / "a.md")
    applied, _ = apply_edits(root, [{"path": "docs/a.md", "action": "write", "content": "hack"}])
    assert not applied and target.read_text() == "original"


def test_guard_blocks_governance_and_traversal(tmp_path):
    root = tmp_path / "wt"
    root.mkdir()
    edits = [{"path": "backend/ultron/governance/policy.py", "action": "write", "content": "ALLOW = True"},
             {"path": "../escape.py", "action": "write", "content": "x"},
             {"path": "backend/ultron/security/x.py", "action": "delete"}]
    applied, rejected = apply_edits(root, edits)
    assert applied == [] and len(rejected) == 3
    assert not (tmp_path / "escape.py").exists()


def test_guard_replace_requires_unique_match(tmp_path):
    root = tmp_path / "wt"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "a.md").write_text("x\nx\n")
    applied, rejected = apply_edits(root, [{"path": "docs/a.md", "action": "replace", "find": "x", "replace": "y"}])
    assert not applied and "exatamente 1" in rejected[0]["reason"]


# ------------------------------------------------------------------ permissões

def test_publish_scope_never_usable_by_agents():
    assert not authorize_tool("publicar", "publish", ["publicar"], ["publish"], ["publish"]).allowed


def test_tool_requires_list_scope_and_grant():
    assert not authorize_tool("web_search", "external_access", [], ["external_access"], ["external_access"]).allowed
    assert not authorize_tool("web_search", "external_access", ["web_search"], [], ["external_access"]).allowed
    assert not authorize_tool("web_search", "external_access", ["web_search"], ["external_access"], []).allowed
    assert authorize_tool("web_search", "external_access", ["web_search"], ["external_access"],
                          ["external_access"]).allowed


def test_owner_cannot_grant_publish_to_autonomy():
    assert "publish" not in sanitize_granted_scopes(["publish", "read_analyze", "inventado"])


@pytest.mark.parametrize("kwargs,reason", [
    ({"requested_scopes": ["read_analyze", "external_access"]}, "privilégios"),
    ({"requested_tools": ["read_file", "run_tests"]}, "ferramentas"),
    ({"requested_scopes": ["publish"]}, "publicação"),
    ({"generation": 2}, "geração"),
    ({"existing_dynamic": 99}, "limite"),
    ({"budget_usd": 50.0}, "orçamento"),
    ({"purpose": "x"}, "finalidade"),
])
def test_agent_creation_cannot_escalate(kwargs, reason):
    base = dict(requested_scopes=["read_analyze"], requested_tools=["read_file"], creator_scopes=["read_analyze"],
                creator_tools=["read_file"], generation=1, budget_usd=0.05, max_steps=4, existing_dynamic=0,
                purpose="agente auxiliar para resumir documentos técnicos")
    base.update(kwargs)
    d = validate_new_agent(**base)
    assert not d.allowed and reason in d.reason


# ------------------------------------------------------------------ rede (SSRF)

@pytest.mark.parametrize("url", ["http://127.0.0.1/", "http://localhost:8000/api", "http://169.254.169.254/latest",
                                 "http://10.1.2.3/", "http://192.168.0.1/", "http://[::1]/", "http://0.0.0.0/",
                                 "file:///etc/passwd", "ftp://example.com/", "http://u:p@93.184.216.34/",
                                 "http://93.184.216.34:22/", "http://metadata.google.internal/", "http://100.64.0.1/",
                                 "http://[::ffff:127.0.0.1]/"])
async def test_ssrf_targets_blocked(url):
    with pytest.raises(BlockedURL):
        await validate_url(url)


async def test_redirect_to_internal_address_blocked():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://127.0.0.1:8000/api/settings"})

    with pytest.raises(BlockedURL):
        await safe_get("http://93.184.216.34/", transport=httpx.MockTransport(handler))


async def test_response_size_is_limited():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"a" * 50_000)

    r = await safe_get("http://93.184.216.34/", transport=httpx.MockTransport(handler), max_bytes=1000)
    assert r.truncated and len(r.content) <= 50_000
