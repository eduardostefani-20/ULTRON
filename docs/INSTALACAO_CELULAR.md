# Instalação pelo celular (sem terminal)

Tempo estimado: 15 minutos. Tudo pelo navegador do celular.

> **Por que Render?** O ULTRON precisa de um processo **sempre ligado** (o scheduler da
> autoevolução e o worker de missões rodam continuamente). Funções serverless e páginas abertas no
> navegador não servem para isso. O plano Starter do Render custa US$ 7/mês e faz deploy direto do
> GitHub, inclusive pelo celular. Alternativas compatíveis: Railway, Fly.io ou qualquer VPS com Docker
> (`docker compose up -d`).

## Passo 1 — Criar a conta no Render

1. Abra **https://dashboard.render.com** e entre com sua conta do **GitHub**.
2. Autorize o Render a acessar o repositório **ULTRON** (privado).

## Passo 2 — Criar o serviço pelo Blueprint

1. No Render, toque em **New → Blueprint**.
2. Escolha o repositório **eduardostefani-20/ULTRON**.
3. Em **Branch**, escolha o branch com o código do ULTRON
   (hoje: `ccr-39385a67-fi2gyu`; se você fizer merge para `main`, use `main`).
4. O Render lê o arquivo `render.yaml` e mostra o serviço **ultron** com um disco de 1 GB.
5. Ele vai pedir alguns valores (os marcados com `sync: false`):
   - **ULTRON_GIT_BASE_BRANCH**: o mesmo branch do item 3.
   - **GITHUB_TOKEN**: pode deixar vazio agora (passo 6).
   - **DATABASE_URL**: deixe vazio (usa SQLite no disco persistente).
6. Toque em **Apply**. O primeiro build leva cerca de 5–8 minutos.

`ULTRON_SECRET_KEY` e `ULTRON_SETUP_TOKEN` são gerados automaticamente pelo Render.

## Passo 3 — Primeiro acesso

1. No Render, abra o serviço **ultron → Environment** e copie o valor de **ULTRON_SETUP_TOKEN**.
2. Abra o endereço do serviço (algo como `https://ultron-xxxx.onrender.com`).
3. Na tela inicial, crie a conta do proprietário: nome, e-mail, senha forte e o **token de configuração**
   copiado. Só quem tem esse token consegue criar a conta — e só uma vez.

## Passo 4 — Instalar como aplicativo

- **Android (Chrome):** menu ⋮ → **Instalar aplicativo**.
- **iPhone (Safari):** botão Compartilhar → **Adicionar à Tela de Início**.

## Passo 5 — Conectar pelo menos um provedor de IA

No app: **Mais → Integrações**. Recomendações para o orçamento de R$ 100/mês:

| Provedor | Por quê | Onde obter a chave |
|---|---|---|
| **Anthropic** | Haiku 5.5 é muito barato (US$ 0,10 / 0,50 por 1M tokens); Opus 5.5 para tarefas críticas | console.anthropic.com |
| **Google Gemini** | Camada gratuita com limites; bom para pesquisa | aistudio.google.com/apikey |
| **DeepSeek** | Muito barato, bom para código | platform.deepseek.com |

Toque no provedor → cole a chave → **Salvar e testar**. A chave é cifrada no servidor e nunca volta
para o navegador. Com dois provedores, o Conselho fica mais diverso e há fallback automático.

Opcional: **Tavily** (1.000 buscas grátis/mês) melhora muito a pesquisa web.

## Passo 6 — Permitir que o ULTRON publique melhorias no GitHub

1. No GitHub: **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate**.
2. Repository access: **Only select repositories → ULTRON**.
3. Permissions: **Contents: Read and write**, **Pull requests: Read and write**.
4. Copie o token e cole em **Integrações → GitHub** no app (ou em `GITHUB_TOKEN` no Render).

Com isso, cada melhoria vira um **pull request** que você pode revisar até pelo app do GitHub.

### Proteção recomendada do branch (no GitHub, 2 minutos)

**Settings → Branches → Add rule** para o branch principal:
- ✅ Require a pull request before merging
- ✅ Require status checks to pass → marque **Backend**, **Frontend** e **Guarda de governança**
- ✅ Require review from Code Owners (os arquivos de governança ficam protegidos pelo `CODEOWNERS`)

## Passo 7 — Ativar a autoevolução

Ela já vem **ligada** (ciclo a cada 6 horas) e o primeiro ciclo roda poucos minutos após o deploy.
A **publicação automática** vem **desligada**. Veja como ativar com segurança em
[AUTOEVOLUCAO.md](AUTOEVOLUCAO.md).

## Se algo der errado

- No Render, abra **Logs** do serviço.
- No Render, abra **Shell** e rode: `cd /app/backend && python -m ultron.doctor`
- Tela em branco ou "sem conexão": confira se o deploy terminou (status **Live**).
- Esqueceu a senha: no **Shell** do Render rode
  `cd /app/backend && python -m ultron.admin reset-password seu@email.com` e digite a nova senha.
