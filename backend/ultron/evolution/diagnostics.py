"""Autodiagnóstico baseado em DADOS OBSERVÁVEIS (métricas, erros, testes, mapa de código).

Responde: quais são minhas limitações? o que está falhando? onde desperdiço recursos? que
capacidades faltam? quais problemas se repetem?
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ultron.models import Diagnostic
from ultron.utils import utcnow


@dataclass
class Finding:
    signature: str
    category: str  # capability|reliability|performance|cost|quality|code|security|memory|tests|docs
    severity: str  # info|low|medium|high|critical
    title: str
    detail: str = ""
    evidence: dict = field(default_factory=dict)
    suggestion: str = ""
    action: str = "proposal"  # proposal|human|config|none
    template: dict = field(default_factory=dict)


SEVERITY_WEIGHT = {"info": 0.5, "low": 1, "medium": 2, "high": 3, "critical": 4}


def analyze(snap: dict, ctx: dict, codemap: dict | None) -> list[Finding]:
    out: list[Finding] = []
    llm = snap.get("llm", {})

    # ---------------------------------------------------------------- capacidades
    if not ctx.get("llm_providers"):
        out.append(Finding("cap.no_llm", "capability", "critical", "Nenhum provedor de IA configurado",
                           "Sem um provedor real, chat, agentes, missões e desenvolvimento autônomo não funcionam.",
                           suggestion="Adicione uma chave em Integrações (Anthropic, OpenAI, Gemini, DeepSeek...).",
                           action="human"))
    elif len(ctx["llm_providers"]) == 1:
        out.append(Finding("cap.single_provider", "capability", "medium",
                           "Apenas um provedor de IA: sem fallback e Conselho com baixa diversidade",
                           f"Provedor ativo: {ctx['llm_providers'][0]}.",
                           suggestion="Conecte um segundo provedor barato (ex.: Gemini Flash ou DeepSeek).",
                           action="human"))
    if not ctx.get("search_providers"):
        out.append(Finding("cap.no_search_key", "capability", "low",
                           "Pesquisa web sem provedor dedicado (usando DuckDuckGo/Wikipedia)",
                           "A busca sem chave é limitada e instável.",
                           suggestion="Adicione Tavily (1.000 buscas grátis/mês) ou Brave em Integrações.",
                           action="human"))
    if not ctx.get("github"):
        out.append(Finding("cap.no_github", "capability", "medium",
                           "Publicação no GitHub indisponível (sem token)",
                           "Melhorias aprovadas ficam apenas no workspace local e não chegam ao deploy.",
                           suggestion="Crie um token fine-grained (Contents + Pull requests) e salve em Integrações.",
                           action="human"))
    if ctx.get("sandbox_network") == "not_isolated":
        out.append(Finding("sec.sandbox_network", "security", "high", "Sandbox sem isolamento de rede",
                           "O kernel/hospedagem não permite namespaces de rede; código experimental poderia acessar "
                           "a rede. A publicação automática permanece bloqueada.",
                           suggestion="Use uma hospedagem com suporte a 'unshare' ou Docker, ou valide via CI no GitHub.",
                           action="human"))
    if ctx.get("workspace_error"):
        out.append(Finding("cap.workspace", "capability", "high", "Workspace de desenvolvimento indisponível",
                           ctx["workspace_error"], suggestion="Configure ULTRON_REPO_URL/ULTRON_GITHUB_REPO e o token.",
                           action="human"))

    # ---------------------------------------------------------------- confiabilidade
    for p, d in (llm.get("providers") or {}).items():
        if d["calls"] >= 5 and d["error_rate"] >= 0.2:
            out.append(Finding(f"rel.provider_errors.{p}", "reliability", "high" if d["error_rate"] > 0.5 else "medium",
                               f"Provedor {p} com {d['error_rate']:.0%} de falhas",
                               f"{d['failures']} falhas em {d['calls']} chamadas nas últimas {snap['window_hours']}h.",
                               evidence=d, suggestion="Verificar chave/cota; priorizar outro provedor no roteamento.",
                               action="config", template={"setting": "routing.preferred_providers"}))
        if d.get("latency_p95_ms", 0) > 30000 and d["calls"] >= 5:
            out.append(Finding(f"perf.latency.{p}", "performance", "medium", f"Latência alta no provedor {p}",
                               f"p95 de {d['latency_p95_ms'] / 1000:.1f}s.", evidence=d,
                               suggestion="Usar camada 'fast' para tarefas simples ou outro provedor.", action="config"))
        if d.get("unknown_price"):
            out.append(Finding(f"cost.unknown_price.{p}", "cost", "low", f"Modelos de {p} sem preço catalogado",
                               "O orçamento está usando preço conservador (US$3/US$15 por 1M tokens).",
                               suggestion="Informe o preço real em Configurações → Roteamento.", action="human"))
    for tool, d in (snap.get("tools") or {}).items():
        if d["calls"] >= 4 and d["failure_rate"] >= 0.4:
            out.append(Finding(f"rel.tool.{tool}", "reliability", "medium",
                               f"Ferramenta '{tool}' falha em {d['failure_rate']:.0%} das chamadas",
                               evidence=d, suggestion="Investigar causa e tornar a ferramenta mais robusta."))
        if d.get("denied", 0) >= 5:
            out.append(Finding(f"sec.tool_denied.{tool}", "security", "low",
                               f"Agentes tentaram usar '{tool}' sem permissão {d['denied']} vezes",
                               evidence=d, suggestion="Revisar prompts/planos que pedem ferramentas não autorizadas.",
                               action="none"))
    ms = snap.get("missions", {})
    by = ms.get("by_status", {})
    fin = by.get("COMPLETED", 0) + by.get("FAILED", 0)
    if fin >= 3 and (ms.get("success_rate") or 0) < 0.7:
        out.append(Finding("quality.missions", "quality", "high",
                           f"Taxa de sucesso das missões baixa ({(ms.get('success_rate') or 0):.0%})",
                           f"{by.get('FAILED', 0)} falhas de {fin} missões finalizadas.", evidence=by,
                           suggestion="Analisar falhas recorrentes do planejamento e dos agentes."))
    for agent, d in (snap.get("agents") or {}).items():
        if d["runs"] >= 4 and d["failure_rate"] >= 0.4:
            out.append(Finding(f"quality.agent.{agent}", "quality", "medium",
                               f"Agente {agent} falha em {d['failure_rate']:.0%} das execuções", evidence=d,
                               suggestion="Ajustar instruções, ferramentas ou camada de modelo do agente."))
    for e in snap.get("errors", []):
        if e["count"] >= 3:
            out.append(Finding(f"rel.recurring.{e['signature']}", "reliability", "medium" if e["count"] < 10 else "high",
                               f"Erro recorrente ({e['count']}x) em {e['source']}", e["message"][:500], evidence=e,
                               suggestion="Corrigir a causa raiz do erro recorrente."))
    q = snap.get("quality", {})
    rated = q.get("positive", 0) + q.get("negative", 0)
    if rated >= 4 and q.get("negative", 0) / rated > 0.3:
        out.append(Finding("quality.feedback", "quality", "medium",
                           f"{q['negative']} de {rated} respostas avaliadas negativamente", evidence=q,
                           suggestion="Revisar respostas mal avaliadas e o modo/modelo usado."))
    api = snap.get("api", {})
    if api.get("api.errors_5xx", {}).get("sum", 0) >= 5:
        out.append(Finding("rel.api_5xx", "reliability", "high",
                           f"{int(api['api.errors_5xx']['sum'])} erros 5xx na API", evidence=api,
                           suggestion="Investigar exceções não tratadas."))

    # ---------------------------------------------------------------- custos
    b = ctx.get("budget") or {}
    if b and b.get("projected_month_usd", 0) > b.get("limit_usd", 1e9):
        out.append(Finding("cost.projection", "cost", "high", "Projeção de gasto mensal acima do orçamento",
                           f"Projeção: US$ {b['projected_month_usd']:.2f} para limite de US$ {b['limit_usd']:.2f}.",
                           evidence=b, suggestion="Priorizar modelos 'fast', cache e reduzir ciclos de evolução.",
                           action="config"))

    # ---------------------------------------------------------------- testes
    base = ctx.get("baseline_tests")
    if base and (base.get("failed") or base.get("errors")):
        out.append(Finding("tests.baseline_failing", "tests", "critical",
                           f"A suíte de testes do branch estável falha ({base.get('failed')} falhas, "
                           f"{base.get('errors')} erros)", ", ".join(base.get("failed_ids", [])[:8]), evidence=base,
                           suggestion="Corrigir os testes quebrados antes de qualquer outra evolução.",
                           template={"kind": "code", "files": []}))

    # ---------------------------------------------------------------- código
    if codemap:
        for f in codemap.get("findings", []):
            kind = f.get("kind")
            if kind in ("syntax_error",):
                out.append(Finding(f"code.{kind}.{f['path']}", "code", "high", f["title"], f.get("detail", ""),
                                   evidence=f, template={"kind": "code", "files": [f["path"]]}))
            elif kind in ("large_file", "complexity", "import_cycle", "duplication"):
                out.append(Finding(f"code.{kind}.{f['path']}", "code", "low", f["title"], f.get("detail", ""),
                                   evidence=f, template={"kind": "code", "files": [f["path"]]}))
            elif kind == "untested_module":
                out.append(Finding(f"tests.untested.{f['path']}", "tests", "low", f["title"], f.get("detail", ""),
                                   evidence=f, template={"kind": "test", "files": [f["path"]]}))
            elif kind == "unused_module":
                out.append(Finding(f"code.unused.{f['path']}", "code", "info", f["title"], f.get("detail", ""),
                                   evidence=f, action="none"))
    if ctx.get("doc_stale"):
        out.append(Finding("docs.architecture_stale", "docs", "low",
                           "Documentação de arquitetura gerada está desatualizada",
                           "docs/ARQUITETURA_GERADA.md não reflete o código atual.",
                           suggestion="Regenerar o documento a partir do mapa de código.",
                           template={"kind": "docs", "strategy": "deterministic", "generator": "architecture_doc"}))
    return out


async def upsert(session: AsyncSession, findings: list[Finding], cycle_id: str) -> dict:
    open_rows = (await session.execute(select(Diagnostic).where(Diagnostic.status == "open"))).scalars().all()
    by_sig = {d.signature: d for d in open_rows}
    seen: set[str] = set()
    created, updated = 0, 0
    now = utcnow()
    for f in findings:
        seen.add(f.signature)
        row = by_sig.get(f.signature)
        if row:
            row.occurrences += 1
            row.last_seen_at = now
            row.evidence = {**f.evidence, "_action": f.action, "_template": f.template}
            row.detail = f.detail
            row.severity = f.severity
            row.title = f.title[:300]
            updated += 1
        else:
            session.add(Diagnostic(signature=f.signature, cycle_id=cycle_id, category=f.category, severity=f.severity,
                                   title=f.title[:300], detail=f.detail, evidence={**f.evidence, "_action": f.action,
                                                                                   "_template": f.template},
                                   suggestion=f.suggestion))
            created += 1
    resolved = 0
    for sig, row in by_sig.items():
        if sig not in seen:
            row.status = "resolved"
            row.resolved_at = now
            resolved += 1
    await session.flush()
    return {"created": created, "updated": updated, "resolved": resolved, "total_open": len(seen)}
