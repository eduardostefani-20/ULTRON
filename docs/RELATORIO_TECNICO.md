# Relatório técnico — primeira entrega do ULTRON (v0.1.0)

Data: 04/11/2026 · Branch: `ccr-39385a67-fi2gyu`

## 1. Arquitetura final

Um único serviço Docker contém a API FastAPI, a interface PWA (Next.js exportado), o scheduler
persistente e o worker de missões. Dados em SQLite no disco persistente (ou PostgreSQL). Um workspace
git próprio (clone do repositório + worktrees `evolution/*`) é onde o ULTRON desenvolve a si mesmo.
Detalhes em [ARQUITETURA.md](ARQUITETURA.md).

## 2. Tecnologias

Python 3.13, FastAPI 0.162, Pydantic 2, SQLAlchemy 2.1 assíncrono, Alembic, aiosqlite/asyncpg, httpx,
SDK oficial `anthropic`, Argon2, PyJWT, cryptography (Fernet/HKDF), BeautifulSoup, pytest, ruff ·
Next.js 16, React 19, TypeScript 5.9, Tailwind 4, lucide · Docker, GitHub Actions, Render Blueprint.

LiteLLM e LangGraph **não** foram usados (decisão justificada em ARQUITETURA.md: adaptadores e motor
de grafo próprios, com estado e governança no banco do ULTRON).

## 3. Funcionalidades implementadas

- **Acesso:** PWA instalável, layout para celular e computador, login, configuração inicial protegida
  por token, renovação de sessão, troca e redefinição de senha.
- **ULTRON Core / Chat:** histórico, 7 modos (Automático, Rápido, Padrão, Conselho, Pesquisa,
  Engenharia, Missão), memória recuperada por mensagem, feedback 👍/👎, aprendizado automático.
- **Council Engine:** QUICK, STANDARD, COUNCIL (membros independentes de provedores distintos, crítico,
  sintetizador, divergências registradas), DEEP RESEARCH, ENGINEERING COUNCIL (proponente, crítico,
  revisor de segurança/arquitetura → registro de decisão → proposta de evolução).
- **Multi-modelo:** 9 provedores, catálogo com preços, roteamento por tarefa/qualidade/custo/saúde/contexto,
  circuit breaker, fallback, cache, refusal tratado.
- **Agentes:** 14 especializados com ferramentas e escopos; execução direta pela interface; criação de
  novos agentes com finalidade/orçamento/permissões e aprovação humana.
- **Missões:** planejamento em grafo, paralelismo com travas de recurso, checkpoints, retomada após
  queda, aprovação de ações sensíveis, revisão independente, replanejamento, cancelamento.
- **Memória:** 9 tipos, 6 status de confiabilidade, busca híbrida, deduplicação, retenção, exclusão.
- **Pesquisa:** cadeia de buscadores, leitura segura de páginas, confiabilidade por fonte, síntese citada.
- **Self-Evolution Engine:** observabilidade, autodiagnóstico, inteligência de código, propostas
  estruturadas e fila priorizada, desenvolvimento autônomo em branch isolada, sandbox, avaliação
  independente, publicação limitada por risco, rollback, monitoramento pós-publicação, scheduler.
- **Governança:** política imutável, permissões em 4 escopos, auditoria encadeada append-only,
  aprovações, integridade, autoteste de segurança, guarda no CI.
- **Custos:** orçamento mensal em R$, limites por missão/agente/modelo/ciclo/evolução, pausa automática.
- **14 telas:** Painel, Chat, Conselho, Agentes, Missões, Memória, Pesquisa, Autoevolução,
  Integrações, Uso e custos, Configurações, Segurança e auditoria, Arquitetura, Workspace.

## 4. Funcionalidades testadas

168 testes automatizados (`cd backend && python -m pytest -q`), todos passando:

- **Segurança (105):** ataques diretos aos controles — caminhos protegidos, travessia, symlinks,
  segredos, escalonamento de agentes, SSRF, auditoria adulterada/apagada, configurações protegidas,
  sandbox (segredos, rede, arquivos privados, tempo, comandos), todas as rotas exigindo autenticação,
  chaves nunca devolvidas, aprovação de alto risco exigindo senha.
- **Provedores:** formato real das requisições/respostas de OpenAI-compatível, Gemini e Anthropic
  (sem `temperature`, `effort`, fallback de recusa no servidor, recusas), preços.
