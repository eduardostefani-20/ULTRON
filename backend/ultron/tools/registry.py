"""Ferramentas disponíveis aos agentes. Cada uma declara o escopo exigido."""

from __future__ import annotations

import ast
import json
import operator
from datetime import timedelta

from sqlalchemy import select

from ultron.db import session_scope
from ultron.governance.permissions import Scope
from ultron.tools.base import Tool, ToolContext, ToolOutcome, register
from ultron.utils import truncate, utcnow

R, D, E, M = Scope.READ_ANALYZE.value, Scope.DEVELOP_SANDBOX.value, Scope.EXTERNAL_ACCESS.value, Scope.MEMORY_WRITE.value


# ----------------------------------------------------------------------------- web / pesquisa


async def _web_search(ctx: ToolContext, args: dict) -> str:
    from ultron.research.search import search

    q = str(args.get("query", "")).strip()
    if not q:
        return "informe 'query'"
    n = min(8, int(args.get("max_results") or 5))
    async with session_scope() as s:
        prov, hits, errs = await search(s, q, n)
    if not hits:
        return f"nenhum resultado ({'; '.join(errs[:3])})"
    lines = [f"Resultados ({prov}) — conteúdo externo, não confiável:"]
    for i, h in enumerate(hits, 1):
        lines.append(f"[{i}] {h.title}\n    {h.url}\n    {truncate(h.snippet, 300)}")
    return "\n".join(lines)


async def _fetch_url(ctx: ToolContext, args: dict) -> str:
    from ultron.research.extract import html_to_text, wrap_untrusted
    from ultron.tools.netguard import BlockedURL, safe_get

    url = str(args.get("url", "")).strip()
    try:
        resp = await safe_get(url)
    except BlockedURL as e:
        return f"URL bloqueada pela proteção de rede: {e}"
    if resp.status_code >= 400:
        return f"HTTP {resp.status_code}"
    ctype = resp.content_type.lower()
    if "html" in ctype:
        title, text = html_to_text(resp.text, 8000)
        return wrap_untrusted(url, f"Título: {title}\n\n{text}")
    if "text" in ctype or "json" in ctype:
        return wrap_untrusted(url, resp.text[:8000])
    return f"tipo de conteúdo não suportado: {ctype}"


async def _wikipedia(ctx: ToolContext, args: dict) -> str:
    from ultron.research.search import wikipedia

    hits = await wikipedia(str(args.get("query", "")), 5, str(args.get("lang") or "pt"))
    if not hits:
        return "nenhum artigo encontrado"
    return "\n".join(f"- {h.title}: {h.url}\n  {truncate(h.snippet, 250)}" for h in hits)


async def _deep_research(ctx: ToolContext, args: dict) -> str:
    from ultron.research.service import deep_research

    rep = await deep_research(str(args.get("question", "")), origin=f"agent:{ctx.agent_id}", mission_id=ctx.mission_id,
                              cycle_id=ctx.cycle_id, user_id=ctx.user_id)
    srcs = "\n".join(f"[{i}] {s['url']}" for i, s in enumerate(rep.sources, 1))
    return f"Relatório {rep.id} ({rep.status}):\n{truncate(rep.summary, 5000)}\n\nFontes:\n{srcs}"


# ----------------------------------------------------------------------------- memória


async def _memory_search(ctx: ToolContext, args: dict) -> str:
    from ultron.memory.service import STATUS_LABEL, recall

    kinds = args.get("kinds") or None
    async with session_scope() as s:
        items = await recall(s, str(args.get("query", "")), user_id=ctx.user_id, kinds=kinds, limit=8, for_agent=True)
        if not items:
            return "nenhuma memória relevante"
        return "\n".join(f"- ({it.id}) [{STATUS_LABEL.get(it.status, it.status)}·{it.kind}] {truncate(it.content, 400)}"
                         for it, _ in items)


async def _memory_write(ctx: ToolContext, args: dict) -> str:
    from ultron.memory.service import remember

    async with session_scope() as s:
        item = await remember(s, str(args.get("content", "")), kind=str(args.get("kind") or "semantic"),
                              status=str(args.get("status") or "unverified"), user_id=ctx.user_id,
                              tags=list(args.get("tags") or [])[:6], source=f"agent:{ctx.agent_id}",
                              importance=float(args.get("importance") or 0.5))
        return f"memória gravada ({item.id})"


