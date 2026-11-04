"""Inteligência de código: o ULTRON conhece o próprio repositório.

Mapeia arquivos, módulos, dependências, funções/componentes, complexidade, duplicações,
módulos sem uso, ciclos de importação, módulos sem testes e padrões inseguros. O mapa é
refeito sempre que o commit do workspace muda.
"""

from __future__ import annotations

import ast
import hashlib
import re
from collections import defaultdict
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ultron.models import CodeMapSnapshot
from ultron.utils import find_secrets

CODE_EXTS = (".py", ".ts", ".tsx", ".js", ".mjs")
SKIP = {".git", "node_modules", ".next", "out", ".venv", "venv", "__pycache__", "data", "dist", "build",
        ".pytest_cache", ".ruff_cache"}
GENERATED_DOC = "docs/ARQUITETURA_GERADA.md"
ENTRYPOINTS = {"backend/ultron/main.py", "backend/ultron/__init__.py", "backend/alembic/env.py"}
TS_IMPORT = re.compile(r"""(?:import|export)\s+(?:[^'"]*?\s+from\s+)?['"]([^'"]+)['"]""")
TS_SYMBOL = re.compile(r"export\s+(?:default\s+)?(?:async\s+)?(?:function|const|class|interface|type)\s+([A-Za-z0-9_]+)")
SECURITY_RULES = [
    ("eval/exec", re.compile(r"(?<![\w.])(eval|exec)\s*\(")),
    ("shell=True", re.compile(r"shell\s*=\s*True")),
    ("pickle", re.compile(r"\bpickle\.loads?\(")),
    ("yaml.load inseguro", re.compile(r"yaml\.load\((?!.*Loader)")),
    ("TLS desativado", re.compile(r"verify\s*=\s*False")),
    ("os.system", re.compile(r"\bos\.system\(")),
    ("hash fraco para senha", re.compile(r"(?i)(md5|sha1)\(.*(senha|password)")),
    ("SQL montado com f-string", re.compile(r"execute\(\s*f[\"']")),
    ("dangerouslySetInnerHTML", re.compile(r"dangerouslySetInnerHTML")),
]


def _complexity(node: ast.AST) -> int:
    c = 1
    for n in ast.walk(node):
        if isinstance(n, ast.If | ast.For | ast.While | ast.AsyncFor | ast.With | ast.AsyncWith | ast.ExceptHandler |
                      ast.IfExp | ast.comprehension | ast.Match):
            c += 1
        elif isinstance(n, ast.BoolOp):
            c += len(n.values) - 1
    return c


def _py_module_name(rel: str) -> str | None:
    if not rel.startswith("backend/") or not rel.endswith(".py"):
        return None
    mod = rel[len("backend/"):-3].replace("/", ".")
    return mod[: -len(".__init__")] if mod.endswith(".__init__") else mod


def _iter(root: Path):
    for p in sorted(root.rglob("*")):
        if any(part in SKIP for part in p.relative_to(root).parts):
            continue
        if p.is_file() and p.suffix in CODE_EXTS:
            yield p.relative_to(root).as_posix(), p


