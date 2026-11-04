# Arquitetura do ULTRON

## Visão geral

```
 Celular / computador (PWA Next.js estático)
            │  HTTPS + Bearer token
            ▼
 ┌──────────────────────── processo único (Docker) ────────────────────────┐
 │ FastAPI (82 endpoints)  ──►  ULTRON CORE (chat, modo automático)         │
 │                              │                                           │
 │   Council Engine ◄───────────┤  Mission Engine (DAG, checkpoints,        │
 │   QUICK/STANDARD/COUNCIL/    │  retomada, aprovação, revisão)            │
 │   DEEP_RESEARCH/ENGINEERING  │                                           │
 │                              ▼                                           │
 │          Agentes (14) ── runtime JSON ── Ferramentas (23) ── Governança  │
 │                              │                                           │
 │          Serviço de LLM: orçamento → cache → roteador → fallback         │
 │          Adaptadores: Anthropic (SDK oficial) · Gemini · OpenAI-compat.  │
 │                                                                          │
 │   Memória (híbrida)   Pesquisa (busca + leitura segura + síntese)        │
 │                                                                          │
 │   Self-Evolution Engine ◄── Scheduler persistente (leases no banco)      │
 │   observar → diagnosticar → pesquisar → planejar → desenvolver →         │
 │   testar (sandbox) → auditar → publicar/aprovar → monitorar              │
 │        │                                                                 │
 │        └── Workspace git próprio (clone + worktrees evolution/*)         │
 └──────────────────────────────────────────────────────────────────────────┘
            │                                    │
     SQLite (/data) ou PostgreSQL         GitHub (PRs, CI, guarda de governança)
```

## Módulos (`backend/ultron`)

| Pacote | Responsabilidade |
|---|---|
| `core/chat.py` | Interpreta a mensagem, recupera memória, escolhe o modo (heurística gratuita), executa, registra e aprende. |
| `council/engine.py` | Os 5 modos de inteligência. O Conselho registra respostas independentes, crítica, divergências e nota explícita de que consenso não é verdade. |
| `agents/` | 14 agentes nativos (`definitions.py`), runtime raciocínio→ferramenta→observação (`runtime.py`), criação recursiva validada (`factory.py`). |
| `tools/` | 23 ferramentas com escopo declarado; `netguard.py` protege contra SSRF. |
| `missions/engine.py` | Missões em grafo de tarefas, paralelismo com travas de recurso, checkpoints, retomada após queda, aprovação humana, revisão independente e replanejamento. |
| `memory/` | Memória com 9 tipos e 6 status de confiabilidade; busca híbrida (vetor local + BM25 + importância + recência); deduplicação; retenção. |
| `research/` | Cadeia de busca (Tavily → Brave → Serper → SearXNG → Wikipedia/DuckDuckGo), leitura segura, conteúdo externo marcado como não confiável, síntese com citações. |
| `providers/` | Catálogo de modelos e preços, adaptadores, roteador com circuit breaker. |
| `llm/` | Serviço unificado e controle de orçamento. |
| `evolution/` | Observabilidade, diagnóstico, inteligência de código, propostas, desenvolvimento, sandbox, avaliação, publicação, ciclo, scheduler, autoteste. |
| `governance/` | Política imutável, permissões, auditoria encadeada, aprovações, integridade, guarda do CI. |
| `security/` | Senhas (Argon2id), tokens (JWT curto + refresh rotativo), cofre (Fernet/HKDF). |
| `api/` | Rotas REST. |

## Decisões técnicas

- **Adaptadores próprios em vez de LiteLLM.** Menos dependências (superfície de ataque de cadeia de
  suprimentos menor), controle total de custo por chamada e da política de fallback. O adaptador
  Anthropic usa o SDK oficial; Gemini e APIs compatíveis com OpenAI usam `httpx`. LiteLLM pode virar
  um adaptador adicional numa evolução futura.
- **Motor de grafo próprio em vez de LangGraph.** O estado das missões e dos ciclos fica no banco do
  ULTRON (checkpoints, leases, retomada), sob a mesma governança e auditoria. LangGraph não é
  necessário para o que foi construído e acrescentaria dependências pesadas.
- **Protocolo JSON universal para agentes.** Funciona com qualquer modelo, inclusive locais (Ollama).
  Chamada nativa de ferramentas por provedor é uma evolução possível.
- **Processo único.** API, scheduler e worker de missões rodam juntos; leases no banco impedem execução
  duplicada se houver mais de uma instância.
- **SQLite por padrão, PostgreSQL opcional.** Para um único usuário, SQLite em disco persistente é
  barato e suficiente. `DATABASE_URL` com `postgres://` (Supabase/Render) é convertido automaticamente
  para o driver assíncrono. As migrações (Alembic) rodam sozinhas ao iniciar.
- **Embeddings locais.** Busca semântica sem custo (vetor de 256 dimensões por hashing + BM25). Embeddings
  de provedor e pgvector são evoluções previstas — o vetor local já cobre bem um volume pessoal.
- **Interface estática.** Next.js exportado como arquivos estáticos e servido pelo próprio backend
  (mesma origem, sem CORS). Também pode ser publicado no Netlify (`netlify.toml`).

## Fluxo de uma mensagem

1. `POST /api/chat` → conversa criada/recuperada, mensagem gravada.
2. Memórias relevantes recuperadas (com status: confirmada, hipótese, desatualizada…).
3. Modo escolhido (automático ou pelo usuário) e executado pelo Council Engine.
4. Cada chamada de modelo: checagem de orçamento → cache → roteador → provedor → telemetria.
5. Resposta gravada com modelos, custo, fontes e detalhes; extração de memória em segundo plano.

## Mapa vivo

O próprio ULTRON gera `docs/ARQUITETURA_GERADA.md` a partir da análise do código (primeira
melhoria que ele propõe após o deploy) e mostra o mapa interativo em **Arquitetura** no app.
