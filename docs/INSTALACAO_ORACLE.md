# Instalação grátis na Oracle Cloud (pelo celular, sem terminal)

Custo: **R$ 0** — usa os recursos "Always Free" da Oracle (VM ARM Ampere com até 4 núcleos e
24 GB de memória). Tempo: ~30 minutos, a maior parte esperando.

O que você vai fazer: criar um token do GitHub, criar a conta na Oracle, criar a VM colando um
script pronto, liberar duas portas e abrir o endereço. A VM instala tudo sozinha: Docker, o
ULTRON, HTTPS automático e a atualização automática (quando o ULTRON publicar uma melhoria
aprovada, a VM se atualiza em até 10 minutos).

> Dica: se alguma tela da Oracle ficar apertada no celular, use "Versão para computador" no menu do
> navegador.

## Passo 1 — Token do GitHub (5 min)

1. No GitHub: foto do perfil → **Settings → Developer settings → Personal access tokens →
   Fine-grained tokens → Generate new token**.
2. Nome: `ULTRON`. Validade: a maior que o GitHub oferecer.
3. **Repository access → Only select repositories → ULTRON**.
4. **Permissions → Repository permissions**: **Contents: Read and write** e
   **Pull requests: Read and write**.
5. **Generate token** e copie o valor (começa com `github_pat_`). Guarde num lugar seguro.

## Passo 2 — Preparar o script (2 min)

1. Abra o arquivo **`deploy/oracle/cloud-init.sh`** do repositório (no app do GitHub ou no site).
2. Copie o conteúdo inteiro para um bloco de notas do celular e edite as duas linhas do topo:
   - `GITHUB_TOKEN="..."` → cole o token do passo 1 entre as aspas.
   - `SETUP_TOKEN="..."` → invente uma frase secreta (ela será pedida no primeiro acesso).

## Passo 3 — Conta na Oracle (10 min)

1. Abra **https://signup.cloud.oracle.com** e crie a conta "Free Tier".
2. **Região inicial (Home Region):** escolha **Brazil East (São Paulo)** ou **Brazil Southeast
   (Vinhedo)**. Ela não pode ser trocada depois e os recursos grátis ficam nela.
3. A Oracle pede um **cartão para verificação de identidade** (pode haver uma cobrança temporária de
   verificação, que é estornada). Os recursos "Always Free" não geram cobrança.

## Passo 4 — Criar a VM (5 min)

No console da Oracle: menu ☰ → **Compute → Instances → Create instance**.

1. **Nome:** `ultron`.
2. **Image:** troque para **Canonical Ubuntu 24.04** (ou 22.04).
3. **Shape:** troque para **Ampere → VM.Standard.A1.Flex** com **4 OCPUs e 24 GB** (ou 2 e 12 GB).
   Deve aparecer o selo **"Always Free-eligible"**.
4. **Networking:** deixe criar a rede e a sub-rede públicas e mantenha marcado **atribuir endereço
   IPv4 público**.
5. **SSH keys:** escolha **Generate a key pair for me** e baixe a chave privada (guarde; não é
   necessária no uso normal).
6. Abra **Show advanced options → Management → Initialization script → Paste cloud-init script** e
   **cole o script editado no passo 2**.
7. Toque em **Create**.

> **"Out of capacity" / sem capacidade?** É comum na VM ARM grátis. Tente outro *Availability
> Domain*, reduza para 2 OCPUs/12 GB ou tente mais tarde. Último recurso: a VM
> **VM.Standard.E2.1.Micro** (também grátis, 1 GB) — funciona, mas a instalação demora mais.

## Passo 5 — Liberar HTTP e HTTPS (3 min)

Na página da instância: **Primary VNIC → Subnet → Security Lists → Default Security List →
Add Ingress Rules**. Adicione **duas regras**:

| Source CIDR | IP Protocol | Destination Port Range |
|---|---|---|
| `0.0.0.0/0` | TCP | `80` |
| `0.0.0.0/0` | TCP | `443` |

## Passo 6 — Abrir o ULTRON (aguarde ~15 min)

1. Na página da instância, copie o **Public IP address**, por exemplo `129.146.10.20`.
2. Troque os pontos por traços e abra **`https://129-146-10-20.sslip.io`**. O certificado HTTPS é
   emitido automaticamente.
3. Crie a conta do proprietário usando a **frase secreta** do passo 2 como token de configuração.
4. Instale como aplicativo: Android (Chrome) menu ⋮ → **Instalar aplicativo**; iPhone (Safari) →
   Compartilhar → **Adicionar à Tela de Início**.

Se a página não abrir depois de 20 minutos, confira o passo 5 (portas) e se a VM está **Running**.

## Passo 7 — Ativar a inteligência

- **Integrações:** adicione pelo menos uma chave de IA (ex.: Anthropic Haiku 5.5, Gemini ou
  DeepSeek) e toque em **Salvar e testar**.
- **Integrações → GitHub:** cole o mesmo token do passo 1 (quando ele vencer, gere outro e salve
  aqui — a VM passa a usá-lo sozinha).
- **Autoevolução → Autoteste de segurança:** nesta VM o sandbox tem isolamento de rede, então o
  autoteste deve passar e você pode ligar a **publicação automática de baixo risco** se quiser.

## Bom saber

- **Instâncias ociosas:** a Oracle pode desligar VMs grátis com uso muito baixo por 7 dias seguidos.
  O ULTRON trabalha sozinho em segundo plano, o que reduz esse risco; se acontecer, basta tocar em
  **Start** na página da instância. Converter a conta para *Pay As You Go* evita isso, mas só faça se
  quiser e configure um alerta de orçamento (os recursos "Always Free" continuam sem custo).
- **Segurança:** o arquivo com as chaves fica só na VM (permissão de root), os containers não
  acessam o serviço de metadados da nuvem e o código experimental roda sem internet.
- **Domínio próprio (opcional):** o endereço `sslip.io` é gratuito e automático. Para usar um
  domínio seu, aponte-o para o IP da VM e troque `ULTRON_DOMAIN` em `/opt/ultron/deploy/oracle/.env`.
- **Registros:** `/var/log/ultron-install.log` (instalação) e `/var/log/ultron-update.log`
  (atualizações), acessíveis pelo SSH se um dia precisar.
