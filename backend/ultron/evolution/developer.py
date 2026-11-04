"""Desenvolvimento autônomo: o Developer Agent transforma propostas aprovadas para
desenvolvimento em código real, numa branch isolada, com iterações guiadas por testes."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from ultron.db import session_scope
from ultron.evolution import codeintel, sandbox
from ultron.evolution.guard import apply_edits
from ultron.evolution.workspace import GitWorkspace, get_workspace
from ultron.governance import audit
from ultron.governance.policy import FORBIDDEN_PATHS
from ultron.llm.budget import BudgetContext, BudgetExceeded
from ultron.llm.service import ChatMessage, TaskProfile, complete_json
from ultron.models import Proposal
from ultron.utils import slugify, truncate, utcnow

log = logging.getLogger("ultron.developer")

DEV_PROMPT = """Você é o Developer Agent do ULTRON e vai implementar uma melhoria no PRÓPRIO código do ULTRON.
Stack: backend Python 3.11+/FastAPI/SQLAlchemy async (pacote backend/ultron, testes pytest em backend/tests com
asyncio_mode=auto e fixtures em backend/tests/conftest.py); frontend Next.js/React/TypeScript/Tailwind em frontend/src.

Regras obrigatórias:
- Faça a MENOR mudança que resolva o problema. Mantenha o estilo do código existente.
- NÃO altere caminhos protegidos (serão rejeitados): {forbidden}
- NÃO adicione dependências novas. Testes não podem usar rede.
- Inclua testes pytest para o comportamento novo/corrigido sempre que houver código Python.
- Use caminhos relativos à raiz do repositório (ex.: backend/ultron/memory/service.py).

