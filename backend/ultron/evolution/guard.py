"""Guardião de escrita do Developer Agent (CÓDIGO DE GOVERNANÇA).

Toda edição gerada por IA passa por aqui: caminhos protegidos, travessia de diretório,
links simbólicos, binários e limites de tamanho são verificados antes de tocar o disco.
"""

from __future__ import annotations

from pathlib import Path

from ultron.governance.policy import check_agent_write, normalize_rel_path

MAX_FILE_BYTES = 200_000
MAX_EDITS = 25


class EditRejected(Exception):
    pass


def _resolve_inside(root: Path, rel: str) -> Path:
    norm = normalize_rel_path(rel)
    if norm is None:
        raise EditRejected(f"caminho inválido: {rel!r}")
    root_r = root.resolve()
    cur = root_r
    for part in Path(norm).parts:
        cur = cur / part
        if cur.is_symlink():
            raise EditRejected(f"links simbólicos não são permitidos: {rel}")
    target = (root_r / norm).resolve()
    if root_r not in target.parents:
        raise EditRejected(f"caminho fora do workspace: {rel}")
    return target


def apply_edits(root: Path, edits: list[dict]) -> tuple[list[str], list[dict]]:
    """Aplica edições em ``root`` (uma worktree). Retorna (aplicadas, rejeitadas)."""
    applied: list[str] = []
    rejected: list[dict] = []
    if not isinstance(edits, list):
        return [], [{"path": "?", "reason": "edits deve ser uma lista"}]
    for edit in edits[:MAX_EDITS]:
        path = str((edit or {}).get("path", ""))
        action = str((edit or {}).get("action", "write")).lower()
        try:
            decision = check_agent_write(path)
            if not decision.allowed:
                raise EditRejected(decision.reason)
            target = _resolve_inside(root, path)
            if action in ("write", "create"):
                content = edit.get("content")
                if not isinstance(content, str):
                    raise EditRejected("'content' ausente")
                if len(content.encode()) > MAX_FILE_BYTES:
                    raise EditRejected("arquivo grande demais")
                if "\x00" in content:
                    raise EditRejected("conteúdo binário não permitido")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content if content.endswith("\n") else content + "\n")
            elif action == "replace":
                find, repl = edit.get("find"), edit.get("replace")
                if not isinstance(find, str) or not isinstance(repl, str) or not find:
                    raise EditRejected("'find' e 'replace' são obrigatórios")
                if not target.is_file():
                    raise EditRejected("arquivo não existe para substituição")
                text = target.read_text()
                count = text.count(find)
                if count != 1:
                    raise EditRejected(f"o trecho 'find' deve ocorrer exatamente 1 vez (ocorre {count})")
                new = text.replace(find, repl, 1)
                if len(new.encode()) > MAX_FILE_BYTES:
                    raise EditRejected("arquivo grande demais")
                target.write_text(new)
            elif action == "delete":
                if not target.is_file():
                    raise EditRejected("arquivo não existe")
                target.unlink()
            else:
                raise EditRejected(f"ação desconhecida: {action}")
            applied.append(f"{action}:{normalize_rel_path(path)}")
        except EditRejected as e:
            rejected.append({"path": path, "action": action, "reason": str(e)})
        except OSError as e:
            rejected.append({"path": path, "action": action, "reason": f"erro de E/S: {e.__class__.__name__}"})
    if len(edits) > MAX_EDITS:
        rejected.append({"path": "*", "reason": f"apenas {MAX_EDITS} edições por iteração"})
    return applied, rejected