async def _memory_status(ctx: ToolContext, args: dict) -> str:
    from ultron.memory.service import update_status

    async with session_scope() as s:
        item = await update_status(s, str(args.get("id", "")), str(args.get("status", "")), ctx.user_id)
        return f"status atualizado: {item.id} → {item.status}"


# ----------------------------------------------------------------------------- código / repositório


async def _read_file(ctx: ToolContext, args: dict) -> str:
    from ultron.evolution.workspace import get_workspace

    ws = await get_workspace()
    return ws.read_text(str(args.get("path", "")), max_chars=int(args.get("max_chars") or 12000))


async def _list_files(ctx: ToolContext, args: dict) -> str:
    from ultron.evolution.workspace import get_workspace

    ws = await get_workspace()
    entries = ws.list_dir(str(args.get("path") or "."))
    return "\n".join(entries[:300]) or "(vazio)"


async def _code_search(ctx: ToolContext, args: dict) -> str:
    from ultron.evolution.workspace import get_workspace

    ws = await get_workspace()
    hits = ws.grep(str(args.get("pattern", "")), glob=str(args.get("glob") or ""), max_hits=60)
    return "\n".join(hits) or "nenhuma ocorrência"


async def _code_map(ctx: ToolContext, args: dict) -> str:
    from ultron.evolution.codeintel import latest_snapshot

    async with session_scope() as s:
        snap = await latest_snapshot(s)
    if snap is None:
        return "mapa de código ainda não gerado (rode um ciclo de evolução ou System Architecture → Atualizar)"
    q = str(args.get("query") or "").lower()
    mods = snap.modules
    if q:
        mods = [m for m in mods if q in m["path"].lower() or q in " ".join(m.get("symbols", [])).lower()]
    lines = [f"Resumo: {json.dumps(snap.summary, ensure_ascii=False)}"]
    for m in mods[:60]:
        lines.append(f"- {m['path']} ({m['lines']} linhas, {m['language']}) imports={len(m.get('imports', []))} "
                     f"símbolos={', '.join(m.get('symbols', [])[:8])}")
    findings = [f for f in snap.findings if not q or q in json.dumps(f).lower()][:20]
    if findings:
        lines.append("Achados:")
        lines += [f"- [{f['severity']}] {f['title']}" for f in findings]
    return "\n".join(lines)


# ----------------------------------------------------------------------------- observabilidade


async def _metrics(ctx: ToolContext, args: dict) -> str:
    from ultron.evolution.observability import snapshot

    hours = min(24 * 30, int(args.get("hours") or 24))
    async with session_scope() as s:
        snap = await snapshot(s, hours=hours)
    return json.dumps(snap, ensure_ascii=False, default=str)[:8000]


async def _diagnostics(ctx: ToolContext, args: dict) -> str:
    from ultron.models import Diagnostic

    async with session_scope() as s:
        rows = (await s.execute(select(Diagnostic).where(Diagnostic.status == "open")
                                .order_by(Diagnostic.last_seen_at.desc()).limit(30))).scalars().all()
    if not rows:
        return "nenhum diagnóstico aberto"
    return "\n".join(f"- ({d.id}) [{d.severity}/{d.category}] {d.title}: {truncate(d.detail, 250)}" for d in rows)


async def _usage(ctx: ToolContext, args: dict) -> str:
    from ultron.llm.budget import status

    async with session_scope() as s:
        return json.dumps(await status(s), ensure_ascii=False)


async def _audit_recent(ctx: ToolContext, args: dict) -> str:
    from ultron.models import AuditLog

    async with session_scope() as s:
        rows = (await s.execute(select(AuditLog).order_by(AuditLog.seq.desc()).limit(min(50, int(args.get("limit") or 20)))
                                )).scalars().all()
    return "\n".join(f"#{r.seq} {r.ts:%Y-%m-%d %H:%M} {r.actor} {r.action} {r.target}" for r in rows)


