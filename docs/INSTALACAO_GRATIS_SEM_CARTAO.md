# Instalação no Hugging Face + Supabase + Gemini

> **Atenção (nov/2026):** o Hugging Face passou a exigir assinatura **PRO** para Spaces Docker
> (erro `402 Payment Required` na implantação). Sem cartão, use o
> **[ULTRON no notebook](INSTALACAO_NOTEBOOK.md)**. O passo 2 (Supabase) continua válido para guardar
> os dados na nuvem em qualquer instalação.

Custo: **R$ 0**, sem cartão de crédito em nenhum serviço. Tudo pelo navegador do celular.
Tempo: ~30 minutos.

| Peça | Serviço gratuito | Para quê |
|---|---|---|
| Hospedagem | **Hugging Face Spaces** (2 núcleos, 16 GB de memória) | roda o ULTRON 24h |
| Banco de dados | **Supabase** (PostgreSQL, 500 MB) | guarda conversas, memórias, missões e evolução |
| Inteligência | **Google Gemini** e/ou **Groq** (camadas gratuitas) | os modelos de IA |
| Automação | **GitHub Actions** (já incluso no seu repositório) | instala, atualiza e mantém o ULTRON acordado |

Como funciona: o Space do Hugging Face é **público, mas contém só um inicializador** (Dockerfile e
um script). Ao ligar, ele baixa o código do ULTRON do seu repositório **privado** usando o token,
compila e inicia. Código e dados continuam privados; a página pública mostra apenas a tela de login.

> Se alguma tela ficar apertada no celular, use "Versão para computador" no menu do navegador.

## Passo 1 — Token do GitHub

Se já criou o token `github_pat_...` (Contents e Pull requests: Read and write, só no repositório
ULTRON), pule. Senão: abra **https://github.com/settings/personal-access-tokens/new** no navegador e
siga o que está na seção "Token do GitHub" do guia da Oracle.

## Passo 2 — Banco de dados no Supabase (8 min)

1. Abra **https://supabase.com** → **Start your project** → entre com o **GitHub**.
2. Crie uma organização (plano **Free**) e um projeto:
   - **Name:** `ultron`
   - **Database Password:** toque em **Generate a password** e **copie** a senha.
     Se ela tiver símbolos como `@ # / ? %`, gere outra até sair só com letras e números.
   - **Region:** **South America (São Paulo)**.
3. Espere o projeto ficar pronto (~2 min) e toque em **Connect** (no topo).
4. Na aba de conexão, escolha **Session pooler** e copie o endereço (URI). Ele se parece com:
   `postgresql://postgres.abcdefgh:[YOUR-PASSWORD]@aws-0-sa-east-1.pooler.supabase.com:5432/postgres`
5. No bloco de notas, troque `[YOUR-PASSWORD]` pela senha do item 2 (sem os colchetes).

## Passo 3 — Conta e token do Hugging Face (5 min)

1. Abra **https://huggingface.co/join** e crie a conta (e-mail, usuário e senha). Confirme o e-mail.
2. Foto do perfil → **Settings → Access Tokens → Create new token**.
3. **Token type: Write**, nome `ULTRON` → **Create token** → copie (começa com `hf_`).

## Passo 4 — Guardar os segredos no GitHub (5 min)

No navegador, abra o repositório **eduardostefani-20/ULTRON** → **Settings** →
**Secrets and variables → Actions → New repository secret**. Crie estes 4 segredos:

| Name | Secret (valor) |
|---|---|
| `HF_TOKEN` | o token `hf_...` do passo 3 |
| `ULTRON_DATABASE_URL` | o endereço do Supabase do passo 2 (já com a senha) |
| `ULTRON_SETUP_TOKEN` | uma frase secreta inventada por você (pedida no primeiro acesso) |
| `ULTRON_GH_TOKEN` | o token `github_pat_...` do passo 1 |

### Testar a conexão com o banco (1 min)

