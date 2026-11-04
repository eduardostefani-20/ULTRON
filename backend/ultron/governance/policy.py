"""Política de segurança imutável do ULTRON.

Este módulo é CÓDIGO DE GOVERNANÇA: agentes não podem modificá-lo (o guardião de
caminhos bloqueia a escrita e o avaliador reprova qualquer diff que o toque). A
classificação de risco é calculada a partir do diff real do git, nunca a partir do que
o agente declara.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass, field
from enum import StrEnum

from ultron.utils import find_secrets


class Risk(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


RISK_ORDER = {Risk.LOW: 0, Risk.MEDIUM: 1, Risk.HIGH: 2}


def max_risk(a: Risk, b: Risk) -> Risk:
    return a if RISK_ORDER[a] >= RISK_ORDER[b] else b


# Caminhos que NENHUM agente pode escrever, nem com aprovação.
# Mudanças aqui só podem ser feitas por humanos, diretamente no repositório.
FORBIDDEN_PATHS: tuple[str, ...] = (
    "backend/ultron/governance/**",
    "backend/ultron/security/**",
    "backend/ultron/evolution/guard.py",
    "backend/ultron/evolution/sandbox.py",
    "backend/ultron/evolution/evaluation.py",
    "backend/ultron/evolution/publisher.py",
    "backend/ultron/evolution/selftest.py",
    "backend/ultron/settings_store.py",
    "backend/ultron/llm/budget.py",
    "backend/ultron/tools/netguard.py",
    "backend/tests/security/**",
    ".github/**",
    "CODEOWNERS",
    ".git/**",
    "**/.git/**",
    ".env",
    "**/.env",
    "**/.env.*",
    "**/secret.key",
    "backend/data/**",
)

# Alto risco: aprovação humana obrigatória (autenticação, credenciais, infraestrutura,
# dependências, banco, permissões, orçamento, rede, publicação).
HIGH_RISK_PATHS: tuple[str, ...] = (
    "backend/ultron/api/auth.py",
    "backend/ultron/api/deps.py",
    "backend/ultron/api/integrations.py",
    "backend/ultron/api/settings.py",
    "backend/ultron/config.py",
    "backend/ultron/main.py",
    "backend/ultron/db.py",
    "backend/ultron/evolution/workspace.py",
    "backend/ultron/evolution/scheduler.py",
    "backend/ultron/evolution/github.py",
    "backend/alembic/**",
    "backend/alembic.ini",
    "backend/pyproject.toml",
    "backend/uv.lock",
    "backend/requirements*.txt",
    "frontend/package.json",
    "frontend/package-lock.json",
    "frontend/next.config.*",
    "frontend/public/sw.js",
    "Dockerfile",
    "**/Dockerfile",
    "docker-compose*.yml",
    "render.yaml",
    "netlify.toml",
    "scripts/**",
)

# Baixo risco: documentação, interface e testes novos.
LOW_RISK_PATHS: tuple[str, ...] = (
    "docs/**",
    "*.md",
    "**/*.md",
    "frontend/src/app/**",
    "frontend/src/components/**",
    "frontend/public/**",
    "backend/tests/**",
)

CODE_EXTENSIONS = (".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".sh", ".yml", ".yaml", ".toml", ".sql")
BINARY_EXTENSIONS = (
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".gz", ".tar", ".so", ".dll", ".exe",
    ".bin", ".pyc", ".whl", ".db", ".sqlite", ".woff", ".woff2",
)

# Padrões de conteúdo que elevam o risco para ALTO quando adicionados em código.
ESCALATION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("execução de processos", re.compile(r"\bsubprocess\b|\bos\.system\b|\bos\.popen\b|\bos\.exec|\bpty\.spawn\b")),
    ("execução dinâmica de código", re.compile(r"(?<![\w.])(eval|exec|compile)\s*\(|__import__\s*\(")),
    ("desserialização insegura", re.compile(r"\bpickle\.loads?\b|\bmarshal\.loads?\b|yaml\.load\((?!.*SafeLoader)")),
    ("acesso de baixo nível", re.compile(r"\bctypes\b|\bsocket\.socket\b")),
    ("shell=True", re.compile(r"shell\s*=\s*True")),
    ("TLS desativado", re.compile(r"verify\s*=\s*False|rejectUnauthorized\s*:\s*false|NODE_TLS_REJECT_UNAUTHORIZED")),
    ("remoção recursiva", re.compile(r"shutil\.rmtree|rm\s+-rf")),
    ("SQL destrutivo", re.compile(r"(?i)\b(drop\s+table|truncate\s+table|delete\s+from\s+audit_log)\b")),
    ("acesso a segredos do ambiente", re.compile(r"os\.environ\b|process\.env\b|getenv\s*\(")),
    ("referência a escopos de publicação", re.compile(r"Scope\.PUBLISH|\"publish\"\s*:")),
    ("alteração de permissões", re.compile(r"\bos\.chmod\b|\bos\.setuid\b|\bsudo\b")),
)

MAX_LOW_RISK_LINES = 400
MAX_LOW_RISK_FILES = 10
MAX_TOTAL_LINES = 3000
MAX_TOTAL_FILES = 40


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    i, out = 0, ""
    while i < len(pattern):
        c = pattern[i]
        if pattern.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
            continue
        if pattern.startswith("**", i):
            out += ".*"
            i += 2
            continue
        if c == "*":
            out += "[^/]*"
        elif c == "?":
            out += "[^/]"
        else:
            out += re.escape(c)
        i += 1
    return re.compile("^" + out + "$")


_compiled: dict[str, re.Pattern[str]] = {}


def path_matches(path: str, patterns: tuple[str, ...]) -> str | None:
    for p in patterns:
        rx = _compiled.get(p)
        if rx is None:
            rx = _compiled[p] = _glob_to_regex(p)
        if rx.match(path):
            return p
    return None


def normalize_rel_path(path: str) -> str | None:
    """Normaliza um caminho relativo ao repositório. Retorna None se for inseguro."""
    if not path or "\x00" in path or "\\" in path:
        return None
    if path.startswith("/") or re.match(r"^[A-Za-z]:", path):
        return None
    norm = posixpath.normpath(path)
    if norm.startswith("..") or norm in (".", "") or "/../" in f"/{norm}/":
        return None
    return norm


@dataclass
class PathDecision:
    allowed: bool
    reason: str = ""
    risk: Risk = Risk.MEDIUM


def check_agent_write(path: str) -> PathDecision:
    """Decide se um agente pode escrever no caminho (relativo à raiz do repositório)."""
    norm = normalize_rel_path(path)
    if norm is None:
        return PathDecision(False, f"caminho inseguro ou fora do repositório: {path!r}")
    hit = path_matches(norm, FORBIDDEN_PATHS)
    if hit:
        return PathDecision(False, f"caminho protegido pela governança ({hit}) — somente humanos podem alterar")
    if norm.lower().endswith(BINARY_EXTENSIONS):
        return PathDecision(False, "arquivos binários não podem ser gerados por agentes")
    return PathDecision(True, "", path_risk(norm, "M"))


def path_risk(path: str, status: str = "M") -> Risk:
    if path_matches(path, FORBIDDEN_PATHS):
        return Risk.HIGH
    if path_matches(path, HIGH_RISK_PATHS):
        return Risk.HIGH
    if path_matches(path, LOW_RISK_PATHS):
        # modificar ou apagar testes existentes não é baixo risco (poderia enfraquecê-los)
        if path.startswith("backend/tests/") and status != "A":
            return Risk.MEDIUM
        if status == "D":
            return Risk.MEDIUM
        return Risk.LOW
    return Risk.MEDIUM


@dataclass
class FileChange:
    path: str
    status: str  # A (adicionado) | M (modificado) | D (removido) | R (renomeado)
    added_lines: list[str] = field(default_factory=list)
    removed_count: int = 0
    old_path: str = ""


@dataclass
class RiskAssessment:
    level: Risk
    reasons: list[str]
    blocked: bool
    blocked_reasons: list[str]
    total_lines: int
    total_files: int

    def to_dict(self) -> dict:
        return {
            "level": self.level.value,
            "reasons": self.reasons,
            "blocked": self.blocked,
            "blocked_reasons": self.blocked_reasons,
            "total_lines": self.total_lines,
            "total_files": self.total_files,
        }


def assess_changes(changes: list[FileChange]) -> RiskAssessment:
    """Classifica o risco de um conjunto de mudanças (calculado sobre o diff real)."""
    level = Risk.LOW
    reasons: list[str] = []
    blocked: list[str] = []
    total_lines = 0

    if not changes:
        return RiskAssessment(Risk.LOW, ["nenhuma mudança"], True, ["diff vazio — nada a publicar"], 0, 0)

    for ch in changes:
        paths = [ch.path] + ([ch.old_path] if ch.old_path else [])
        for p in paths:
            norm = normalize_rel_path(p)
            if norm is None:
                blocked.append(f"caminho inválido: {p!r}")
                continue
            hit = path_matches(norm, FORBIDDEN_PATHS)
            if hit:
                blocked.append(f"{norm}: caminho protegido pela governança ({hit})")
        r = path_risk(ch.path, ch.status)
        if r != Risk.LOW:
            reasons.append(f"{ch.path} [{ch.status}] → risco {r.value}")
        level = max_risk(level, r)
        total_lines += len(ch.added_lines) + ch.removed_count

        added_text = "\n".join(ch.added_lines)
        secrets_found = find_secrets(added_text)
        if secrets_found:
            blocked.append(f"{ch.path}: possível segredo no diff ({', '.join(secrets_found[:3])})")
        if ch.path.lower().endswith(CODE_EXTENSIONS):
            for label, rx in ESCALATION_PATTERNS:
                if rx.search(added_text):
                    reasons.append(f"{ch.path}: adiciona {label} → risco alto")
                    level = Risk.HIGH

    if total_lines > MAX_LOW_RISK_LINES or len(changes) > MAX_LOW_RISK_FILES:
        if level == Risk.LOW:
            reasons.append(f"mudança grande ({total_lines} linhas, {len(changes)} arquivos) → risco médio")
        level = max_risk(level, Risk.MEDIUM)
    if total_lines > MAX_TOTAL_LINES or len(changes) > MAX_TOTAL_FILES:
        blocked.append(f"mudança excede o limite ({total_lines} linhas, {len(changes)} arquivos)")

    if not reasons:
        reasons.append("apenas documentação/interface/testes novos, dentro dos limites")
    return RiskAssessment(level, reasons, bool(blocked), blocked, total_lines, len(changes))


# --------------------------------------------------------------------- configurações

# Chaves de configuração que somente o proprietário humano pode alterar.
PROTECTED_SETTING_PREFIXES: tuple[str, ...] = ("governance.", "autonomy.", "publication.", "budget.", "security.")


def is_protected_setting(key: str) -> bool:
    return key.startswith(PROTECTED_SETTING_PREFIXES)


def requires_human_approval(risk: Risk) -> bool:
    """Médio e alto risco sempre exigem aprovação humana."""
    return risk in (Risk.MEDIUM, Risk.HIGH)


# Ações de missão que exigem aprovação humana (ações externas sensíveis).
SENSITIVE_ACTIONS: tuple[str, ...] = (
    "http_post",
    "send_message",
    "spend_money",
    "delete_data",
    "external_write",
)
