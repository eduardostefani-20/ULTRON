"""Propostas de evolução estruturadas e fila priorizada."""

from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ultron.db import session_scope
from ultron.evolution.diagnostics import SEVERITY_WEIGHT
from ultron.governance import audit
from ultron.governance.policy import Risk, path_risk
from ultron.llm.budget import BudgetContext
from ultron.llm.service import ChatMessage, TaskProfile, complete_json
from ultron.models import Diagnostic, Proposal
from ultron.utils import truncate

log = logging.getLogger("ultron.proposals")

ACTIVE = ("proposed", "queued", "developing", "testing", "evaluated", "awaiting_approval", "approved")
KINDS = ("code", "docs", "config", "agent", "tool", "test")

PROPOSAL_PROMPT = """Você é o Self-Improvement Agent do ULTRON. A partir do diagnóstico (baseado em dados reais) e do
contexto, elabore UMA proposta de melhoria concreta, pequena, testável e reversível do próprio ULTRON.
Não proponha instalar dependências novas. Não toque em governança, segurança, sandbox, avaliação ou publicação
(caminhos protegidos). Prefira mudanças em poucos arquivos com testes.

Responda em JSON:
{"title": "...", "kind": "code|test|docs|tool|agent", "problem": "...", "diagnosis": "causa provável com base na evidência",
 "objective": "resultado mensurável", "solution": "o que mudar e como", "affected_files": ["caminho/relativo"],
 "dependencies": [], "benefits": "...", "risks": "...", "cost_estimate_usd": 0.05,
 "tests_required": ["..."], "acceptance_criteria": ["critério verificável"], "rollback_strategy": "...",
 "declared_risk": "low|medium|high", "confidence": 0.0-1.0}"""


def estimate_risk(files: list[str], kind: str) -> Risk:
    """Estimativa inicial (a classificação definitiva é feita sobre o diff real na avaliação)."""
    level = Risk.LOW if kind in ("docs", "test") else Risk.MEDIUM
    for f in files:
        r = path_risk(f, "A" if kind == "test" else "M")
        if r == Risk.HIGH:
            return Risk.HIGH
        if r == Risk.MEDIUM:
            level = Risk.MEDIUM
    return level


def priority(severity: str, confidence: float, cost: float, risk: str) -> float:
    w = SEVERITY_WEIGHT.get(severity, 1)
    risk_pen = {"low": 1.0, "medium": 0.75, "high": 0.5}.get(risk, 0.7)
    return round(w * max(0.1, confidence) * risk_pen / (1 + 10 * max(0.0, cost)), 4)


async def next_code(session: AsyncSession, offset: int = 0) -> str:
    n = (await session.execute(select(func.count()).select_from(Proposal))).scalar_one()
    return f"EVO-{n + 1 + offset:04d}"


async def create_proposal(session: AsyncSession, *, title: str, source: str = "diagnostic", kind: str = "code",
                          strategy: str = "llm", created_by: str = "ultron", cycle_id: str = "",
                          severity: str = "medium", confidence: float = 0.6, **fields) -> Proposal:
    title = (title or "").strip()
    if len(title) < 5:
        raise ValueError("a proposta precisa de um título")
    kind = kind if kind in KINDS else "code"
    files = [str(f) for f in (fields.pop("affected_files", None) or [])][:20]
    risk = estimate_risk(files, kind)
    raw_cost = fields.pop("cost_estimate_usd", None)
    cost = 0.05 if raw_cost is None else max(0.0, float(raw_cost))
    allowed = {c.key for c in Proposal.__table__.columns}
    clean = {k: v for k, v in fields.items() if k in allowed}
    for attempt in range(5):
        code = await next_code(session, attempt)
        p = Proposal(code=code, title=truncate(title, 300), source=source, kind=kind, strategy=strategy,
                     created_by=created_by, cycle_id=cycle_id, affected_files=files, risk_level=risk.value,
                     cost_estimate_usd=cost, priority_score=priority(severity, confidence, cost, risk.value),
                     status="queued", **clean)
        try:
            async with session.begin_nested():
                session.add(p)
                await session.flush()
            break
        except IntegrityError:
            continue
    else:  # pragma: no cover
        raise RuntimeError("não foi possível gerar código único para a proposta")
    await audit.record(created_by, "proposal.created", p.code, {"title": p.title, "kind": kind, "risk": p.risk_level,
                                                                "source": source}, session=session)
    return p


async def has_active_for(session: AsyncSession, signature: str) -> bool:
    rows = (await session.execute(select(Proposal.payload).where(Proposal.status.in_(ACTIVE)))).scalars().all()
    return any((p or {}).get("signature") == signature for p in rows)


async def recently_failed(session: AsyncSession, signature: str) -> bool:
    rows = (await session.execute(select(Proposal.payload).where(Proposal.status.in_(("failed", "rejected",
                                                                                      "rolled_back")))
                                  .order_by(Proposal.updated_at.desc()).limit(50))).scalars().all()
    return sum(1 for p in rows if (p or {}).get("signature") == signature) >= 2


