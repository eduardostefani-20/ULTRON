"""EVALUATION ENGINE (CÓDIGO DE GOVERNANÇA) — avaliação independente de cada mudança.

O agente desenvolvedor NUNCA aprova o próprio trabalho: a decisão vem de portões objetivos
(diff real, compilação, lint, testes base × candidato, desempenho, segurança) e de um
Auditor Agent executado preferencialmente em outro provedor de IA.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
from pathlib import Path

from sqlalchemy import select

from ultron.config import REPO_ROOT
from ultron.db import session_scope
from ultron.evolution import sandbox
from ultron.evolution.codeintel import SECURITY_RULES
from ultron.evolution.workspace import get_workspace
from ultron.governance import audit
from ultron.governance.policy import assess_changes
from ultron.llm.budget import BudgetContext
from ultron.llm.service import ChatMessage, TaskProfile, available_choices, complete_json
from ultron.models import Evaluation, Proposal, SandboxRun
from ultron.utils import truncate

log = logging.getLogger("ultron.evaluation")

AUDIT_PROMPT = """Você é o Auditor Agent do ULTRON: revisor técnico e de segurança INDEPENDENTE. Avalie o diff abaixo,
produzido por outro agente, contra a proposta e os critérios de aceitação. Procure: bugs, regressões, testes fracos ou
que não testam nada, mudanças fora do escopo, riscos de segurança, violação de governança e efeitos colaterais.
Aprove somente se a mudança é correta, segura, testada e atende aos critérios.

