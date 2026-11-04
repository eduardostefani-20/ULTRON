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
| Testes | 173 testes automatizados (SQLite e PostgreSQL) (incl. testes que atacam os controles de segurança) |

## Começar pelo celular

- **Grátis e sem cartão (recomendado):** [docs/INSTALACAO_GRATIS_SEM_CARTAO.md](docs/INSTALACAO_GRATIS_SEM_CARTAO.md)
  — Hugging Face + Supabase + Gemini, instalado com um toque pelo GitHub Actions.
- **Grátis com cartão (VM mais forte):** [docs/INSTALACAO_ORACLE.md](docs/INSTALACAO_ORACLE.md) — Oracle Cloud.
- **Pago (~R$ 40/mês):** [docs/INSTALACAO_CELULAR.md](docs/INSTALACAO_CELULAR.md) — Render.

## Documentação

- [Instalação grátis e sem cartão (Hugging Face + Supabase)](docs/INSTALACAO_GRATIS_SEM_CARTAO.md)
- [Instalação grátis na Oracle Cloud](docs/INSTALACAO_ORACLE.md)
- [Instalação no Render (pago)](docs/INSTALACAO_CELULAR.md)
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