async def generate_from_diagnostics(cycle_id: str, max_new: int, *, code_context: str = "") -> list[str]:
    """Transforma diagnósticos acionáveis em propostas (determinísticas ou via Self-Improvement Agent)."""
    created: list[str] = []
    async with session_scope() as s:
        diags = (await s.execute(select(Diagnostic).where(Diagnostic.status == "open"))).scalars().all()
        diags = sorted(diags, key=lambda d: -SEVERITY_WEIGHT.get(d.severity, 1))
        candidates = []
        for d in diags:
            action = (d.evidence or {}).get("_action", "proposal")
            if action not in ("proposal",):
                continue
            if await has_active_for(s, d.signature) or await recently_failed(s, d.signature):
                continue
            candidates.append({"id": d.id, "signature": d.signature, "severity": d.severity, "title": d.title,
                               "detail": d.detail, "category": d.category, "suggestion": d.suggestion,
                               "research": d.research, "template": (d.evidence or {}).get("_template") or {},
                               "evidence": {k: v for k, v in (d.evidence or {}).items() if not k.startswith("_")}})
    for c in candidates:
        if len(created) >= max_new:
            break
        tpl = c["template"]
        try:
            if tpl.get("strategy") == "deterministic":
                async with session_scope() as s:
                    p = await create_proposal(
                        s, title="Regenerar documentação de arquitetura a partir do código", kind="docs",
                        strategy="deterministic", cycle_id=cycle_id, severity=c["severity"], confidence=0.95,
                        problem=c["detail"], diagnosis="O mapa de código mudou desde a última geração do documento.",
                        objective="docs/ARQUITETURA_GERADA.md idêntico à análise do código atual.",
                        solution="Documentation Agent regenera o arquivo de forma determinística (sem LLM).",
                        affected_files=["docs/ARQUITETURA_GERADA.md"], benefits="Documentação sempre fiel ao código.",
                        risks="Nenhum risco funcional (apenas documentação).", cost_estimate_usd=0.0,
                        tests_required=["suíte completa continua passando"],
                        acceptance_criteria=["arquivo regenerado corresponde ao mapa de código",
                                             "nenhum teste quebrado"],
                        rollback_strategy="git revert do merge", diagnostic_ids=[c["id"]],
                        payload={"signature": c["signature"], "generator": tpl.get("generator")},
                        declared_risk="low")
                    created.append(p.id)
                continue
            data, res = await complete_json(
                [ChatMessage("system", PROPOSAL_PROMPT),
                 ChatMessage("user", f"DIAGNÓSTICO ({c['severity']}/{c['category']}): {c['title']}\n{c['detail']}\n"
                                     f"Sugestão inicial: {c['suggestion']}\nEvidência: {truncate(str(c['evidence']), 1500)}\n"
                                     f"Arquivos relacionados: {tpl.get('files')}\n"
                                     + (f"Pesquisa: {truncate(c['research'], 2000)}\n" if c['research'] else "")
                                     + (f"\nMAPA DO CÓDIGO:\n{truncate(code_context, 5000)}" if code_context else ""))],
                TaskProfile(task="plan", tier="balanced"),
                ctx=BudgetContext(purpose="evolution.plan", agent_id="self_improvement", cycle_id=cycle_id),
                max_tokens=2000)
            if not isinstance(data, dict) or not data.get("title"):
                continue
            files = [str(f) for f in (data.get("affected_files") or tpl.get("files") or [])]
            async with session_scope() as s:
                p = await create_proposal(
                    s, title=str(data["title"]), kind=str(data.get("kind") or tpl.get("kind") or "code"),
                    cycle_id=cycle_id, severity=c["severity"], confidence=float(data.get("confidence") or 0.6),
                    problem=str(data.get("problem", "")), diagnosis=str(data.get("diagnosis", "")),
                    objective=str(data.get("objective", "")), solution=str(data.get("solution", "")),
                    affected_files=files, dependencies=list(data.get("dependencies") or []),
                    benefits=str(data.get("benefits", "")), risks=str(data.get("risks", "")),
                    cost_estimate_usd=float(data.get("cost_estimate_usd") or 0.05),
                    tests_required=list(data.get("tests_required") or []),
                    acceptance_criteria=list(data.get("acceptance_criteria") or []),
                    rollback_strategy=str(data.get("rollback_strategy") or "git revert do merge"),
                    declared_risk=str(data.get("declared_risk") or ""), diagnostic_ids=[c["id"]],
                    payload={"signature": c["signature"], "planner_model": f"{res.provider}:{res.model}"},
                    cost_usd=res.cost_usd, created_by="agent:self_improvement")
                created.append(p.id)
        except Exception as e:
            log.info("proposta não gerada para %s: %s", c["signature"], e)
            continue
    return created


async def queue(session: AsyncSession, limit: int = 50) -> list[Proposal]:
    return (await session.execute(select(Proposal).where(Proposal.status == "queued")
                                  .order_by(Proposal.priority_score.desc(), Proposal.created_at.asc()).limit(limit))
            ).scalars().all()
