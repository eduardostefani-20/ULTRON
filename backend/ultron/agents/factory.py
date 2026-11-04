"""Fábrica de agentes: semeia os nativos e valida a criação recursiva de novos agentes."""

from __future__ import annotations

import re

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ultron.agents.definitions import BUILTIN_AGENTS
from ultron.governance import audit
from ultron.governance.approvals import request_approval
from ultron.governance.permissions import validate_new_agent
from ultron.models import AgentDefinition
from ultron.tools.base import all_tools


async def seed_builtin_agents(session: AsyncSession) -> int:
    n = 0
    for spec in BUILTIN_AGENTS:
        row = await session.get(AgentDefinition, spec["id"])
        if row is None:
            session.add(AgentDefinition(**spec, builtin=True, status="active", created_by="system",
                                        purpose=spec["description"]))
            n += 1
        else:
            # mantém o status escolhido pelo usuário; atualiza a definição nativa
            for k in ("name", "role", "description", "tools", "scopes", "model_tier", "task_type", "max_steps",
                      "budget_usd_per_run"):
                setattr(row, k, spec[k])
            row.builtin = True
    await session.flush()
    return n


async def propose_agent(session: AsyncSession, *, creator_id: str, spec: dict, generation: int) -> tuple[bool, str]:
    """Agente (ou motor de evolução) propõe um novo agente. Fica pendente de aprovação humana."""
    from ultron.settings_store import get_setting

    if not await get_setting(session, "autonomy.allow_agent_creation"):
        return False, "criação de agentes desativada pelo proprietário"
    creator = await session.get(AgentDefinition, creator_id)
    if creator is None:
        return False, "agente criador desconhecido"
    slug = re.sub(r"[^a-z0-9_]", "_", str(spec.get("id") or spec.get("name") or "").lower()).strip("_")[:50]
    if not slug or await session.get(AgentDefinition, slug):
        return False, "identificador inválido ou já existente"
    tools = [str(t) for t in (spec.get("tools") or [])]
    unknown = [t for t in tools if t not in all_tools()]
    if unknown:
        return False, f"ferramentas inexistentes: {unknown}"
    scopes = [str(s) for s in (spec.get("scopes") or [])]
    dynamic = (await session.execute(select(func.count()).select_from(AgentDefinition)
                                     .where(AgentDefinition.builtin.is_(False)))).scalar_one()
    try:
        budget = float(spec.get("budget_usd_per_run") or 0.03)
        steps = int(spec.get("max_steps") or 5)
    except (TypeError, ValueError):
        return False, "orçamento/passos inválidos"
    decision = validate_new_agent(requested_scopes=scopes, requested_tools=tools, creator_scopes=list(creator.scopes),
                                  creator_tools=list(creator.tools), generation=max(generation, creator.generation + 1),
                                  budget_usd=budget, max_steps=steps, existing_dynamic=dynamic,
                                  purpose=str(spec.get("purpose") or ""))
    if not decision.allowed:
        await audit.record(f"agent:{creator_id}", "agent.creation_denied", slug, {"reason": decision.reason},
                           session=session)
        return False, decision.reason
    agent = AgentDefinition(id=slug, name=str(spec.get("name") or slug)[:120], role=str(spec.get("role") or "")[:200],
                            description=str(spec.get("purpose") or "")[:2000], purpose=str(spec.get("purpose") or ""),
                            system_prompt=str(spec.get("system_prompt") or "")[:4000], tools=tools, scopes=scopes,
                            model_tier=str(spec.get("model_tier") or "fast"), task_type=str(spec.get("task_type") or "chat"),
                            max_steps=steps, budget_usd_per_run=budget, builtin=False, status="pending_approval",
                            created_by=f"agent:{creator_id}", parent_agent=creator_id,
                            generation=creator.generation + 1)
    session.add(agent)
    await session.flush()
    await request_approval(session, kind="agent_creation", target_type="agent", target_id=slug, risk="medium",
                           title=f"Novo agente proposto: {agent.name}",
                           summary=f"Finalidade: {agent.purpose}\nFerramentas: {tools}\nEscopos: {scopes}\n"
                                   f"Orçamento por execução: US$ {budget}", requested_by=f"agent:{creator_id}",
                           details={"agent_id": slug})
    await audit.record(f"agent:{creator_id}", "agent.proposed", slug, {"tools": tools, "scopes": scopes},
                       session=session)
    return True, f"agente '{slug}' proposto e aguardando aprovação humana"