Responda em JSON:
{"approve": true|false, "summary": "parecer curto", "issues": ["problemas concretos"],
 "security_concerns": ["..."], "criteria": [{"criterion": "...", "met": true|false, "evidence": "..."}]}"""


async def _baseline(ws, base_sha: str) -> dict:
    label = f"baseline:{base_sha[:12]}"
    async with session_scope() as s:
        row = (await s.execute(select(SandboxRun).where(SandboxRun.label == label, SandboxRun.status != "running")
                               .order_by(SandboxRun.created_at.desc()).limit(1))).scalar_one_or_none()
        if row is not None and row.parsed and "tests" in row.parsed:
            return {**row.parsed, "cached": True}
    return await sandbox.run_test_suite(ws, ref=base_sha, label=label)


async def test_candidate(proposal_id: str) -> dict:
    """Fase TESTE: executa a suíte no estado original e no candidato, ambos no sandbox."""
    async with session_scope() as s:
        p = await s.get(Proposal, proposal_id)
        branch, base_sha, code = p.branch, p.base_sha, p.code
    ws = await get_workspace()
    baseline = await _baseline(ws, base_sha)
    candidate = await sandbox.run_test_suite(ws, ref=branch, label=f"candidate:{code}", proposal_id=proposal_id)
    async with session_scope() as s:
        p = await s.get(Proposal, proposal_id)
        p.payload = {**(p.payload or {}), "tests": {"baseline": baseline, "candidate": candidate}}
        p.status = "evaluating"
    return {"baseline": baseline, "candidate": candidate}


def _added_insecure(changes) -> list[str]:
    hits = []
    for ch in changes:
        if "/tests/" in ch.path or not ch.path.endswith((".py", ".ts", ".tsx", ".js")):
            continue
        for line in ch.added_lines:
            for name, rx in SECURITY_RULES:
                if rx.search(line) and "noqa" not in line:
                    hits.append(f"{ch.path}: {name}")
    return hits


async def _frontend_check(ws, branch: str, changes) -> dict:
    if not any(c.path.startswith("frontend/") for c in changes):
        return {"needed": False}
    nm = REPO_ROOT / "frontend" / "node_modules"
    npx = shutil.which("npx")
    if not nm.exists() or not npx:
        return {"needed": True, "ran": False, "ok": False,
                "detail": "toolchain do frontend indisponível neste servidor — validação exigida via CI do GitHub"}
    wt = await ws.detached_worktree(branch, f"sbx-fe-{branch[-20:]}")
    try:
        os.symlink(nm, wt / "frontend" / "node_modules")
        r = await sandbox.run([npx, "tsc", "--noEmit", "-p", "."], wt / "frontend", timeout=300, label="frontend:tsc",
                              mem_mb=2048)
        sandbox.cleanup(r)
        return {"needed": True, "ran": True, "ok": r["exit_code"] == 0,
                "detail": truncate(r["stdout"] + r["stderr"], 3000), "isolation": r["isolation"]}
    finally:
        await ws.remove_worktree(wt)


async def finalize(proposal_id: str, cycle_id: str = "") -> Evaluation:
    """Fase AUDITORIA: portões objetivos + auditor independente → veredito."""
    async with session_scope() as s:
        p = await s.get(Proposal, proposal_id)
        snap = {k: getattr(p, k) for k in ("code", "title", "kind", "strategy", "branch", "base_sha", "tree_sha",
                                            "acceptance_criteria", "solution", "objective", "payload", "declared_risk")}
    ws = await get_workspace()
    gates: list[dict] = []

    def gate(name: str, passed: bool, detail: str = "", hard: bool = True) -> None:
        gates.append({"name": name, "passed": bool(passed), "detail": truncate(detail, 2000), "hard": hard})

    current_tree = await ws.tree(snap["branch"])
    gate("integridade", current_tree == snap["tree_sha"], "branch inalterada desde o desenvolvimento"
         if current_tree == snap["tree_sha"] else "a branch mudou após o desenvolvimento")
    changes = await ws.diff_changes(snap["base_sha"], snap["branch"])
    assessment = assess_changes(changes)
    gate("política de governança", not assessment.blocked, "; ".join(assessment.blocked_reasons) or "nenhum bloqueio")
    if snap["declared_risk"] and snap["declared_risk"] != assessment.level.value:
        gate("risco declarado × calculado", True, f"declarado {snap['declared_risk']}, calculado "
                                                   f"{assessment.level.value} (vale o calculado)", hard=False)

    # compilação e lint dos arquivos Python alterados
    wt = await ws.detached_worktree(snap["branch"], f"sbx-eval-{snap['code']}")
    try:
        py = [c.path for c in changes if c.path.endswith(".py") and c.status != "D" and (wt / c.path).exists()]
        if py:
            r = await sandbox.run([sys.executable, "-m", "py_compile", *py], wt, timeout=120, label="eval:compile",
                                  proposal_id=proposal_id)
            sandbox.cleanup(r)
            gate("compilação", r["exit_code"] == 0, truncate(r["stderr"], 1500) or "ok")
            ruff = shutil.which("ruff") or (str(Path(sys.executable).parent / "ruff")
                                            if (Path(sys.executable).parent / "ruff").exists() else None)
            if ruff:
                r = await sandbox.run([ruff, "check", "--select", "F,E9", "--no-cache", *py], wt, timeout=120,
                                      label="eval:lint", proposal_id=proposal_id)
                sandbox.cleanup(r)
                gate("lint (erros)", r["exit_code"] == 0, truncate(r["stdout"], 1500) or "ok")
            else:
                gate("lint (erros)", True, "ruff indisponível — ignorado", hard=False)
        else:
            gate("compilação", True, "nenhum arquivo Python alterado", hard=False)
    finally:
        await ws.remove_worktree(wt)

    tests = (snap["payload"] or {}).get("tests") or {}
    base, cand = tests.get("baseline") or {}, tests.get("candidate") or {}
    if not cand:
        gate("testes do candidato", False, "testes do candidato não executados")
    else:
        base_failed = set(base.get("failed_ids") or [])
        new_failures = [t for t in cand.get("failed_ids") or [] if t not in base_failed]
        if base_failed:
            gate("testes do candidato", not new_failures and not cand.get("timed_out"),
                 f"falhas novas: {new_failures[:10]}" if new_failures else "nenhuma falha nova (base já tinha falhas)")
        else:
            ok = cand.get("failed", 1) == 0 and cand.get("errors", 1) == 0 and not cand.get("timed_out")
            gate("testes do candidato", ok, f"{cand.get('passed')} passaram, {cand.get('failed')} falharam, "
                                            f"{cand.get('errors')} erros")
        gate("sem perda de testes", cand.get("passed", 0) >= base.get("passed", 0),
             f"base {base.get('passed', 0)} × candidato {cand.get('passed', 0)} testes passando")
        if snap["kind"] == "test":
            gate("testes adicionados", cand.get("tests", 0) > base.get("tests", 0),
                 f"base {base.get('tests', 0)} × candidato {cand.get('tests', 0)} testes")
        bt, ct = float(base.get("time_s") or 0), float(cand.get("time_s") or 0)
        gate("desempenho dos testes", ct <= bt * 2 + 30, f"base {bt:.1f}s × candidato {ct:.1f}s")
        iso = (cand.get("isolation") or {}).get("network")
        gate("isolamento de rede do sandbox", iso == "isolated", f"rede: {iso}", hard=False)

    insecure = _added_insecure(changes)
    gate("varredura de segurança", not insecure, "; ".join(insecure[:10]) or "nenhum padrão inseguro adicionado")
    fe = await _frontend_check(ws, snap["branch"], changes)
    if fe.get("needed"):
        gate("verificação do frontend", fe.get("ok", False), fe.get("detail", ""), hard=fe.get("ran", False))

    # auditor independente
    audit_result: dict = {"available": False}
    if snap["strategy"] == "deterministic":
        audit_result = {"available": False, "approve": True, "summary": "mudança determinística (sem IA) — "
                        "verificada apenas pelos portões automáticos", "deterministic": True}
    else:
        diff = await ws.diff_text(snap["base_sha"], snap["branch"], max_chars=30000)
        dev_providers = {m.split(":")[0] for m in (snap["payload"] or {}).get("dev_models", [])}
        try:
            async with session_scope() as s:
                choices = await available_choices(s, TaskProfile(task="critique", tier="balanced"))
            alt = [c for c in choices if c.provider not in dev_providers] or choices
            data, res = await complete_json(
                [ChatMessage("system", AUDIT_PROMPT),
                 ChatMessage("user", f"PROPOSTA {snap['code']}: {snap['title']}\nObjetivo: {snap['objective']}\n"
                                     f"Solução: {snap['solution']}\nCritérios: {snap['acceptance_criteria']}\n\n"
                                     f"RESULTADO DOS TESTES: {truncate(str({k: cand.get(k) for k in ('passed', 'failed', 'errors', 'tests')}), 400)}\n\n"
                                     f"DIFF:\n{diff}")],
                TaskProfile(task="critique", tier="balanced"),
                ctx=BudgetContext(purpose="evolution.audit", agent_id="auditor", cycle_id=cycle_id),
                max_tokens=2000, choices=alt)
            audit_result = data if isinstance(data, dict) else {"approve": False, "summary": str(data)}
            audit_result["available"] = True
            audit_result["model"] = f"{res.provider}:{res.model}"
            audit_result["independent_provider"] = res.provider not in dev_providers
            audit_result["cost_usd"] = res.cost_usd
        except Exception as e:
            audit_result = {"available": False, "approve": False, "summary": f"auditor indisponível: {e}"}
        if audit_result.get("available"):
            gate("auditor independente", bool(audit_result.get("approve")), audit_result.get("summary", ""))
            unmet = [c for c in audit_result.get("criteria", []) if isinstance(c, dict) and c.get("met") is False]
            gate("critérios de aceitação", not unmet, "; ".join(str(c.get("criterion")) for c in unmet) or
                 "todos atendidos segundo o auditor")
        else:
            gate("auditor independente", False, audit_result.get("summary", "indisponível") +
                 " — exige revisão humana", hard=False)

    verdict = "pass" if all(g["passed"] for g in gates if g["hard"]) else "fail"
    scores = {"risk": assessment.level.value, "risk_reasons": assessment.reasons, "lines": assessment.total_lines,
              "files": assessment.total_files, "baseline_passed": base.get("passed"), "candidate_passed": cand.get("passed"),
              "baseline_time_s": base.get("time_s"), "candidate_time_s": cand.get("time_s"),
              "requires_ci": bool(fe.get("needed") and not fe.get("ran")),
              "auditor_available": bool(audit_result.get("available")) or snap["strategy"] == "deterministic"}
    async with session_scope() as s:
        ev = Evaluation(proposal_id=proposal_id, verdict=verdict, gates=gates, baseline=base, candidate=cand,
                        audit=audit_result, scores=scores, risk_level=assessment.level.value)
        s.add(ev)
        p = await s.get(Proposal, proposal_id)
        p.risk_level = assessment.level.value
        p.risk_reasons = assessment.reasons
        p.cost_usd = (p.cost_usd or 0) + float(audit_result.get("cost_usd") or 0)
        p.status = "evaluated" if verdict == "pass" else "failed"
        if verdict == "fail":
            p.error = "reprovada na avaliação: " + "; ".join(g["name"] for g in gates if g["hard"] and not g["passed"])
        await s.flush()
        await audit.record("evaluation_engine", f"proposal.evaluated.{verdict}", p.code,
                           {"risk": assessment.level.value, "failed_gates": [g["name"] for g in gates
                                                                             if not g["passed"]]}, session=s)
        s.expunge(ev)
    return ev