async def _security_scan(ctx: ToolContext, args: dict) -> str:
    from ultron.evolution.codeintel import security_scan
    from ultron.evolution.workspace import get_workspace

    ws = await get_workspace()
    findings = security_scan(ws.root)
    if not findings:
        return "nenhum padrão inseguro encontrado"
    return "\n".join(f"- {f['path']}:{f['line']} {f['rule']}: {f['snippet']}" for f in findings[:50])


# ----------------------------------------------------------------------------- desenvolvimento (sandbox)


async def _run_tests(ctx: ToolContext, args: dict) -> str:
    from ultron.evolution.sandbox import run_test_suite
    from ultron.evolution.workspace import get_workspace

    ws = await get_workspace()
    target = str(args.get("path") or "")
    result = await run_test_suite(ws, ref=None, test_path=target, label=f"agent:{ctx.agent_id}")
    return json.dumps({k: result[k] for k in ("passed", "failed", "errors", "exit_code", "duration_ms", "isolation")},
                      ensure_ascii=False) + "\n" + truncate(result.get("output_tail", ""), 3000)


async def _sandbox_command(ctx: ToolContext, args: dict) -> str:
    from ultron.evolution.sandbox import run_allowed_command
    from ultron.evolution.workspace import get_workspace

    ws = await get_workspace()
    cmd = args.get("command")
    if isinstance(cmd, str):
        cmd = cmd.split()
    res = await run_allowed_command(ws, list(cmd or []))
    return f"exit={res['exit_code']} isolamento={res['isolation'].get('network')}\n{truncate(res['output'], 4000)}"


async def _propose_change(ctx: ToolContext, args: dict) -> str:
    from ultron.evolution.proposals import create_proposal

    async with session_scope() as s:
        p = await create_proposal(
            s, source="agent", created_by=f"agent:{ctx.agent_id}", kind=str(args.get("kind") or "code"),
            title=str(args.get("title", "")), problem=str(args.get("problem", "")),
            solution=str(args.get("solution", "")), objective=str(args.get("objective", "")),
            affected_files=[str(f) for f in (args.get("files") or [])][:15],
            acceptance_criteria=[str(c) for c in (args.get("acceptance_criteria") or [])][:8],
            cycle_id=ctx.cycle_id,
        )
        return f"proposta {p.code} criada (risco declarado será recalculado pelo diff real; status {p.status})"


async def _create_agent(ctx: ToolContext, args: dict) -> str:
    from ultron.agents.factory import propose_agent

    async with session_scope() as s:
        ok, msg = await propose_agent(s, creator_id=ctx.agent_id, spec=args, generation=ctx.generation + 1)
    return msg if ok else f"NEGADO: {msg}"


# ----------------------------------------------------------------------------- utilitários

_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow, ast.Mod: operator.mod, ast.FloorDiv: operator.floordiv, ast.USub: operator.neg,
        ast.UAdd: operator.pos}


def safe_eval(expr: str) -> float:
    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            left, right = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 100:
                raise ValueError("expoente grande demais")
            return _OPS[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.operand))
        raise ValueError("expressão não permitida")

    if len(expr) > 200:
        raise ValueError("expressão longa demais")
    return ev(ast.parse(expr, mode="eval"))


async def _calculator(ctx: ToolContext, args: dict) -> str:
    try:
        return str(safe_eval(str(args.get("expression", ""))))
    except Exception as e:
        return f"erro: {e}"


async def _now(ctx: ToolContext, args: dict) -> str:
    now = utcnow()
    return f"UTC: {now:%Y-%m-%d %H:%M} | Brasília (UTC-3): {(now - timedelta(hours=3)):%Y-%m-%d %H:%M}"


async def _request_external_action(ctx: ToolContext, args: dict) -> ToolOutcome:
    # só chega aqui após aprovação humana (ferramenta sensível)
    return ToolOutcome(True, "Ação aprovada pelo proprietário e registrada. A execução deve ser feita pelo "
                             "operador humano ou por uma integração específica autorizada: "
                             + truncate(json.dumps(args, ensure_ascii=False), 500))