def analyze_repo(root: Path) -> dict:
    modules: list[dict] = []
    py_index: dict[str, str] = {}
    raw_imports: dict[str, list[str]] = {}
    windows: dict[str, list[tuple[str, int]]] = defaultdict(list)
    findings: list[dict] = []
    test_text = ""
    test_functions = 0
    for rel, p in _iter(root):
        try:
            text = p.read_text(errors="replace")
        except OSError:
            continue
        lines = text.splitlines()
        info: dict = {"path": rel, "language": "python" if rel.endswith(".py") else "typescript",
                      "lines": len(lines), "symbols": [], "imports": [], "functions": 0, "classes": 0,
                      "max_complexity": 0, "todo": len(re.findall(r"\b(TODO|FIXME|XXX)\b", text)),
                      "is_test": "/tests/" in rel or rel.split("/")[-1].startswith("test_")}
        if info["is_test"]:
            test_text += text + "\n"
        if rel.endswith(".py"):
            mod = _py_module_name(rel)
            if mod:
                py_index[mod] = rel
            try:
                tree = ast.parse(text)
            except SyntaxError as e:
                findings.append({"severity": "high", "kind": "syntax_error", "path": rel,
                                 "title": f"Erro de sintaxe em {rel}", "detail": str(e)})
                modules.append(info)
                continue
            imps = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imps += [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    base = node.module or ""
                    if node.level and mod:
                        pkg = mod.split(".")
                        pkg = pkg[: len(pkg) - node.level + (1 if rel.endswith("__init__.py") else 0)]
                        base = ".".join(pkg + ([base] if base else []))
                    imps.append(base)
                    imps += [f"{base}.{a.name}" for a in node.names]
            raw_imports[rel] = imps
            for node in tree.body:
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                    info["symbols"].append(node.name)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                    info["functions"] += 1
                    if info["is_test"] and node.name.startswith("test_"):
                        test_functions += 1
                    cx = _complexity(node)
                    if cx > info["max_complexity"]:
                        info["max_complexity"] = cx
                        info["most_complex"] = node.name
                elif isinstance(node, ast.ClassDef):
                    info["classes"] += 1
            info["docstring"] = bool(ast.get_docstring(tree))
        else:
            raw_imports[rel] = TS_IMPORT.findall(text)
            info["symbols"] = TS_SYMBOL.findall(text)[:30]
            info["functions"] = len(re.findall(r"\bfunction\b|=>", text))
        modules.append(info)
        # janelas para detecção de duplicação (código não trivial)
        norm = [re.sub(r"\s+", " ", ln.strip()) for ln in lines]
        for i in range(0, max(0, len(norm) - 7)):
            win = norm[i : i + 8]
            if sum(len(x) > 12 for x in win) < 7 or any(x.startswith(("import ", "from ", "#", "//")) for x in win):
                continue
            h = hashlib.sha1("\n".join(win).encode(), usedforsecurity=False).hexdigest()
            windows[h].append((rel, i + 1))

    # resolução de dependências internas
    paths = {m["path"] for m in modules}
    edges: set[tuple[str, str]] = set()
    for rel, imps in raw_imports.items():
        for imp in imps:
            target = None
            if rel.endswith(".py"):
                if imp in py_index:
                    target = py_index[imp]
            else:
                if imp.startswith("@/"):
                    base = "frontend/src/" + imp[2:]
                elif imp.startswith("."):
                    base = str(Path(rel).parent / imp)
                    base = re.sub(r"/\./", "/", base)
                    parts: list[str] = []
                    for part in base.split("/"):
                        if part == "..":
                            if parts:
                                parts.pop()
                        elif part != ".":
                            parts.append(part)
                    base = "/".join(parts)
                else:
                    continue
                for cand in (base, base + ".ts", base + ".tsx", base + "/index.ts", base + "/index.tsx", base + ".js"):
                    if cand in paths:
                        target = cand
                        break
            if target and target != rel:
                edges.add((rel, target))
    by_path = {m["path"]: m for m in modules}
    for a, b in edges:
        by_path[a]["imports"].append(b)
    imported_by: dict[str, int] = defaultdict(int)
    for _a, b in edges:
        imported_by[b] += 1
    for m in modules:
        m["imported_by"] = imported_by.get(m["path"], 0)

    # achados
    for m in modules:
        if m["is_test"]:
            continue
        if m["lines"] > 600:
            findings.append({"severity": "medium", "kind": "large_file", "path": m["path"],
                             "title": f"Arquivo grande: {m['path']} ({m['lines']} linhas)",
                             "detail": "Considere dividir em módulos menores."})
        if m.get("max_complexity", 0) > 20:
            findings.append({"severity": "medium", "kind": "complexity", "path": m["path"],
                             "title": f"Função complexa: {m.get('most_complex')} em {m['path']} "
                                      f"(complexidade {m['max_complexity']})",
                             "detail": "Funções muito ramificadas são difíceis de testar e manter."})
        if m["language"] == "python" and m["path"].startswith("backend/ultron/"):
            mod = _py_module_name(m["path"]) or ""
            stem = Path(m["path"]).stem
            if (stem != "__init__" and m["imported_by"] == 0 and m["path"] not in ENTRYPOINTS
                    and mod not in test_text and not m["path"].startswith("backend/ultron/api/")):
                findings.append({"severity": "low", "kind": "unused_module", "path": m["path"],
                                 "title": f"Módulo possivelmente sem uso: {m['path']}",
                                 "detail": "Nenhum outro módulo o importa."})
            if stem != "__init__" and m["lines"] > 40 and mod not in test_text and f"import {stem}" not in test_text:
                findings.append({"severity": "low", "kind": "untested_module", "path": m["path"],
                                 "title": f"Módulo sem teste dedicado: {m['path']}",
                                 "detail": "Nenhum teste referencia este módulo diretamente."})

    # duplicações (blocos em arquivos ou regiões distintas)
    dup_pairs: dict[tuple[str, str], int] = defaultdict(int)
    for occ in windows.values():
        if len(occ) < 2:
            continue
        files = sorted({o[0] for o in occ})
        if len(files) >= 2:
            dup_pairs[(files[0], files[1])] += 1
    for (a, b), n in sorted(dup_pairs.items(), key=lambda kv: -kv[1])[:8]:
        if n >= 3:
            findings.append({"severity": "low", "kind": "duplication", "path": a,
                             "title": f"Código duplicado entre {a} e {b} (~{n + 7} linhas)",
                             "detail": "Blocos idênticos sugerem extrair uma função comum."})

    # ciclos de importação (Tarjan)
    graph: dict[str, list[str]] = defaultdict(list)
    for a, b in edges:
        graph[a].append(b)
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on: set[str] = set()
    sccs: list[list[str]] = []
    counter = [0]

    def strong(v: str) -> None:
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on.add(v)
        for w in graph.get(v, []):
            if w not in index:
                strong(w)
                low[v] = min(low[v], low[w])
            elif w in on:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp = []
            while True:
                w = stack.pop()
                on.discard(w)
                comp.append(w)
                if w == v:
                    break
            if len(comp) > 1:
                sccs.append(sorted(comp))

    import sys

    old = sys.getrecursionlimit()
    sys.setrecursionlimit(max(old, 10000))
    try:
        for v in list(graph):
            if v not in index:
                strong(v)
    finally:
        sys.setrecursionlimit(old)
    for comp in sccs[:5]:
        findings.append({"severity": "low", "kind": "import_cycle", "path": comp[0],
                         "title": f"Ciclo de importação entre {len(comp)} módulos",
                         "detail": " → ".join(comp[:6])})

    py = [m for m in modules if m["language"] == "python"]
    ts = [m for m in modules if m["language"] != "python"]
    summary = {
        "files": len(modules), "lines": sum(m["lines"] for m in modules),
        "python_modules": len(py), "typescript_modules": len(ts),
        "functions": sum(m["functions"] for m in py), "classes": sum(m["classes"] for m in py),
        "test_files": sum(1 for m in modules if m["is_test"]), "test_functions": test_functions,
        "dependencies": len(edges), "todo": sum(m["todo"] for m in modules),
        "findings": len(findings), "import_cycles": len(sccs),
    }
    return {"summary": summary, "modules": modules, "edges": [{"from": a, "to": b} for a, b in sorted(edges)],
            "findings": findings}


def security_scan(root: Path) -> list[dict]:
    out: list[dict] = []
    for rel, p in _iter(root):
        if "/tests/" in rel:
            continue
        try:
            lines = p.read_text(errors="replace").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines, 1):
            if "noqa" in line or line.strip().startswith(("#", "//")):
                continue
            for name, rx in SECURITY_RULES:
                if rx.search(line):
                    out.append({"path": rel, "line": i, "rule": name, "snippet": line.strip()[:160]})
            if find_secrets(line):
                out.append({"path": rel, "line": i, "rule": "possível segredo no código", "snippet": "[oculto]"})
    return out


