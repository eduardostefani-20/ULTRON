"""Verificação de integridade do código de governança.

Calcula o hash dos arquivos que implementam as proteções. Na inicialização, o hash é
comparado ao último registrado na auditoria; qualquer mudança é registrada (mudanças
legítimas só ocorrem por deploy humano, pois agentes não podem escrever nesses caminhos).
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ultron.governance import audit
from ultron.models import AuditLog
from ultron.utils import sha256

PACKAGE_DIR = Path(__file__).resolve().parent.parent

GOVERNANCE_FILES = (
    "governance/policy.py",
    "governance/permissions.py",
    "governance/audit.py",
    "governance/integrity.py",
    "governance/ci_guard.py",
    "security/passwords.py",
    "security/tokens.py",
    "security/vault.py",
    "evolution/guard.py",
    "evolution/sandbox.py",
    "evolution/evaluation.py",
    "evolution/publisher.py",
    "evolution/selftest.py",
    "settings_store.py",
    "llm/budget.py",
    "tools/netguard.py",
)


def governance_fingerprint() -> dict:
    files = {}
    for rel in GOVERNANCE_FILES:
        p = PACKAGE_DIR / rel
        files[rel] = sha256(p.read_bytes()) if p.exists() else "missing"
    combined = sha256("".join(f"{k}:{v};" for k, v in sorted(files.items())))
    return {"combined": combined, "files": files}


async def check_and_record(session: AsyncSession) -> dict:
    fp = governance_fingerprint()
    last = (
        await session.execute(
            select(AuditLog).where(AuditLog.action == "governance.fingerprint").order_by(AuditLog.seq.desc()).limit(1)
        )
    ).scalar_one_or_none()
    previous = (last.details or {}).get("combined") if last else None
    changed = previous is not None and previous != fp["combined"]
    missing = [k for k, v in fp["files"].items() if v == "missing"]
    if previous != fp["combined"]:
        changed_files = []
        if last:
            old_files = (last.details or {}).get("files", {})
            changed_files = [k for k, v in fp["files"].items() if old_files.get(k) != v]
        await audit.record("system", "governance.fingerprint", "governance",
                           {"combined": fp["combined"], "files": fp["files"], "changed_files": changed_files,
                            "previous": previous}, session=session)
    return {"fingerprint": fp["combined"], "changed_since_last_boot": changed, "missing": missing,
            "files": fp["files"]}