Responda em JSON:
{{"summary": "o que foi feito", "edits": [
   {{"path": "arquivo existente", "action": "replace", "find": "trecho EXATO e ÚNICO do arquivo atual", "replace": "novo trecho"}},
   {{"path": "arquivo novo ou reescrito", "action": "write", "content": "conteúdo COMPLETO"}},
   {{"path": "arquivo", "action": "delete"}}],
 "tests_added": ["backend/tests/test_algo.py"], "notes": "limitações ou riscos"}}"""


def _related_tests(wt: Path, files: list[str]) -> list[str]:
    tests_dir = wt / "backend" / "tests"
    if not tests_dir.exists():
        return []
    mods = []
    for f in files:
        if f.startswith("backend/") and f.endswith(".py"):
            mods.append(f[len("backend/"):-3].replace("/", "."))
    out = []
    for t in sorted(tests_dir.rglob("test_*.py")):
        rel = t.relative_to(wt).as_posix()
        if rel.startswith("backend/tests/security/"):
            continue
        txt = t.read_text(errors="replace")
        if any(m in txt or m.split(".")[-1] in txt for m in mods):
            out.append(rel)
    return out[:6]


def _file_context(wt: Path, files: list[str], limit_files: int = 6, per_file: int = 10000) -> str:
    parts = []
    for f in files[:limit_files]:
        p = wt / f
        if p.is_file():
            text = p.read_text(errors="replace")
            parts.append(f"===== {f} ({len(text.splitlines())} linhas) =====\n{truncate(text, per_file)}")
        else:
            parts.append(f"===== {f} (NÃO EXISTE — crie se necessário) =====")
    return "\n\n".join(parts)


async def _quick_checks(ws: GitWorkspace, wt: Path, changed: list[str], tests: list[str], proposal_id: str) -> dict:
    py = [c for c in changed if c.endswith(".py") and (wt / c).exists()]
    result: dict = {"compile_ok": True, "compile_output": "", "tests": None}
    if py:
        r = await sandbox.run([sys.executable, "-m", "py_compile", *py], wt, timeout=120, label="dev:compile",
                              proposal_id=proposal_id)
        sandbox.cleanup(r)
        result["compile_ok"] = r["exit_code"] == 0
        result["compile_output"] = truncate(r["stderr"] or r["stdout"], 3000)
        if not result["compile_ok"]:
            return result
    targets = [t[len("backend/"):] for t in tests if t.startswith("backend/tests/") and (wt / t).exists()]
    if targets:
        res = await sandbox.run_test_suite(ws, worktree=wt, test_path=" ".join(targets[:1]) if len(targets) == 1
                                           else "tests", label="dev:tests", proposal_id=proposal_id)
        result["tests"] = {k: res.get(k) for k in ("passed", "failed", "errors", "tests", "failed_ids")}
        result["tests_output"] = truncate(res.get("output_tail", ""), 4000)
    return result


async def develop(proposal_id: str, cycle_id: str = "") -> dict:
    async with session_scope() as s:
        p = await s.get(Proposal, proposal_id)
        if p is None:
            raise ValueError("proposta não encontrada")
        p.status = "developing"
        p.error = ""
        snapshot = {k: getattr(p, k) for k in ("code", "title", "kind", "strategy", "problem", "diagnosis",
                                                 "objective", "solution", "affected_files", "acceptance_criteria",
                                                 "tests_required", "payload")}
        await audit.record("agent:developer", "proposal.develop_started", p.code, {}, session=s)
    log_entries: list[dict] = []
    cost = 0.0
    models: list[str] = []
    ws = await get_workspace()
    await ws.sync()
    base_sha = await ws.head()
    branch = f"evolution/{snapshot['code'].lower()}-{slugify(snapshot['title'], 32)}"
    await ws.delete_branch(branch)
    wt = await ws.create_worktree(branch, base_sha)
    try:
        if snapshot["strategy"] == "deterministic":
            gen = (snapshot["payload"] or {}).get("generator")
            if gen != "architecture_doc":
                raise ValueError(f"gerador determinístico desconhecido: {gen}")
            data = codeintel.analyze_repo(wt)
            content = codeintel.render_architecture_doc(data)
            applied, rejected = apply_edits(wt, [{"path": codeintel.GENERATED_DOC, "action": "write",
                                                  "content": content}])
            log_entries.append({"step": "deterministic", "generator": gen, "applied": applied, "rejected": rejected})
        else:
            max_iter = 3
            async with session_scope() as s:
                from ultron.settings_store import get_setting

                max_iter = int(await get_setting(s, "evolution.dev_max_iterations") or 3)
            files = list(snapshot["affected_files"] or [])
            feedback = ""
            changed: list[str] = []
            ctx = BudgetContext(purpose="evolution.develop", agent_id="developer", cycle_id=cycle_id)
            for it in range(1, max_iter + 1):
                tree_hint = "\n".join(f"- {x}" for x in sorted({str(Path(f).parent) for f in files}) or ["backend/ultron"])
                user = (f"PROPOSTA {snapshot['code']}: {snapshot['title']}\nTipo: {snapshot['kind']}\n"
                        f"Problema: {snapshot['problem']}\nDiagnóstico: {snapshot['diagnosis']}\n"
                        f"Objetivo: {snapshot['objective']}\nSolução proposta: {snapshot['solution']}\n"
                        f"Critérios de aceitação: {snapshot['acceptance_criteria']}\n"
                        f"Testes exigidos: {snapshot['tests_required']}\n\nDiretórios relevantes:\n{tree_hint}\n\n"
                        f"ARQUIVOS ATUAIS:\n{_file_context(wt, sorted(set(files + changed)))}")
                if feedback:
                    user += f"\n\nRESULTADO DA ITERAÇÃO ANTERIOR (corrija):\n{feedback}"
                data, res = await complete_json(
                    [ChatMessage("system", DEV_PROMPT.format(forbidden=", ".join(FORBIDDEN_PATHS[:12]))),
                     ChatMessage("user", user)], TaskProfile(task="code", tier="premium"), ctx=ctx, max_tokens=8000,
                    timeout=300)
                cost += res.cost_usd
                models.append(f"{res.provider}:{res.model}")
                edits = (data or {}).get("edits") if isinstance(data, dict) else None
                applied, rejected = apply_edits(wt, edits or [])
                for a in applied:
                    path = a.split(":", 1)[1]
                    if path not in changed:
                        changed.append(path)
                tests = [str(t) for t in ((data or {}).get("tests_added") or [])] + _related_tests(wt, changed)
                checks = await _quick_checks(ws, wt, changed, tests, proposal_id)
                entry = {"step": f"iteração {it}", "model": models[-1], "summary": truncate(str((data or {}).get(
                    "summary", "")), 1000), "applied": applied, "rejected": rejected, "checks": checks,
                    "cost_usd": res.cost_usd}
                log_entries.append(entry)
                problems = []
                if rejected:
                    problems.append("Edições rejeitadas: " + "; ".join(f"{r['path']}: {r['reason']}" for r in rejected))
                if not checks["compile_ok"]:
                    problems.append("Erro de compilação:\n" + checks["compile_output"])
                t = checks.get("tests") or {}
                if t and (t.get("failed") or t.get("errors")):
                    problems.append("Testes falhando:\n" + checks.get("tests_output", ""))
                if not applied and not changed:
                    problems.append("Nenhuma edição aplicada.")
                if not problems:
                    break
                feedback = "\n\n".join(problems)
        sha = await ws.commit_all(wt, f"{snapshot['code']}: {snapshot['title']}\n\nGerado pelo Developer Agent do "
                                      f"ULTRON (proposta {snapshot['code']}).")
        if not sha:
            raise ValueError("nenhuma alteração foi produzida")
        changes = await ws.diff_changes(base_sha, branch)
        tree = await ws.tree(branch)
        added = sum(len(c.added_lines) for c in changes)
        removed = sum(c.removed_count for c in changes)
        async with session_scope() as s:
            p = await s.get(Proposal, proposal_id)
            p.branch, p.base_sha, p.commit_sha, p.tree_sha = branch, base_sha, sha, tree
            p.changed_files = [{"path": c.path, "status": c.status} for c in changes]
            p.diff_stats = {"files": len(changes), "added": added, "removed": removed}
            p.dev_log = log_entries
            p.cost_usd = (p.cost_usd or 0) + cost
            p.payload = {**(p.payload or {}), "dev_models": models}
            p.status = "testing"
            await audit.record("agent:developer", "proposal.developed", p.code,
                               {"branch": branch, "commit": sha, "files": len(changes)}, session=s)
        return {"status": "testing", "branch": branch, "commit": sha, "files": len(changes)}
    except (BudgetExceeded, Exception) as e:
        async with session_scope() as s:
            p = await s.get(Proposal, proposal_id)
            p.status = "failed"
            p.error = f"desenvolvimento falhou: {e}"
            p.dev_log = log_entries
            p.cost_usd = (p.cost_usd or 0) + cost
            p.updated_at = utcnow()
            await audit.record("agent:developer", "proposal.develop_failed", p.code, {"error": str(e)[:500]},
                               session=s)
        await ws.delete_branch(branch)
        return {"status": "failed", "error": str(e)}
    finally:
        await ws.remove_worktree(wt)
