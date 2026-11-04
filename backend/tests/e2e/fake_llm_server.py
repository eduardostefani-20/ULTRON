"""Servidor de TESTE para validar a interface com respostas de IA simuladas.

Uso exclusivo em testes de interface (E2E). Recusa-se a iniciar fora de ULTRON_ENV=test.
As respostas são fixas e identificadas como simuladas — nunca use isto como provedor real.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

if os.environ.get("ULTRON_ENV") != "test":
    sys.exit("fake_llm_server só pode rodar com ULTRON_ENV=test")

import uvicorn  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from tests.conftest import FakeProvider, install_fake, last_user, system_of  # noqa: E402
from ultron.main import create_app  # noqa: E402

TAG = "_(resposta simulada de teste)_"


def responder(req) -> str:
    sysmsg, user = system_of(req), last_user(req)
    if "Planeje a missão" in sysmsg:
        return json.dumps({"title": "Plano de estudos de IA", "strategy": "Pesquisar e depois sintetizar.", "tasks": [
            {"key": "t1", "title": "Levantar tópicos", "agent": "analyst", "instructions": "liste tópicos", "depends_on": []},
            {"key": "t2", "title": "Montar cronograma", "agent": "strategist", "instructions": "monte", "depends_on": ["t1"]}]})
    if "revisor independente" in sysmsg:
        return json.dumps({"meets_objective": True, "score": 8, "issues": []})
    if "Consolide os resultados" in sysmsg:
        return f"## Plano final\n\n1. **Semana 1:** fundamentos\n2. **Semana 2:** agentes\n\n{TAG}"
    if "crítico do Conselho" in sysmsg:
        return json.dumps({"consensus": ["Diversificar provedores reduz risco"], "divergences": [
            {"topic": "Custo", "positions": {"A": "usar só modelos rápidos", "B": "mesclar rápidos e premium"},
             "assessment": "B equilibra qualidade e custo"}], "errors": []})
    if "sintetizador" in sysmsg:
        return f"### Recomendação do Conselho\n\nMesclar modelos **rápidos** e **premium** conforme a tarefa.\n\n{TAG}"
    if "membro" in sysmsg and "Conselho" in sysmsg:
        return f"Minha análise independente: priorize custo por tarefa concluída. Confiança: média. {TAG}"
    if "Memory Agent" in sysmsg:
        return json.dumps({"memories": []})
    if "PROTOCOLO" in sysmsg:
        if "OBSERVAÇÃO" in user:
            return json.dumps({"thought": "concluir", "final": f"Resultado da tarefa com base nos dados. {TAG}"})
        return json.dumps({"thought": "concluir direto", "final": f"Tarefa executada. {TAG}"})
    return f"Olá! Sou o **ULTRON**.\n\n- Posso conversar\n- Pesquisar com fontes\n- Executar missões\n\n{TAG}"


async def main() -> None:
    from ultron.missions.engine import worker

    install_fake(FakeProvider("simulado", responder))
    server = uvicorn.Server(uvicorn.Config(create_app(), host="127.0.0.1", port=int(os.environ.get("PORT", "8766")),
                                           log_level="warning"))

    async def run_worker() -> None:  # em modo teste o app não inicia o worker sozinho
        while not server.started:
            await asyncio.sleep(0.2)
        await worker.run_forever()

    await asyncio.gather(server.serve(), run_worker())


if __name__ == "__main__":
    asyncio.run(main())
