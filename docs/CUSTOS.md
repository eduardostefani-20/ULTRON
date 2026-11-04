# Custos e orçamento (meta: R$ 100/mês)

Câmbio de referência configurável (`ULTRON_USD_BRL_RATE`, padrão R$ 5,50).

## Infraestrutura

**Opção grátis (recomendada): Oracle Cloud "Always Free"** — VM ARM com até 4 núcleos e 24 GB, disco
de até 200 GB, HTTPS automático via `sslip.io`: **R$ 0/mês**. Guia: [INSTALACAO_ORACLE.md](INSTALACAO_ORACLE.md).
Com ela, praticamente os R$ 100 inteiros ficam para IA.

**Opção paga: Render**

| Item | Custo mensal |
|---|---|
| Render Starter (sempre ligado, necessário para o scheduler) | US$ 7,00 ≈ R$ 38,50 |
| Disco persistente 1 GB (SQLite + workspace) | US$ 0,25 ≈ R$ 1,40 |
| GitHub privado + Actions (2.000 min/mês grátis em repositórios privados) | R$ 0 |
| **Total de infraestrutura** | **≈ R$ 40** |

Alternativas: PostgreSQL do Supabase (camada gratuita) via `DATABASE_URL`; VPS com Docker a partir de
~US$ 4–5/mês; modelos locais com Ollama (custo zero de IA, exige servidor com mais memória).

## Inteligência artificial (≈ R$ 100 na Oracle ou ≈ R$ 60 no Render)

Preços de referência por 1 milhão de tokens (entrada / saída), editáveis em Configurações:

| Modelo | Camada | US$ entrada | US$ saída |
|---|---|---|---|
| Claude Haiku 5.5 | rápida | 0,10 | 0,50 |
| Gemini 2.5 Flash-Lite | rápida | 0,10 | 0,40 |
| DeepSeek Chat | equilibrada | 0,28 | 0,42 |
| Claude Sonnet 5.5 | equilibrada | 2,00 | 10,00 |
| Claude Opus 5.5 | premium | 4,00 | 20,00 |

Estimativa de uso pessoal com Haiku 5.5 + DeepSeek como principais: uma conversa rápida custa
~US$ 0,0002–0,001; uma missão de 3–5 tarefas ~US$ 0,01–0,05; um ciclo de evolução com
desenvolvimento por IA ~US$ 0,05–0,40 (limitado pelo orçamento do ciclo). Modelos de preço
desconhecido são contabilizados com preço conservador (US$ 3 / 15) para nunca subestimar.

## Controles automáticos

- Limite mensal global com **parada obrigatória** (padrão ligada).
- Fatia mensal da autoevolução (padrão 35%) — ao estourar, a evolução **pausa sozinha**.
- Orçamento por ciclo (US$ 0,40), por missão (US$ 0,30), por execução de agente (por definição do agente) e por modelo (opcional).
- Cache de respostas determinísticas, roteamento econômico (camada rápida pesa custo mais forte) e
  modo automático do chat que prefere o modo rápido para mensagens simples.
- Alerta visual ao atingir 80% (configurável) e projeção do mês na tela **Uso e custos**.
