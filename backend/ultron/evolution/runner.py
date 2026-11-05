"""Executor de autoevolução fora do servidor (GitHub Actions).

    python -m ultron.evolution.runner cycle      # roda (ou retoma) um ciclo completo
    python -m ultron.evolution.runner selftest   # autoteste de segurança neste ambiente isolado

Usa o mesmo banco do servidor (DATABASE_URL). Com a mesma ULTRON_SECRET_KEY, lê também as chaves de
IA e o token do GitHub salvos em Integrações; sem ela, executa apenas as etapas que não usam IA.
Ideal para hospedagens gratuitas fracas: o trabalho pesado (testes no sandbox) roda numa máquina
efêmera e isolada do GitHub, sem acesso ao servidor de produção.
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import select


async def _prepare() -> None:
    from ultron.db import init_engine
    from ultron.main import bootstrap, harden_data_dir, protect_process

    protect_process()
    harden_data_dir()
    init_engine()
    await bootstrap()


async def run_cycle_once() -> dict:
    from ultron import telemetry
    from ultron.db import session_scope
    from ultron.evolution.cycle import LEASE_MIN, create_cycle, run_cycle
    from ultron.models import EvolutionCycle
    from ultron.settings_store import get_setting
    from ultron.utils import utcnow

    await _prepare()
    async with session_scope() as s:
        if not await get_setting(s, "evolution.enabled"):
            return {"status": "skipped", "reason": "autoevolução desativada no app"}
        if await get_setting(s, "evolution.paused"):
            return {"status": "skipped", "reason": "autoevolução pausada no app"}
        current = (await s.execute(select(EvolutionCycle).where(EvolutionCycle.status.in_(("running", "interrupted")))
                                   .order_by(EvolutionCycle.started_at.desc()))).scalars().first()
        resume_id = None
        if current is not None:
            fresh = bool(current.lease_expires_at and current.lease_expires_at > utcnow())
            if current.status == "running" and fresh:
                return {"status": "skipped", "reason": f"ciclo #{current.number} já está em execução"}
            resume_id = current.id
    cycle_id = resume_id or await create_cycle("github-actions")
    print(f"{'Retomando' if resume_id else 'Iniciando'} ciclo {cycle_id[:8]} (prazo do lease: {LEASE_MIN} min)")
    result = await run_cycle(cycle_id)
    await telemetry.flush()
    return result


async def run_selftest() -> dict:
    from ultron.evolution.selftest import run_selftest as _run

    await _prepare()
    return await _run("github-actions")


def main(argv: list[str]) -> int:
    mode = argv[1] if len(argv) > 1 else "cycle"
    if mode == "cycle":
        res = asyncio.run(run_cycle_once())
        print(f"Resultado: {res.get('status')} — {res.get('summary') or res.get('reason') or res.get('error') or ''}")
        return 1 if res.get("status") == "failed" else 0
    if mode == "selftest":
        res = asyncio.run(run_selftest())
        for c in res["checks"]:
            print(("✅" if c["passed"] else "❌"), c["name"], "—", c["detail"][:90])
        print("Autoteste aprovado" if res["passed"] else "Autoteste reprovado (publicação automática segue desligada)")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
