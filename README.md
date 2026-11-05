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
| Testes | 198 testes automatizados (SQLite e PostgreSQL) (incl. testes que atacam os controles de segurança) |

## Como instalar

- **No seu notebook, grátis e sem cartão (recomendado):** [docs/INSTALACAO_NOTEBOOK.md](docs/INSTALACAO_NOTEBOOK.md)
  — Docker Desktop + dois cliques em `INICIAR-ULTRON.bat`; use no celular pelo QR code da tela inicial.
- **Grátis com cartão (VM na nuvem 24h):** [docs/INSTALACAO_ORACLE.md](docs/INSTALACAO_ORACLE.md) — Oracle Cloud.
- **Render:** [docs/INSTALACAO_CELULAR.md](docs/INSTALACAO_CELULAR.md) — plano gratuito (com banco no Supabase e
  ciclos de autoevolução no GitHub Actions) ou pago (~R$ 40/mês).
- Hugging Face: [docs/INSTALACAO_GRATIS_SEM_CARTAO.md](docs/INSTALACAO_GRATIS_SEM_CARTAO.md) — hoje exige assinatura PRO.

## Documentação

- [Instalação no notebook (grátis, sem cartão)](docs/INSTALACAO_NOTEBOOK.md)
- [Instalação no Hugging Face + Supabase (requer HF PRO)](docs/INSTALACAO_GRATIS_SEM_CARTAO.md)
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
