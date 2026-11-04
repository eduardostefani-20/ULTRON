# ULTRON

**Plataforma pessoal de inteligência artificial autônoma, multiagente e autoevolutiva.**

O ULTRON conversa, pesquisa, convoca um conselho de IAs, executa missões longas com agentes
especializados, mantém memória persistente — e **observa o próprio funcionamento, diagnostica
limitações, desenvolve melhorias no próprio código, testa em sandbox isolado, passa por avaliação
independente e publica de forma controlada**, com aprovação humana e rollback.

| | |
|---|---|
| Acesso | Aplicativo web instalável (PWA) — celular e computador |
| Backend | Python 3.13 · FastAPI · SQLAlchemy assíncrono · Alembic |
| Interface | Next.js 16 · React 19 · TypeScript · Tailwind 4 |
| Dados | SQLite em disco persistente (padrão) ou PostgreSQL (Supabase/Render) |
| IA | Anthropic, OpenAI, Google Gemini, xAI, DeepSeek, Groq, OpenRouter, Mistral, Ollama |
| Testes | 161 testes automatizados (incl. testes que atacam os controles de segurança) |

## Começar pelo celular

Siga **[docs/INSTALACAO_CELULAR.md](docs/INSTALACAO_CELULAR.md)** — são cerca de 10 toques no
Render, sem terminal.

## Documentação

- [Instalação pelo celular](docs/INSTALACAO_CELULAR.md)
- [Arquitetura](docs/ARQUITETURA.md)
- [Autoevolução: como funciona e como ativar](docs/AUTOEVOLUCAO.md)
- [Segurança e governança](docs/SEGURANCA.md)
- [Custos e orçamento](docs/CUSTOS.md)
- [Relatório técnico da entrega](docs/RELATORIO_TECNICO.md)

## Desenvolvimento local (opcional)

```bash
./scripts/dev.sh                      # compila a interface e sobe tudo em http://localhost:8000
cd backend && python -m pytest -q     # testes
python -m ultron.doctor               # diagnóstico da instalação
```