- **Roteamento/orçamento:** preferência por custo, diversidade, circuit breaker, fallback, cache,
  bloqueio mensal, por execução e pausa automática da evolução.
- **Inteligência:** memória, agentes com ferramentas, negação de ferramenta, ação sensível, Conselho,
  chat, missões (grafo completo, retomada após interrupção, aprovação e retomada, cancelamento).
- **Autoevolução ponta a ponta sobre git real:** ciclo completo → aprovação → publicação → rollback;
  desenvolvimento por IA aprovado; tentativa maliciosa de alterar governança rejeitada; mudança que
  quebra testes reprovada; autoteste + publicação automática de baixo risco; pausa e retomada;
  branch perdida após reinício; aprovação antiga não autoriza código novo; aprovação que chegou antes
  do CI é publicada na retentativa automática.

## 5. Resultados reais obtidos nesta construção

- O ULTRON **clonou o próprio repositório e executou a própria suíte inteira dentro do sandbox**
  (usuário `nobody`, rede isolada por namespace, sem segredos): dos 160 testes, 159 passaram e 1 foi
  pulado por design (o teste de rebaixamento de privilégios não se aplica dentro do próprio sandbox).
- Servidor completo + navegador (Playwright, viewport de celular): criação de conta, as 14 telas,
  chat, memória; o **scheduler iniciou sozinho** um ciclo sobre o código real do ULTRON: 159 testes do
  branch estável verdes, **51 diagnósticos reais** (módulos sem teste dedicado, funções complexas,
  ausência de provedor de IA, pesquisa sem chave, documentação desatualizada), 1 proposta desenvolvida,
  avaliada e aprovada pelos portões, **aprovada pela interface e publicada** (merge no workspace).
- O servidor foi derrubado no meio de um ciclo e o novo processo **retomou o ciclo do checkpoint**.
- Esse teste revelou e corrigiu dois problemas reais: branch perdida após reinício (agora recuperada
  do remoto ou devolvida à fila) e aprovação que poderia valer para código redesenvolvido (agora
  vinculada ao hash exato da árvore).
- Varredura de estouro horizontal: 17 telas × 3 larguras de celular sem estouro.
- Imagem Docker construída e executada: saúde OK, token de configuração exigido, interface servida,
  `/data` 0711 e banco 0600. Dentro do Docker padrão o `unshare` é bloqueado (rede do sandbox não
  isolada); com `seccomp=unconfined` o isolamento funciona.
- **CI do GitHub verde** em ambiente independente (runners do GitHub): backend com lint + toda a
  suíte, e frontend com checagem de tipos + build.
- Guarda de governança do CI testado localmente: diff em governança reprovado (saída 1), diff de
  documentação aprovado (saída 0).

## 6. Agentes disponíveis

Director, Research, Analyst, Strategist, Developer, Auditor, Executor, Memory, Self-Improvement,
Architecture, Testing, Cost Optimization, Security, Documentation.

## 7. Modelos conectados

**Nenhum provedor real foi chamado neste ambiente de construção**: não havia chave de API do usuário e
a rede deste ambiente bloqueia OpenAI, Anthropic, xAI, DeepSeek, Groq e OpenRouter. Os adaptadores
foram validados contra os formatos oficiais das APIs com transportes simulados, e a orquestração
completa foi validada com um provedor simulado **restrito aos testes**. A primeira chamada real
acontece quando você adicionar uma chave em Integrações (botão "Salvar e testar" confirma a conexão).

Catálogo pronto: Anthropic (Haiku 5.5, Sonnet 5.5, Opus 5.5), OpenAI, Gemini, xAI, DeepSeek, Groq,
Mistral, OpenRouter e Ollama; modelos de cada camada são editáveis na interface.

## 8. Estado da memória

Funcional e persistente (CRUD, busca híbrida local, status, retenção, extração automática com modelo
rápido). Embeddings de provedor e pgvector ainda não implementados.

## 9. Estado do Self-Evolution Engine

Funcional de ponta a ponta. Sem provedor de IA, já executa observação, diagnóstico, propostas
determinísticas (documentação de arquitetura), desenvolvimento, testes, avaliação e publicação. Com
provedor, adiciona pesquisa, propostas por IA, desenvolvimento por IA e auditor independente.

