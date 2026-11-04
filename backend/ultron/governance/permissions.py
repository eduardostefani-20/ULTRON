"""Escopos de permissão e validação de privilégios de agentes.

Separação obrigatória:
  1. READ_ANALYZE     — ler e analisar (código, métricas, memória)
  2. DEVELOP_SANDBOX  — desenvolver/testar em ambiente isolado
  3. PUBLISH          — publicar alterações (NUNCA concedido a agentes; só o publicador
                        com política e aprovações)
  4. EXTERNAL_ACCESS  — acessar dados e serviços externos (web, APIs)
  + MEMORY_WRITE      — gravar memória
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Scope(StrEnum):
    READ_ANALYZE = "read_analyze"
    DEVELOP_SANDBOX = "develop_sandbox"
    PUBLISH = "publish"
    EXTERNAL_ACCESS = "external_access"
    MEMORY_WRITE = "memory_write"


ALL_SCOPES = {s.value for s in Scope}

# Escopos que o proprietário pode conceder à autonomia (PUBLISH fica fora de propósito).
GRANTABLE_SCOPES = {Scope.READ_ANALYZE, Scope.DEVELOP_SANDBOX, Scope.EXTERNAL_ACCESS, Scope.MEMORY_WRITE}

DEFAULT_GRANTED_SCOPES = [
    Scope.READ_ANALYZE.value,
    Scope.DEVELOP_SANDBOX.value,
    Scope.EXTERNAL_ACCESS.value,
    Scope.MEMORY_WRITE.value,
]

# Limites para criação recursiva de agentes (evita agentes criando agentes indefinidamente)
MAX_AGENT_GENERATION = 1
MAX_DYNAMIC_AGENTS = 12
MAX_DYNAMIC_AGENT_BUDGET_USD = 0.10
MAX_DYNAMIC_AGENT_STEPS = 8


@dataclass
class Decision:
    allowed: bool
    reason: str = ""


def authorize_tool(tool_name: str, tool_scope: str, agent_tools: list[str], agent_scopes: list[str],
                   granted_scopes: list[str]) -> Decision:
    """Um agente só usa uma ferramenta se: ela está na lista do agente, o agente possui o
    escopo, e o proprietário concedeu esse escopo à autonomia."""
    if tool_scope == Scope.PUBLISH.value:
        return Decision(False, "ferramentas de publicação não podem ser usadas por agentes")
    if tool_name not in agent_tools:
        return Decision(False, f"ferramenta '{tool_name}' não está autorizada para este agente")
    if tool_scope not in agent_scopes:
        return Decision(False, f"agente não possui o escopo '{tool_scope}'")
    if tool_scope not in granted_scopes:
        return Decision(False, f"escopo '{tool_scope}' não foi concedido pelo proprietário")
    return Decision(True)


def validate_new_agent(*, requested_scopes: list[str], requested_tools: list[str], creator_scopes: list[str],
                       creator_tools: list[str], generation: int, budget_usd: float, max_steps: int,
                       existing_dynamic: int, purpose: str) -> Decision:
    """Valida a criação de um agente por outro agente (ou pelo motor de evolução)."""
    if not purpose or len(purpose.strip()) < 15:
        return Decision(False, "todo novo agente precisa de uma finalidade descrita")
    if Scope.PUBLISH.value in requested_scopes:
        return Decision(False, "agentes não podem receber o escopo de publicação")
    unknown = set(requested_scopes) - ALL_SCOPES
    if unknown:
        return Decision(False, f"escopos desconhecidos: {sorted(unknown)}")
    if not set(requested_scopes) <= set(creator_scopes):
        return Decision(False, "um agente não pode criar outro com mais privilégios que os seus")
    if not set(requested_tools) <= set(creator_tools):
        return Decision(False, "um agente não pode conceder ferramentas que ele mesmo não possui")
    if generation > MAX_AGENT_GENERATION:
        return Decision(False, "limite de geração atingido: agentes criados não podem criar outros agentes")
    if existing_dynamic >= MAX_DYNAMIC_AGENTS:
        return Decision(False, f"limite de {MAX_DYNAMIC_AGENTS} agentes dinâmicos atingido")
    if budget_usd <= 0 or budget_usd > MAX_DYNAMIC_AGENT_BUDGET_USD:
        return Decision(False, f"orçamento por execução deve estar entre 0 e US$ {MAX_DYNAMIC_AGENT_BUDGET_USD}")
    if max_steps < 1 or max_steps > MAX_DYNAMIC_AGENT_STEPS:
        return Decision(False, f"máximo de passos deve estar entre 1 e {MAX_DYNAMIC_AGENT_STEPS}")
    return Decision(True)


def sanitize_granted_scopes(scopes: list[str]) -> list[str]:
    """O proprietário pode conceder escopos, mas PUBLISH nunca entra na lista de autonomia."""
    return sorted({s for s in scopes if s in {g.value for g in GRANTABLE_SCOPES}})