async def refresh(session: AsyncSession, root: Path, commit_sha: str, force: bool = False) -> CodeMapSnapshot:
    latest = await latest_snapshot(session)
    if latest and latest.commit_sha == commit_sha and not force:
        return latest
    data = analyze_repo(root)
    snap = CodeMapSnapshot(commit_sha=commit_sha, summary=data["summary"], modules=data["modules"],
                           edges=data["edges"], findings=data["findings"])
    session.add(snap)
    await session.flush()
    return snap


async def latest_snapshot(session: AsyncSession) -> CodeMapSnapshot | None:
    return (await session.execute(select(CodeMapSnapshot).order_by(CodeMapSnapshot.created_at.desc()).limit(1))
            ).scalar_one_or_none()


def render_architecture_doc(data: dict) -> str:
    """Documento determinístico da arquitetura (sem datas, para ser estável entre execuções)."""
    s = data["summary"]
    lines = [
        "# Arquitetura gerada automaticamente",
        "",
        "> Documento mantido pelo Documentation Agent do ULTRON a partir da análise estática do código.",
        "> Não edite manualmente: ele é regenerado quando o código muda.",
        "",
        "## Resumo",
        "",
        "| Métrica | Valor |",
        "|---|---|",
    ]
    labels = {"files": "Arquivos de código", "lines": "Linhas", "python_modules": "Módulos Python",
              "typescript_modules": "Módulos TypeScript", "functions": "Funções (Python)", "classes": "Classes",
              "test_files": "Arquivos de teste", "test_functions": "Funções de teste", "dependencies":
              "Dependências internas", "import_cycles": "Ciclos de importação"}
    for k, label in labels.items():
        lines.append(f"| {label} | {s.get(k, 0)} |")
    groups: dict[str, list[dict]] = defaultdict(list)
    for m in data["modules"]:
        parts = m["path"].split("/")
        key = "/".join(parts[:3]) if parts[0] == "backend" and len(parts) > 3 else "/".join(parts[:2])
        groups[key].append(m)
    lines += ["", "## Módulos por pacote", ""]
    for key in sorted(groups):
        mods = groups[key]
        lines.append(f"### `{key}` — {len(mods)} arquivo(s), {sum(m['lines'] for m in mods)} linhas")
        lines.append("")
        for m in sorted(mods, key=lambda x: x["path"]):
            syms = ", ".join(m["symbols"][:6])
            lines.append(f"- `{m['path']}` · {m['lines']} linhas · usado por {m['imported_by']}"
                         + (f" · {syms}" if syms else ""))
        lines.append("")
    hubs = sorted(data["modules"], key=lambda m: -m["imported_by"])[:10]
    lines += ["## Módulos mais centrais (mais importados)", ""]
    lines += [f"{i}. `{m['path']}` — importado por {m['imported_by']}" for i, m in enumerate(hubs, 1)]
    lines += ["", "## Achados da análise estática", ""]
    kinds: dict[str, int] = defaultdict(int)
    for f in data["findings"]:
        kinds[f["kind"]] += 1
    if kinds:
        lines += [f"- {k}: {v}" for k, v in sorted(kinds.items())]
    else:
        lines.append("- nenhum")
    return "\n".join(lines) + "\n"
