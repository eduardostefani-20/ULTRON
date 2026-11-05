"""Autoevolução de ponta a ponta sobre um repositório git real, com sandbox real."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select

from tests.conftest import FakeProvider, install_fake, system_of
from ultron.db import session_scope
from ultron.evolution import codeintel
from ultron.evolution.cycle import create_cycle, develop_now, run_cycle
from ultron.evolution.workspace import get_workspace, git
from ultron.models import Diagnostic, Evaluation, Proposal, Publication

PASSWORD = "Senha-Forte-2026"


def test_codeintel_maps_imports_cycles_and_renders_stable_doc(tmp_path):
    root = tmp_path
    (root / "backend" / "ultron").mkdir(parents=True)
    (root / "backend" / "ultron" / "a.py").write_text("from ultron import b\n\ndef fa():\n    return b.fb()\n")
    (root / "backend" / "ultron" / "b.py").write_text("from ultron import a\n\ndef fb():\n    if 1:\n        return 2\n")
    (root / "frontend" / "src" / "lib").mkdir(parents=True)
    (root / "frontend" / "src" / "lib" / "api.ts").write_text("export function call() { return 1 }\n")
    (root / "frontend" / "src" / "page.tsx").write_text("import { call } from '@/lib/api'\nexport default function P(){}\n")
    data = codeintel.analyze_repo(root)
    edges = {(e["from"], e["to"]) for e in data["edges"]}
    assert ("backend/ultron/a.py", "backend/ultron/b.py") in edges
    assert ("frontend/src/page.tsx", "frontend/src/lib/api.ts") in edges
    assert any(f["kind"] == "import_cycle" for f in data["findings"])
    assert codeintel.render_architecture_doc(data) == codeintel.render_architecture_doc(codeintel.analyze_repo(root))


async def _approve_publication(client, headers, proposal_id):
    aps = (await client.get("/api/approvals", headers=headers)).json()
    ap = next(a for a in aps if a["target_id"] == proposal_id)
    r = await client.post(f"/api/approvals/{ap['id']}/decide", headers=headers,
                          json={"approve": True, "password": PASSWORD})
    assert r.status_code == 200, r.text
    from ultron.api.evolution import _bg

    for t in list(_bg):
        await t


async def test_full_cycle_deterministic_docs_approval_publish_and_rollback(app_env, client, headers):
    """Sem provedor de IA: o ciclo diagnostica a documentação desatualizada, desenvolve a correção
    numa branch, testa no sandbox, avalia, pede aprovação, publica e permite rollback."""
    cid = await create_cycle("manual")
    res = await run_cycle(cid)
    assert res["status"] == "completed", res
    async with session_scope() as s:
        diags = (await s.execute(select(Diagnostic))).scalars().all()
        sigs = {d.signature for d in diags}
        assert "cap.no_llm" in sigs and "docs.architecture_stale" in sigs
        p = (await s.execute(select(Proposal).where(Proposal.kind == "docs"))).scalars().one()
        ev = (await s.execute(select(Evaluation).where(Evaluation.proposal_id == p.id))).scalars().one()
    assert ev.verdict == "pass", ev.gates
    assert ev.risk_level == "low"
    assert ev.baseline["passed"] == 2 and ev.candidate["passed"] == 2
    assert p.status == "awaiting_approval"  # publicação automática começa DESABILITADA

    status = (await client.get("/api/evolution/status", headers=headers)).json()
    assert status["last_cycle"]["status"] == "completed"
    assert status["pending_approvals"] >= 1

    await _approve_publication(client, headers, p.id)
    ws = await get_workspace()
    assert (ws.root / "docs" / "ARQUITETURA_GERADA.md").exists()
    async with session_scope() as s:
        pub = (await s.execute(select(Publication))).scalars().one()
        assert pub.mode == "approved" and pub.status == "published" and pub.base_sha_before == p.base_sha

    r = await client.post(f"/api/evolution/publications/{pub.id}/rollback", headers=headers,
                          json={"reason": "teste de rollback"})
    assert r.status_code == 200, r.text
    assert not (ws.root / "docs" / "ARQUITETURA_GERADA.md").exists()
    log = (await git("log", "--oneline", "-3", cwd=ws.root)).out
    assert "Rollback" in log  # histórico preservado (revert, não reset)

    audit = (await client.get("/api/audit", headers=headers, params={"action": "proposal."})).json()
    actions = {a["action"] for a in audit}
    assert {"proposal.created", "proposal.developed", "proposal.evaluated.pass", "proposal.published",
            "proposal.rolled_back"} <= actions


def _dev_responder(edits):
    def responder(req):
        sysmsg = system_of(req)
        if "Developer Agent" in sysmsg:
            return json.dumps({"summary": "implementação", "edits": edits, "tests_added": ["backend/tests/test_mult.py"]})
        if "Auditor Agent" in sysmsg:
            return json.dumps({"approve": True, "summary": "correto e testado", "issues": [],
                               "criteria": [{"criterion": "multiplica funciona", "met": True, "evidence": "teste"}]})
        return json.dumps({"thought": "x", "final": "ok"})
    return responder


async def _new_proposal(client, headers, title="Adicionar função multiplica"):
    r = await client.post("/api/evolution/proposals", headers=headers, json={
        "title": title, "problem": "falta multiplicação", "solution": "criar multiplica(a, b)",
        "affected_files": ["backend/app/calc.py"], "acceptance_criteria": ["multiplica funciona"], "kind": "code"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


async def test_llm_developer_change_is_tested_audited_and_waits_for_approval(app_env, client, headers):
    edits = [
        {"path": "backend/app/calc.py", "action": "replace", "find": "def soma(a, b):\n    return a + b",
         "replace": "def soma(a, b):\n    return a + b\n\n\ndef multiplica(a, b):\n    return a * b"},
        {"path": "backend/tests/test_mult.py", "action": "write",
         "content": "from app.calc import multiplica\n\n\ndef test_multiplica():\n    assert multiplica(3, 4) == 12\n"},
    ]
    install_fake(FakeProvider("dev", _dev_responder(edits)), FakeProvider("aud", _dev_responder(edits)))
    pid = await _new_proposal(client, headers)
    out = await develop_now(pid)
    assert out["verdict"] == "pass", out
    detail = (await client.get(f"/api/evolution/proposals/{pid}", headers=headers)).json()
    assert detail["status"] == "awaiting_approval"
    assert detail["risk_level"] == "medium"  # código fora de docs/UI/testes → médio
    ev = detail["evaluations"][0]
    assert ev["candidate"]["passed"] == 3 and ev["baseline"]["passed"] == 2
    assert ev["audit"]["approve"] is True
    diff = (await client.get(f"/api/workspace/diff/{pid}", headers=headers)).json()["diff"]
    assert "def multiplica" in diff


async def test_developer_cannot_touch_governance(app_env, client, headers):
    edits = [{"path": "backend/ultron/governance/policy.py", "action": "write", "content": "ALLOW_ALL = True"},
             {"path": ".github/workflows/x.yml", "action": "write", "content": "on: push"},
             {"path": "../../fora.txt", "action": "write", "content": "x"}]
    install_fake(FakeProvider("dev", _dev_responder(edits)))
    pid = await _new_proposal(client, headers, "Tentativa maliciosa de alterar governança")
    out = await develop_now(pid)
    assert out["status"] == "failed" and "nenhuma alteração" in out["error"]
    async with session_scope() as s:
        p = await s.get(Proposal, pid)
    rejected = [r for step in p.dev_log for r in step.get("rejected", [])]
    assert len(rejected) >= 3 * 1 and all("protegido" in r["reason"] or "inseguro" in r["reason"] for r in rejected)


async def test_evaluation_rejects_change_that_breaks_tests(app_env, client, headers):
    edits = [{"path": "backend/app/calc.py", "action": "replace", "find": "return a + b", "replace": "return a - b"}]
    install_fake(FakeProvider("dev", _dev_responder(edits)))
    pid = await _new_proposal(client, headers, "Mudança que quebra a soma")
    out = await develop_now(pid)
    assert out["verdict"] == "fail"
    async with session_scope() as s:
        ev = (await s.execute(select(Evaluation).where(Evaluation.proposal_id == pid))).scalars().one()
        p = await s.get(Proposal, pid)
    failed = {g["name"] for g in ev.gates if not g["passed"] and g["hard"]}
    assert "testes do candidato" in failed and p.status == "failed"


async def test_selftest_then_low_risk_auto_publish(app_env, client, headers):
    r = await client.post("/api/evolution/selftest", headers=headers)
    assert r.status_code == 200
    st = r.json()
    from ultron.evolution import sandbox

    if not (sandbox.capabilities()["unshare_net"] and sandbox.drops_privileges()):
        # sem rede isolada ou sem usuário separado o autoteste DEVE falhar e manter a publicação automática bloqueada
        assert not st["passed"]
        r = await client.post("/api/evolution/autopublish", headers=headers, json={"enabled": True, "password": PASSWORD})
        assert r.status_code == 400
        return
    assert st["passed"], [c for c in st["checks"] if not c["passed"]]
    r = await client.post("/api/evolution/autopublish", headers=headers, json={"enabled": True, "password": PASSWORD})
    assert r.status_code == 200, r.text
    cid = await create_cycle("manual")
    assert (await run_cycle(cid))["status"] == "completed"
    async with session_scope() as s:
        p = (await s.execute(select(Proposal).where(Proposal.kind == "docs"))).scalars().one()
        pub = (await s.execute(select(Publication))).scalars().one()
    assert p.status == "published" and pub.mode == "auto" and pub.risk_level == "low"
    ws = await get_workspace()
    assert Path(ws.root / "docs" / "ARQUITETURA_GERADA.md").exists()


async def test_pause_blocks_new_cycles(app_env, client, headers):
    assert (await client.post("/api/evolution/pause", headers=headers)).json()["paused"] is True
    cid = await create_cycle("manual")
    res = await run_cycle(cid)
    assert res["status"] == "stopped" and "pausada" in res["reason"]
    assert (await client.post("/api/evolution/resume", headers=headers)).json()["paused"] is False
    res = await run_cycle(cid)  # retoma o ciclo interrompido
    assert res["status"] == "completed"


async def test_lost_branch_after_restart_requeues_instead_of_crashing(app_env, client, headers):
    """Regressão: workspace recriado (ex.: deploy em disco efêmero) não pode travar a publicação."""
    cid = await create_cycle("manual")
    assert (await run_cycle(cid))["status"] == "completed"
    async with session_scope() as s:
        p = (await s.execute(select(Proposal).where(Proposal.kind == "docs"))).scalars().one()
        pid, branch = p.id, p.branch
    ws = await get_workspace()
    await git("branch", "-D", branch, cwd=ws.root)  # simula a perda da branch
    await _approve_publication(client, headers, pid)
    detail = (await client.get(f"/api/evolution/proposals/{pid}", headers=headers)).json()
    assert detail["status"] == "queued" and "redesenvolvida" in detail["error"]
    async with session_scope() as s:
        assert (await s.execute(select(Publication))).scalars().first() is None


async def test_old_approval_does_not_authorize_new_code(app_env, client, headers):
    """Segurança: aprovar a versão A de uma proposta não autoriza publicar uma versão B diferente."""
    from ultron.evolution.publisher import PublishError, publish

    cid = await create_cycle("manual")
    assert (await run_cycle(cid))["status"] == "completed"
    async with session_scope() as s:
        p = (await s.execute(select(Proposal).where(Proposal.kind == "docs"))).scalars().one()
        pid = p.id
        from ultron.governance.approvals import decide
        from ultron.models import Approval

        ap = (await s.execute(select(Approval).where(Approval.target_id == pid))).scalars().one()
        await decide(s, ap.id, approve=True, decided_by="user:x", human=True)
        p.tree_sha = "0" * 40  # outra versão do código
    import pytest

    with pytest.raises(PublishError, match="versão exata"):
        await publish(pid, mode="approved", approved_by="user:x")


async def test_approved_but_unpublished_is_retried(app_env, client, headers):
    """Aprovação que chegou antes de a publicação ser possível é publicada na próxima tentativa."""
    from ultron.evolution.publisher import retry_approved
    from ultron.governance.approvals import decide
    from ultron.models import Approval

    cid = await create_cycle("manual")
    assert (await run_cycle(cid))["status"] == "completed"
    async with session_scope() as s:
        p = (await s.execute(select(Proposal).where(Proposal.kind == "docs"))).scalars().one()
        ap = (await s.execute(select(Approval).where(Approval.target_id == p.id))).scalars().one()
        await decide(s, ap.id, approve=True, decided_by="user:x", human=True)
        p.status = "evaluated"  # simula publicação que falhou (ex.: CI ainda rodando)
    out = await retry_approved()
    assert out and out[0]["status"] == "published"
    r = await client.post(f"/api/evolution/proposals/{p.id}/publish", headers=headers)
    assert r.status_code == 400 and "já publicada" in r.text


async def test_github_runner_mode_skips_local_cycles_and_runner_executes_cycle(app_env, monkeypatch):
    """Modo 'github': o servidor não roda ciclos; o executor (GitHub Actions) roda e grava no mesmo banco."""
    from ultron.config import reset_settings_cache
    from ultron.evolution.runner import run_cycle_once
    from ultron.evolution.scheduler import Scheduler
    from ultron.models import EvolutionCycle

    monkeypatch.setenv("ULTRON_EVOLUTION_RUNNER", "github")
    reset_settings_cache()
    sched = Scheduler()
    started = await sched.tick()
    assert not any(s.startswith("evolution_cycle") for s in started)
    import pytest

    with pytest.raises(RuntimeError, match="GitHub"):
        await sched.run_now()  # sem token: explica o que falta
    for t in list(sched._jobs.values()):
        await t
    res = await run_cycle_once()
    assert res["status"] == "completed", res
    async with session_scope() as s:
        c = (await s.execute(select(EvolutionCycle))).scalars().one()
    assert c.trigger == "github-actions" and c.status == "completed"
    monkeypatch.delenv("ULTRON_EVOLUTION_RUNNER")
    reset_settings_cache()