## 10. Estado do scheduler

Funcional: roda no processo do servidor, com leases no banco, jobs de evolução (6 h), saúde dos
provedores (30 min), monitoramento de publicações (10 min), retenção de memória (24 h), limpeza de
cache (6 h) e métricas da API (1 min); retoma ciclos interrompidos.

## 11. Estado do sandbox

Funcional: ambiente limpo, limites de recursos, tempo máximo, destruição de temporários, usuário
`nobody` quando o servidor é root, rede isolada quando o host permite namespaces. No Render (Docker
gerenciado) espera-se **rede não isolada** — a publicação automática fica bloqueada nesse caso.

## 12. Estado da publicação limitada

Implementada e testada. **Publicação automática começa desabilitada.** Só pode ser ligada pelo dono,
com senha, após o autoteste de segurança passar, e apenas para baixo risco. Médio/alto risco sempre
pedem aprovação. Com GitHub configurado, cada melhoria vira PR e exige CI verde.

## 13. Infraestrutura necessária

Serviço sempre ligado com Docker e disco persistente, repositório GitHub privado (já existe), token
fine-grained do GitHub e pelo menos uma chave de IA. Duas opções prontas:

- **Oracle Cloud "Always Free" (R$ 0):** `deploy/oracle/cloud-init.sh` instala Docker, o ULTRON,
  HTTPS automático (Caddy + `sslip.io`) e a atualização automática a cada 10 minutos (é assim que as
  melhorias publicadas pelo ULTRON entram no ar). O sandbox tem isolamento de rede nessa VM e os
  containers não acessam o serviço de metadados da nuvem. Os scripts de implantação são caminhos
  protegidos (nenhum agente os altera). Validados aqui: sintaxe, compose, todas as dependências com
  pacotes ARM64 e o atualizador (teste automatizado com docker simulado). A instalação real na Oracle
  só pode ser feita na sua conta.
- **Render Starter (~R$ 40/mês):** `render.yaml`.

## 14. Custos estimados

R$ 0 de infraestrutura na Oracle (ou ≈ R$ 40 no Render) + IA limitada pelo orçamento (padrão
R$ 100 no total). Ver [CUSTOS.md](CUSTOS.md).

## 15. Pendências

**Dependem de você (não há como fazer daqui):**
1. Criar a VM grátis na Oracle colando o script ([INSTALACAO_ORACLE.md](INSTALACAO_ORACLE.md)) —
   ou o serviço pago no Render ([INSTALACAO_CELULAR.md](INSTALACAO_CELULAR.md)).
2. Adicionar pelo menos uma chave de IA em Integrações.
3. Criar o token do GitHub e ativar a proteção do branch (CI obrigatório + Code Owners).
4. (Opcional) Chave do Tavily para pesquisa melhor.

**Técnicas (próximas evoluções do próprio ULTRON):**
- Validação com provedores reais (pendente de chave).
- Embeddings de provedor/pgvector; chamada nativa de ferramentas por provedor; respostas em streaming.
- Notificações push para aprovações pendentes.
- Verificação do frontend no servidor de produção depende do CI (a imagem não inclui o toolchain Node).
- Isolamento de rede do sandbox no Render depende do host; alternativa: VPS com Docker e
  `seccomp=unconfined`, ou runner dedicado.
- Heurística "módulo sem teste dedicado" é simples (gera alguns falsos positivos de baixa severidade).

## 16. Acesso pelo celular

Após a instalação: abra `https://<IP-com-traços>.sslip.io` (Oracle) ou a URL do Render → crie a conta com o token de configuração →
instale como aplicativo (Android: menu → Instalar; iPhone: Compartilhar → Tela de Início). A
navegação inferior dá acesso a Painel, Chat, Missões, Evolução e "Mais" (todas as 14 telas);
aprovações pendentes aparecem no topo.

## 17. Próximas evoluções recomendadas

1. Conectar Haiku 5.5 + DeepSeek e deixar o primeiro ciclo propor melhorias com IA.
2. Aprovar a primeira melhoria (documentação de arquitetura gerada) para validar a publicação via PR.
3. Notificações push de aprovações e fim de missões.
4. Streaming de respostas no chat.
5. pgvector + embeddings de provedor quando a memória crescer.
6. Runner de sandbox com rede isolada (VPS barato) para liberar a publicação automática de baixo risco.