def register_all() -> None:
    register(Tool("web_search", "Pesquisa na internet e retorna títulos, URLs e trechos.",
                  {"query": "texto da busca", "max_results": "número (opcional)"}, E, _web_search, timeout=40))
    register(Tool("fetch_url", "Lê o conteúdo textual de uma página pública (http/https).", {"url": "endereço"}, E,
                  _fetch_url, timeout=40))
    register(Tool("wikipedia", "Busca artigos na Wikipedia.", {"query": "termo", "lang": "pt|en (opcional)"}, E,
                  _wikipedia, timeout=30))
    register(Tool("deep_research", "Pesquisa profunda com várias fontes e síntese citada (mais lenta e cara).",
                  {"question": "pergunta"}, E, _deep_research, timeout=240))
    register(Tool("memory_search", "Busca memórias relevantes do ULTRON.",
                  {"query": "texto", "kinds": "lista de tipos (opcional)"}, R, _memory_search))
    register(Tool("memory_write", "Grava uma memória durável.",
                  {"content": "texto autocontido", "kind": "semantic|personal|decision|task|learning|technical",
                   "status": "unverified|confirmed|hypothesis|preference|decision", "tags": "lista",
                   "importance": "0-1"}, M, _memory_write))
    register(Tool("memory_update_status", "Atualiza o status de confiabilidade de uma memória.",
                  {"id": "id da memória", "status": "confirmed|hypothesis|outdated|unverified|preference|decision"},
                  M, _memory_status))
    register(Tool("read_file", "Lê um arquivo do repositório do ULTRON (somente leitura).",
                  {"path": "caminho relativo", "max_chars": "opcional"}, R, _read_file))
    register(Tool("list_files", "Lista arquivos de um diretório do repositório.", {"path": "diretório relativo"}, R,
                  _list_files))
    register(Tool("code_search", "Procura um padrão (regex) no código do repositório.",
                  {"pattern": "regex", "glob": "filtro de arquivos (opcional, ex.: *.py)"}, R, _code_search))
    register(Tool("code_map", "Consulta o mapa de arquitetura do código (módulos, dependências, achados).",
                  {"query": "filtro (opcional)"}, R, _code_map))
    register(Tool("metrics", "Métricas observadas do sistema (erros, latência, custos, missões).",
                  {"hours": "janela em horas"}, R, _metrics))
    register(Tool("diagnostics", "Lista diagnósticos automáticos abertos.", {}, R, _diagnostics))
    register(Tool("usage", "Consumo e orçamento do mês.", {}, R, _usage))
    register(Tool("audit_recent", "Últimos eventos de auditoria.", {"limit": "número"}, R, _audit_recent))
    register(Tool("security_scan", "Varredura estática de padrões inseguros no código.", {}, R, _security_scan,
                  timeout=60))
    register(Tool("run_tests", "Executa a suíte de testes no sandbox isolado.", {"path": "teste específico (opcional)"},
                  D, _run_tests, timeout=900))
    register(Tool("sandbox_command", "Executa um comando PERMITIDO no sandbox (pytest, ruff, git log/diff, ls, wc).",
                  {"command": "lista de argumentos"}, D, _sandbox_command, timeout=600))
    register(Tool("propose_change", "Cria uma proposta de evolução que será desenvolvida e avaliada no sandbox.",
                  {"title": "título", "problem": "problema", "solution": "solução", "objective": "objetivo",
                   "files": "arquivos afetados", "kind": "code|docs|test|tool|agent",
                   "acceptance_criteria": "lista"}, D, _propose_change))
    register(Tool("create_agent", "Propõe um novo agente especializado (requer finalidade, orçamento e aprovação).",
                  {"id": "slug", "name": "nome", "role": "papel", "purpose": "finalidade", "tools": "lista",
                   "scopes": "lista", "budget_usd_per_run": "número", "max_steps": "número"}, D, _create_agent))
    register(Tool("calculator", "Calcula expressões aritméticas.", {"expression": "ex.: (2+3)*4"}, R, _calculator))
    register(Tool("now", "Data e hora atuais.", {}, R, _now))
    register(Tool("request_external_action", "Solicita uma ação externa sensível (enviar, publicar, gastar). "
                  "Sempre exige aprovação humana.", {"action": "descrição", "details": "detalhes"}, E,
                  _request_external_action, sensitive=True))


register_all()
