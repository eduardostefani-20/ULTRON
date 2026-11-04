"""Utilidades gerais."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def new_id() -> str:
    return uuid.uuid4().hex


def sha256(text: str | bytes) -> str:
    if isinstance(text, str):
        text = text.encode("utf-8")
    return hashlib.sha256(text).hexdigest()


def canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def truncate(text: str | None, limit: int) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[: limit - 20] + f"\n…[+{len(text) - limit + 20} chars]"


def tail(text: str | None, limit: int) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return f"[…{len(text) - limit} chars]\n" + text[-limit:]


def slugify(text: str, max_len: int = 40) -> str:
    text = text.lower()
    text = re.sub(r"[àáâãä]", "a", text)
    text = re.sub(r"[èéêë]", "e", text)
    text = re.sub(r"[ìíîï]", "i", text)
    text = re.sub(r"[òóôõö]", "o", text)
    text = re.sub(r"[ùúûü]", "u", text)
    text = re.sub(r"ç", "c", text)
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:max_len].strip("-") or "item"


_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),
    re.compile(r"xai-[A-Za-z0-9]{20,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{30,}"),
    re.compile(r"gsk_[A-Za-z0-9]{30,}"),
    re.compile(r"tvly-[A-Za-z0-9]{20,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)(password|senha|secret|api[_-]?key|token)\s*[:=]\s*['\"][^'\"\s]{8,}['\"]"),
]


def find_secrets(text: str) -> list[str]:
    """Detecta padrões de segredos (chaves de API, tokens, chaves privadas)."""
    hits: list[str] = []
    for pat in _SECRET_PATTERNS:
        for m in pat.finditer(text or ""):
            hits.append(m.group(0)[:12] + "…")
    return hits


def redact_secrets(text: str) -> str:
    out = text or ""
    for pat in _SECRET_PATTERNS:
        out = pat.sub("[REDACTED]", out)
    return out


def extract_json(text: str) -> Any:
    """Extrai o primeiro objeto/array JSON válido de um texto de modelo.

    Tolera blocos ```json, texto antes/depois e vírgulas finais simples.
    Lança ValueError se nada válido for encontrado.
    """
    if text is None:
        raise ValueError("resposta vazia")
    s = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", s, re.DOTALL)
    candidates = []
    if fence:
        candidates.append(fence.group(1).strip())
    candidates.append(s)
    for cand in candidates:
        try:
            return json.loads(cand)
        except Exception:
            pass
        # procura o primeiro bloco balanceado
        for opener, closer in (("{", "}"), ("[", "]")):
            start = cand.find(opener)
            while start != -1:
                depth = 0
                in_str = False
                esc = False
                for i in range(start, len(cand)):
                    ch = cand[i]
                    if in_str:
                        if esc:
                            esc = False
                        elif ch == "\\":
                            esc = True
                        elif ch == '"':
                            in_str = False
                        continue
                    if ch == '"':
                        in_str = True
                    elif ch == opener:
                        depth += 1
                    elif ch == closer:
                        depth -= 1
                        if depth == 0:
                            block = cand[start : i + 1]
                            try:
                                return json.loads(block)
                            except Exception:
                                cleaned = re.sub(r",\s*([}\]])", r"\1", block)
                                try:
                                    return json.loads(cleaned)
                                except Exception:
                                    break
                start = cand.find(opener, start + 1)
    raise ValueError("nenhum JSON válido encontrado na resposta do modelo")


def estimate_tokens(text: str) -> int:
    # aproximação conservadora (~3.5 caracteres/token para PT-BR e código)
    return max(1, int(len(text or "") / 3.5))
