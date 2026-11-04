"""Guarda de governança executado no CI do GitHub (proteção independente do servidor).

Em pull requests de branches ``evolution/*`` ou ``rollback/*`` (criadas pelo ULTRON), reprova o PR
se o diff tocar caminhos protegidos ou contiver segredos. O workflow carrega ESTE arquivo a partir
do branch base — o PR não consegue alterar a regra que o avalia.

Uso: python -m ultron.governance.ci_guard <ref_base> <ref_head>
"""

from __future__ import annotations

import subprocess
import sys

from ultron.governance.policy import FileChange, assess_changes


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def collect(base: str, head: str) -> list[FileChange]:
    changes: dict[str, FileChange] = {}
    for line in _git("diff", "--name-status", "-M", f"{base}...{head}").splitlines():
        parts = line.split("\t")
        if len(parts) >= 3 and parts[0].startswith("R"):
            changes[parts[2]] = FileChange(parts[2], "R", old_path=parts[1])
        elif len(parts) >= 2:
            changes[parts[1]] = FileChange(parts[1], parts[0][0])
    current = None
    for line in _git("diff", "-U0", "--no-color", "-M", f"{base}...{head}").splitlines():
        if line.startswith("+++ "):
            path = line[4:].removeprefix("b/")
            current = changes.get(path)
        elif current is not None and line.startswith("+") and not line.startswith("+++"):
            current.added_lines.append(line[1:])
        elif current is not None and line.startswith("-") and not line.startswith("---"):
            current.removed_count += 1
    return list(changes.values())


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    assessment = assess_changes(collect(argv[1], argv[2]))
    print(f"Risco calculado: {assessment.level.value} ({assessment.total_files} arquivos, {assessment.total_lines} linhas)")
    for r in assessment.reasons:
        print(f"  - {r}")
    if assessment.blocked:
        print("BLOQUEADO pela governança:")
        for r in assessment.blocked_reasons:
            print(f"  ✗ {r}")
        return 1
    print("OK: nenhum caminho protegido ou segredo no diff.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
