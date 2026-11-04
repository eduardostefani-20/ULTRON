"""Infraestrutura de ferramentas: definição, autorização por política e execução medida."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from ultron import telemetry
from ultron.governance import audit
from ultron.governance.permissions import authorize_tool
from ultron.llm.budget import BudgetContext
from ultron.utils import truncate


@dataclass
class ToolContext:
    agent_id: str
    agent_tools: list[str]
    agent_scopes: list[str]
    granted_scopes: list[str]
    user_id: str | None = None
    mission_id: str = ""
    cycle_id: str = ""
    budget: BudgetContext = field(default_factory=BudgetContext)
    approved_actions: set[str] = field(default_factory=set)
    generation: int = 0


@dataclass
class ToolOutcome:
    ok: bool
    output: str
    denied: bool = False
    needs_approval: bool = False
    approval_summary: str = ""
    data: dict = field(default_factory=dict)


Handler = Callable[[ToolContext, dict], Awaitable[str | ToolOutcome]]


@dataclass
class Tool:
    name: str
    description: str
    args: dict[str, str]
    scope: str
    handler: Handler
    sensitive: bool = False
    timeout: float = 60.0

    def prompt_spec(self) -> str:
        args = ", ".join(f'"{k}": {v}' for k, v in self.args.items()) or "sem argumentos"
        return f"- {self.name}: {self.description} | argumentos: {{{args}}}"


_TOOLS: dict[str, Tool] = {}


def register(tool: Tool) -> Tool:
    _TOOLS[tool.name] = tool
    return tool


def get_tool(name: str) -> Tool | None:
    return _TOOLS.get(name)


def all_tools() -> dict[str, Tool]:
    return dict(_TOOLS)


async def run_tool(ctx: ToolContext, name: str, args: dict) -> ToolOutcome:
    tool = _TOOLS.get(name)
    if tool is None:
        return ToolOutcome(False, f"ferramenta desconhecida: {name}. Use apenas as ferramentas listadas.")
    if not isinstance(args, dict):
        return ToolOutcome(False, "argumentos devem ser um objeto JSON")
    decision = authorize_tool(name, tool.scope, ctx.agent_tools, ctx.agent_scopes, ctx.granted_scopes)
    summary = truncate(json.dumps(args, ensure_ascii=False, default=str), 300)
    if not decision.allowed:
        telemetry.record_tool_call(tool=name, agent_id=ctx.agent_id, mission_id=ctx.mission_id, success=False,
                                   denied=True, args_summary=summary, error=decision.reason)
        await audit.record(f"agent:{ctx.agent_id}", "tool.denied", name, {"reason": decision.reason,
                                                                          "mission_id": ctx.mission_id})
        return ToolOutcome(False, f"NEGADO pela governança: {decision.reason}", denied=True)
    action_key = f"{name}:{summary}"
    if tool.sensitive and action_key not in ctx.approved_actions:
        return ToolOutcome(False, "esta ação exige aprovação humana", needs_approval=True,
                           approval_summary=f"{name}({summary})", data={"action_key": action_key})
    t0 = time.monotonic()
    try:
        result = await asyncio.wait_for(tool.handler(ctx, args), timeout=tool.timeout)
        outcome = result if isinstance(result, ToolOutcome) else ToolOutcome(True, str(result))
        telemetry.record_tool_call(tool=name, agent_id=ctx.agent_id, mission_id=ctx.mission_id, success=outcome.ok,
                                   latency_ms=int((time.monotonic() - t0) * 1000), args_summary=summary,
                                   error="" if outcome.ok else truncate(outcome.output, 300))
        return outcome
    except TimeoutError:
        msg = f"tempo esgotado na ferramenta {name} ({tool.timeout}s)"
    except Exception as e:
        msg = f"erro na ferramenta {name}: {e.__class__.__name__}: {e}"
    telemetry.record_tool_call(tool=name, agent_id=ctx.agent_id, mission_id=ctx.mission_id, success=False,
                               latency_ms=int((time.monotonic() - t0) * 1000), args_summary=summary, error=msg)
    telemetry.record_error(f"tool:{name}", msg)
    return ToolOutcome(False, msg)
