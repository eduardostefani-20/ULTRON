# Segurança e governança

As proteções são **código e infraestrutura**, não instruções de prompt. Os agentes não conseguem
modificá-las: os arquivos são caminhos protegidos (o guardião recusa a escrita; a avaliação e o
publicador reprovam qualquer diff que os toque; o CI do GitHub reprova PRs de `evolution/*` que os
toquem, usando as regras do branch base).

## Camadas

| Camada | Implementação |
|---|---|
| Autenticação | Argon2id; JWT de 60 min; refresh rotativo guardado como hash; reuso de refresh revoga todas as sessões; bloqueio após 5 erros; limite de tentativas por IP; token de configuração inicial. |
| Autorização | Todas as rotas `/api` exigem token (há teste que percorre todas). Ações de dono exigem papel `owner`; aprovações de alto risco e a publicação automática exigem senha. |
| Segredos | Chaves cifradas em repouso (Fernet com chave derivada por HKDF da `ULTRON_SECRET_KEY`); nunca retornam ao navegador; redigidas de logs, auditoria e telemetria. |
| Permissões de agentes | 4 escopos separados (ler/analisar, sandbox, acesso externo, memória) + publicação que nunca é concedida a agentes. Ferramenta só roda se estiver na lista do agente, ele tiver o escopo e o dono tiver concedido o escopo. |
| Configurações protegidas | `governance.*`, `autonomy.*`, `publication.*`, `budget.*`, `security.*` só mudam pelo dono. O resultado do autoteste só é gravado pelo autoteste. O sistema só pode **desligar** a publicação automática. |
| Auditoria | Append-only com hash encadeado; `prev_hash` único (sem bifurcação); triggers no banco recusam UPDATE/DELETE/TRUNCATE; verificação da cadeia na tela Segurança. |
| Sandbox | Processo separado, limites de memória/CPU/arquivos, ambiente limpo (sem chaves, tokens, senhas, `DATABASE_URL` ou proxy), diretórios temporários destruídos, rede bloqueada via namespace (`unshare`) quando disponível, usuário `nobody` quando o servidor roda como root, lista de comandos permitidos. |
| Arquivos do servidor | `umask 077`; diretório de dados só atravessável; banco e chave em 0600 — o código experimental não lê memórias nem credenciais. |
| Rede externa | Bloqueio de SSRF (IPs privados, loopback, link-local, metadados de nuvem, IPv6 mapeado), validação a cada redirecionamento, limite de tamanho e tempo. |
| Conteúdo externo | Marcado como dado não confiável; frases de injeção sinalizadas; agentes instruídos de que conteúdo externo não tem autoridade — e, mesmo que obedecessem, as ações continuam sujeitas à governança em código. |
| Instalação no notebook | Scripts `*.bat`/`*.ps1`/`scripts/**` e `docker-compose*.yml` rodam no computador do dono, fora do isolamento — por isso são caminhos **proibidos** para agentes (não podem ser alterados nem por proposta aprovada). O atualizador lê o token de dentro do app e não o grava em disco. O endereço do túnel só aparece para usuários logados. |
| Publicação | Risco calculado pelo diff real; aprovação vinculada ao hash da árvore; revalidação de árvore, base e política imediatamente antes do merge; rollback por revert; monitoramento. |
| Integridade | Hash dos arquivos de governança registrado na auditoria a cada inicialização. |
| Interface | CSP, `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`; markdown renderizado sem `innerHTML`; service worker nunca guarda respostas da API. |

## Testes que atacam os controles

`backend/tests/security/` (caminho protegido) tenta, entre outros: escrever em governança e CI,
travessia `../`, escape por link simbólico, renomear arquivo protegido, segredos em diffs, código
perigoso em áreas de baixo risco, agentes com mais privilégios, publicação por agentes, SSRF em 14
alvos, redirecionamento para IP interno, UPDATE/DELETE na auditoria, adulteração detectada pela cadeia,
segredos em auditoria, alteração de configurações protegidas, publicação automática sem autoteste,
vazamento de variáveis no sandbox, rede no sandbox, leitura de arquivos privados pelo sandbox, comandos
fora da lista, rotas sem autenticação, chaves devolvidas pela API e aprovação de alto risco sem senha.

## Limites conhecidos (honestos)

- Em hospedagens sem namespaces de usuário/rede, o sandbox não isola a rede; o ambiente continua
  limpo e o usuário rebaixado, mas a publicação automática fica bloqueada.
- Instâncias de servidor executando como usuário comum (não root) não conseguem rebaixar o sandbox para
  `nobody`; o autoteste reprova e a publicação automática fica bloqueada.
- Um único proprietário por instalação (modelo pessoal).
