# ULTRON no seu notebook (grátis, sem cartão)

O ULTRON roda no seu computador dentro do **Docker Desktop** (gratuito para uso pessoal) e você
usa pelo **celular** de qualquer lugar, por um endereço HTTPS que aparece como **QR code** na tela
inicial do ULTRON.

| | |
|---|---|
| Custo | **R$ 0** de hospedagem (só o que você gastar com IA, limitado pelo orçamento de R$ 100/mês) |
| Computador | Windows 10/11 (64 bits), Mac ou Linux · 8 GB de memória recomendados · 10 GB livres no disco |
| Tempo | ~30 minutos na primeira vez (a maior parte é esperando downloads) |
| Dados | ficam no seu computador (ou no Supabase, se você quiser — veja no fim) |

> O celular só alcança o ULTRON enquanto o notebook estiver **ligado e sem hibernar**.

---

## Passo 1 — Instalar o Docker Desktop (10 min)

1. No notebook, abra **https://www.docker.com/products/docker-desktop/** e baixe a versão do seu
   sistema (Windows: *Download for Windows – AMD64*; Mac: escolha *Apple Silicon* ou *Intel*).
2. Instale com as opções padrão. **No Windows, deixe marcado "Use WSL 2"**. Se pedir para
   reiniciar o computador, reinicie.
3. Abra o **Docker Desktop** pelo menu Iniciar. Aceite os termos. Não precisa criar conta: se
   aparecer tela de login, procure **"Continue without signing in"** ou **"Skip"**.
4. Espere aparecer **"Engine running"** (verde) no canto inferior esquerdo.
5. Recomendado: **Settings (engrenagem) → General → "Start Docker Desktop when you sign in"**.
   Assim o ULTRON liga sozinho quando o notebook ligar.

Se aparecer erro de **virtualização** ("Virtualization support not detected"), ela precisa ser
ativada na BIOS do notebook: pesquise "ativar virtualização" + o modelo do seu notebook.
Se aparecer **"WSL needs updating"**, clique no botão que o próprio Docker mostra, ou abra o
PowerShell e rode `wsl --update`.

## Passo 2 — Baixar o ULTRON (3 min)

1. No navegador do notebook, entre no GitHub com a sua conta e abra:
   **https://github.com/eduardostefani-20/ULTRON/tree/ccr-39385a67-fi2gyu**
2. Botão verde **Code → Download ZIP**.
3. Na pasta Downloads, clique com o botão direito no ZIP → **Extrair tudo…** → escolha, por
   exemplo, **Documentos**. Vai surgir uma pasta como `ULTRON-ccr-39385a67-fi2gyu`.

## Passo 3 — Ligar o ULTRON (5 a 15 min na primeira vez)

**Windows:** abra a pasta extraída e dê **dois cliques em `INICIAR-ULTRON.bat`**.

- Se o Windows mostrar "O Windows protegeu o computador", clique em **Mais informações →
  Executar assim mesmo** (o arquivo é do seu próprio repositório).
- Uma janela preta mostra o progresso. Na primeira vez ele baixa e monta tudo; depois liga em
  segundos.

**Mac / Linux:** abra o Terminal na pasta extraída e rode `bash scripts/iniciar.sh`.

No final aparece algo assim, e o navegador abre sozinho:

```
ULTRON no ar!
  Neste computador:            http://localhost:8000
  No celular (mesmo Wi-Fi):    http://192.168.0.15:8000
  No celular (qualquer lugar): https://palavras-aleatorias.trycloudflare.com
  Token de configuração (só no primeiro acesso): 3f9c0a7e51b2d846
```

## Passo 4 — Criar sua conta (1 min)

Na página que abriu no notebook, preencha nome, e-mail, uma senha forte e o **token de
configuração** mostrado na janela. Esse token impede que outra pessoa crie a conta antes de você.
(Ele também fica guardado no arquivo `.env` da pasta, que você pode abrir com o Bloco de Notas.)

## Passo 5 — Abrir no celular e instalar o app (1 min)

1. No **Painel** do ULTRON (no notebook) aparece o cartão **"Abrir no celular"** com um QR code.
2. Aponte a câmera do celular para o QR e toque no link.
3. Entre com o seu e-mail e senha.
4. Instale o app: no Chrome (Android) **⋮ → Adicionar à tela inicial / Instalar app**; no Safari
   (iPhone) **Compartilhar → Adicionar à Tela de Início**.

**Importante:** esse endereço HTTPS muda **quando o notebook reinicia**. Quando isso acontecer,
abra `http://localhost:8000` no notebook e escaneie o QR novo (se tiver instalado o app, instale
de novo pelo endereço novo). Quer um endereço que nunca muda? Veja "Endereço fixo" abaixo.

Em casa, no mesmo Wi-Fi, você também pode usar o endereço `http://192.168.x.x:8000` mostrado na
janela (esse não muda, mas não permite instalar como app porque não é HTTPS).

## Passo 6 — Conectar a inteligência e o GitHub (5 min)

No ULTRON, abra **Integrações**:

- **IA:** adicione pelo menos uma chave. Grátis e sem cartão: **Google Gemini**
  (https://aistudio.google.com/apikey) e **Groq** (https://console.groq.com/keys). Também aceita
  Anthropic, OpenAI, xAI, DeepSeek, OpenRouter, Mistral e modelos locais (Ollama).
- **GitHub** (para a autoevolução e para atualizar): crie um token em
  **https://github.com/settings/personal-access-tokens/new** — nome `ULTRON`, validade máxima,
  **Only select repositories → ULTRON**, permissões **Contents: Read and write** e
  **Pull requests: Read and write**. Cole o token (`github_pat_...`) em Integrações → GitHub.

Pronto: o ULTRON já conversa, pesquisa, executa missões e roda os ciclos de autoevolução no seu
notebook (os testes do código experimental rodam num sandbox isolado, sem internet).

---

## Uso no dia a dia

| Quero… | Windows | Mac / Linux |
|---|---|---|
| Ligar | dois cliques em `INICIAR-ULTRON.bat` | `bash scripts/iniciar.sh` |
| Desligar (dados ficam guardados) | `PARAR-ULTRON.bat` | `bash scripts/parar.sh` |
| Atualizar para a versão mais nova | `ATUALIZAR-ULTRON.bat` | `bash scripts/atualizar.sh` |

- **Atualizar** baixa do seu GitHub a versão mais recente — incluindo melhorias que o próprio
  ULTRON desenvolveu e você aprovou em **Autoevolução** — e reinicia. Usa o token salvo em
  Integrações (ele nunca é gravado em arquivo). Se a construção falhar, a versão atual continua
  funcionando.
- Para o celular alcançar o ULTRON, o notebook não pode hibernar: no Windows, **Configurações →
  Sistema → Energia (e bateria) → Tela e suspensão → "Quando conectado, suspender após: Nunca"**.
- Os scripts e o `docker-compose.yml` **não podem ser alterados pelos agentes do ULTRON**
  (regra fixa da governança): eles rodam direto no seu computador, fora do isolamento.

## Endereço fixo (opcional, grátis)

Com o **Tailscale** (gratuito para uso pessoal) o celular acessa o notebook por um endereço HTTPS
que não muda, visível só para os seus aparelhos:

1. Instale o Tailscale no notebook (https://tailscale.com/download) e no celular (loja de apps) e
   entre com a mesma conta nos dois.
2. No notebook, abra o terminal (Windows: PowerShell) e rode `tailscale serve --bg 8000`.
3. Ele mostra um endereço como `https://seu-notebook.algum-nome.ts.net`. Abra no celular e
   instale o app por ele.

Nesse caso você pode desligar o endereço temporário: abra o `.env` com o Bloco de Notas, apague a
linha `COMPOSE_PROFILES=celular` e rode `PARAR-ULTRON` e depois `INICIAR-ULTRON`.

## Guardar os dados na nuvem (opcional)

Por padrão, conversas, memórias e histórico ficam no próprio notebook (num volume do Docker
chamado `ultron_ultron-data`, que sobrevive a desligar, atualizar e até apagar a pasta).
Se preferir guardar no **Supabase** (grátis), abra o `.env` com o Bloco de Notas, preencha
`DATABASE_URL=` com o endereço do *Session pooler* (veja o passo 2 de
[INSTALACAO_GRATIS_SEM_CARTAO.md](INSTALACAO_GRATIS_SEM_CARTAO.md)) e rode `PARAR-ULTRON` e
depois `INICIAR-ULTRON`. Os dados antigos do notebook não são copiados automaticamente.

**Guarde o arquivo `.env`**: ele contém a chave mestra que cifra as chaves de IA e o token salvos
em Integrações. Não envie esse arquivo para ninguém.

## Problemas comuns

| Sintoma | O que fazer |
|---|---|
| "O Docker Desktop não está instalado" | Faça o passo 1 e reinicie o computador. |
| A janela fica em "Aguardando o Docker Desktop" | Abra o Docker Desktop e espere "Engine running". |
| Falha no download durante a construção | Problema de internet: rode `INICIAR-ULTRON` de novo; ele continua de onde parou. |
| O cartão "Abrir no celular" não aparece | Espere 1 minuto e recarregue a página. Redes de empresa/escola podem bloquear o endereço temporário: use o Wi-Fi de casa ou o Tailscale. |
| "port is already allocated" (porta 8000 em uso) | Feche o outro programa que usa a porta 8000 e rode de novo. |
| Esqueci a senha | Na pasta do ULTRON, digite `cmd` na barra de endereço do Explorer, Enter, e rode `docker compose exec ultron python -m ultron.admin reset-password seu@email.com`. |
| Quero ver o que está acontecendo | No Docker Desktop → Containers → `ultron` → Logs. Ou, no ULTRON, **Segurança e auditoria** (autoteste de segurança) e **Uso e custos**. |
| Quero apagar tudo e começar do zero | `PARAR-ULTRON`, depois no Docker Desktop → Volumes → apague `ultron_ultron-data`, e apague o `.env`. |

## Como funciona (para curiosos)

- `INICIAR-ULTRON` cria o `.env` com chaves aleatórias na primeira vez e roda
  `docker compose up -d --build`: um contêiner com a interface, a API, o scheduler e o sandbox
  (`ultron`) e outro com o túnel HTTPS temporário da Cloudflare (`tunnel`).
- O ULTRON lê o endereço atual do túnel internamente (`http://tunnel:2000/quicktunnel`) e mostra
  o link e o QR no Painel, apenas para quem está logado.
- O contêiner roda com `seccomp=unconfined` para que o sandbox consiga criar um namespace de rede
  vazio (o código experimental roda sem internet, como usuário sem privilégios). O autoteste de
  segurança confere isso; se o isolamento falhar, a publicação automática continua desligada.