No repositório: aba **Actions** → **Testar conexão com o banco** → **Run workflow**. Em ~30 segundos:

- ✅ **"Banco de dados conectado (PostgreSQL ...) — leitura e escrita OK"**: pronto, siga em frente.
- ❌ A mensagem diz o que corrigir: senha ainda como `[YOUR-PASSWORD]`, senha errada, senha com
  símbolos, endereço de "conexão direta" ou "Transaction pooler" em vez de **Session pooler**, ou
  projeto pausado. Corrija o segredo `ULTRON_DATABASE_URL` (Settings → Secrets → editar) e teste de novo.

A instalação do passo 5 também faz esse teste antes de publicar e não continua se o banco falhar.

## Passo 5 — Instalar com um toque

1. No repositório: aba **Actions** → **Implantar no Hugging Face** → **Run workflow** → escolha o
   branch `ccr-39385a67-fi2gyu` → **Run workflow**.
2. Em ~1 minuto fica verde ✅. Abra a execução → **Implantar** → no fim do registro aparece a linha
   `ULTRON: https://SEU-USUARIO-ultron.hf.space`.
3. A primeira inicialização leva **~5–10 minutos** (o Hugging Face monta a imagem e o ULTRON compila
   a interface). Acompanhe em `https://huggingface.co/spaces/SEU-USUARIO/ultron` até aparecer
   **Running**.

## Passo 6 — Primeiro acesso

1. Abra `https://SEU-USUARIO-ultron.hf.space`.
2. Crie a conta do proprietário: nome, e-mail, senha forte e a **frase secreta** do passo 4.
3. Instale como aplicativo: Android (Chrome) menu ⋮ → **Instalar aplicativo**; iPhone (Safari) →
   Compartilhar → **Adicionar à Tela de Início**.

## Passo 7 — Ligar a inteligência (sem cartão)

- **Google Gemini:** abra **https://aistudio.google.com/apikey** → **Create API key** → copie.
  No ULTRON: **Mais → Integrações → Google Gemini** → cole → **Salvar e testar**. O ULTRON escolhe
  sozinho os modelos disponíveis na sua conta.
- **Groq (opcional, recomendado como segundo provedor):** **https://console.groq.com/keys** →
  **Create API Key** → cole em **Integrações → Groq**. Com dois provedores o Conselho fica mais
  diverso e há reserva se um falhar.
- **GitHub (para a autoevolução publicar):** em **Integrações → GitHub**, cole o mesmo
  `github_pat_...`.

> As camadas gratuitas têm limites de uso por minuto/dia. Pela política do Google, dados enviados na
> camada gratuita do Gemini podem ser usados para melhorar os produtos deles — evite colocar
> informações muito sensíveis nas conversas.

## Bom saber

- **Atualizações automáticas:** quando o ULTRON publica uma melhoria aprovada (ou você altera o
  repositório), o GitHub reinicia o Space com o código novo. Fica ~1–2 minutos fora do ar.
- **Sempre acordado:** Spaces gratuitos dormem após 48 h sem acessos; o GitHub visita o seu a cada
  6 horas para evitar isso. Se um dia estiver dormindo, basta abrir o endereço e esperar ~2 minutos.
- **Dados seguros:** tudo fica no Supabase; reinícios do Space não apagam nada. A chave mestra que
  protege as chaves de IA é criada uma única vez e guardada nos segredos do Space.
- **Publicação automática:** neste tipo de hospedagem o sandbox roda com o mesmo usuário do servidor,
  então o autoteste mantém a publicação automática **desligada** — as melhorias chegam para sua
  aprovação no app (e como pull request no GitHub). Chaves e senha do banco continuam protegidas do
  código experimental.
- **Problemas?** Veja os registros em `https://huggingface.co/spaces/SEU-USUARIO/ultron` → **Logs**.
  Erro de banco geralmente é a senha no endereço do Supabase (passo 2, item 5).
