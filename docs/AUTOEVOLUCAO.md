# Autoevolução

## O ciclo

O scheduler roda no servidor, independente da interface estar aberta (padrão: a cada 6 horas).

| Fase | O que acontece de verdade |
|---|---|
| **Observar** | Agrega métricas reais (chamadas de IA, erros, latência, custos, missões, ferramentas, feedback, API), atualiza o mapa do código do workspace e roda a suíte de testes do branch estável no sandbox. |
| **Diagnosticar** | Regras sobre dados observáveis geram diagnósticos: provedor falhando, latência, projeção de custo, missões/agentes falhando, erros recorrentes, testes quebrados, capacidades faltando, código complexo/duplicado/sem teste, documentação desatualizada. |
| **Pesquisar** | Para diagnósticos graves, o Research Agent pesquisa soluções na web (se habilitado e com orçamento). |
| **Planejar** | O Self-Improvement Agent gera propostas estruturadas (problema, diagnóstico, objetivo, solução, arquivos, dependências, benefícios, riscos, custo, testes, critérios de aceitação, reversão). Há também propostas determinísticas (sem IA). Fila priorizada por severidade × confiança × risco ÷ custo. |
| **Desenvolver** | O Developer Agent edita numa branch `evolution/*` em worktree isolada. Toda edição passa pelo guardião (caminhos protegidos, travessia, links simbólicos, binários). Itera até 3 vezes com o resultado de compilação e testes. |
| **Testar** | Suíte completa no sandbox: versão original × versão modificada. |
| **Auditar** | Evaluation Engine: integridade da branch, política sobre o diff real, compilação, lint, testes sem falhas novas, sem perda de testes, desempenho, varredura de segurança, frontend; Auditor Agent em **outro provedor** quando possível. |
| **Publicar ou pedir aprovação** | Ver política abaixo. |
| **Monitorar** | Após publicar, compara erros antes × depois; regressão clara → rollback automático. |

Cada fase grava checkpoint: se o servidor reiniciar no meio, o ciclo é **retomado** da fase seguinte.
Limites: orçamento por ciclo, fatia mensal da evolução (pausa automática ao estourar), duração máxima,
número de propostas e de desenvolvimentos por ciclo.

## Política de publicação (LIMITED)

| Risco (calculado sobre o diff real) | Exemplos | Publicação |
|---|---|---|
| **Baixo** | documentação, interface, testes novos, até 400 linhas e 10 arquivos | automática **somente** se ativada, após autoteste aprovado, avaliação aprovada, auditor disponível, sandbox com rede isolada e CI verde |
| **Médio** | agentes, integrações, núcleo, banco, arquitetura, alterar/apagar testes | aprovação humana |
| **Alto** | autenticação, credenciais, permissões, dependências, infraestrutura, migrações, código com subprocessos/eval/rede/segredos | aprovação humana obrigatória **com senha** |
| **Protegido** | governança, segurança, sandbox, avaliação, publicação, orçamento, CI, testes de segurança | **nenhum agente altera** — só humanos, direto no repositório |

Com GitHub configurado, cada proposta que aguarda aprovação vira um PR. **Aprove pelo app do
ULTRON** (o PR serve para revisar o código, inclusive pelo app do GitHub). Se você aprovar antes de o
CI terminar, o ULTRON tenta publicar de novo sozinho a cada 10 minutos — ou toque em **Publicar agora**.

O risco declarado pelo agente é ignorado: vale o calculado. Uma aprovação vale apenas para a versão
exata do código avaliado (hash da árvore). Toda publicação guarda o ponto de retorno; rollback é um
`git revert` (o histórico é preservado).

## Como ativar a publicação automática (baixo risco)

1. **Autoevolução → Visão geral → Autoteste de segurança.** Ele tenta quebrar os controles: diffs em
   governança, segredos, travessia de caminhos, links simbólicos, escalonamento de privilégios de
   agentes, SSRF, adulteração de auditoria, configurações protegidas, segredos e rede no sandbox,
   leitura de arquivos privados pelo sandbox, e roda a suíte de testes de segurança.
2. Se tudo passar, ligue **Publicação automática (somente baixo risco)** e confirme com sua senha.
3. Se um autoteste futuro falhar, a publicação automática é desligada sozinha.

> Em hospedagens que não permitem namespaces de rede (muitos serviços Docker gerenciados), a checagem
> "sandbox sem acesso à rede" falha e a publicação automática fica bloqueada — por segurança. A
> autoevolução continua funcionando com sua aprovação, e cada PR é validado também pelo CI do GitHub.

## Pedir uma melhoria

**Autoevolução → Propostas → Pedir melhoria**, ou no chat use o modo **Engenharia** e toque em
**Criar proposta de evolução**. O Developer Agent implementa, o sandbox testa, o Evaluation Engine
avalia e você aprova.

## Novos agentes

O Self-Improvement Agent pode propor agentes novos com finalidade, ferramentas, escopos e orçamento.
Regras: nunca mais privilégios que o criador, nunca o escopo de publicação, no máximo 1 geração
(agentes criados não criam outros), até 12 agentes dinâmicos, orçamento ≤ US$ 0,10 por execução, e
**sempre** aprovação humana antes de ativar.
