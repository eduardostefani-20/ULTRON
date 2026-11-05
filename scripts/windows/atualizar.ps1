# Baixa a versão mais recente do ULTRON do seu GitHub (incluindo melhorias aprovadas que o próprio
# ULTRON publicou) e reinicia. Se a construção falhar, a versão atual continua funcionando.
# Use ATUALIZAR-ULTRON.bat (duplo clique).
. (Join-Path $PSScriptRoot 'comum.ps1')
Escreva '=== ULTRON: atualizar ===' Green
Garantir-Docker
$repo = Ler-Env 'ULTRON_GITHUB_REPO'
$branch = Ler-Env 'ULTRON_GIT_BASE_BRANCH'
if (-not $repo -or -not $branch) { Escreva 'Rode INICIAR-ULTRON primeiro (falta o arquivo .env).' Yellow; exit 1 }

# token vigente: o salvo no app (Integrações → GitHub), lido de dentro do ULTRON; nunca é gravado em disco
$token = (& docker compose exec -T ultron python -m ultron.admin github-token 2>$null | Out-String).Trim()
if (-not $token) {
  Escreva 'Para atualizar, o ULTRON precisa estar ligado e com o token do GitHub salvo em Integrações → GitHub.' Yellow
  exit 1
}
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
$h = @{ Authorization = "Bearer $token"; 'User-Agent' = 'ultron-atualizador'; Accept = 'application/vnd.github+json' }
try {
  $sha = (Invoke-RestMethod -Uri "https://api.github.com/repos/$repo/commits/$branch" -Headers $h -UseBasicParsing -ErrorAction Stop).sha
} catch {
  Escreva "O GitHub recusou o acesso: $($_.Exception.Message). Confira o token em Integrações." Red
  exit 1
}
$versaoPath = Join-Path $Raiz '.versao'
$atual = ''
if (Test-Path -LiteralPath $versaoPath) { $atual = (Get-Content -LiteralPath $versaoPath -Raw).Trim() }
if ($sha -eq $atual) { Escreva "Você já está na versão mais recente ($($sha.Substring(0, 7)))." Green; exit 0 }

$tmp = Join-Path $env:TEMP ('ultron-' + (Novo-Segredo 4))
New-Item -ItemType Directory -Path $tmp | Out-Null
try {
  Escreva "Baixando a versão $($sha.Substring(0, 7))..." Cyan
  $zip = Join-Path $tmp 'codigo.zip'
  Invoke-WebRequest -Uri "https://api.github.com/repos/$repo/zipball/$sha" -Headers $h -OutFile $zip -UseBasicParsing -ErrorAction Stop
  Expand-Archive -LiteralPath $zip -DestinationPath (Join-Path $tmp 'x') -Force -ErrorAction Stop
  $src = (Get-ChildItem -LiteralPath (Join-Path $tmp 'x') -Directory | Select-Object -First 1).FullName
  if (-not $src -or -not (Test-Path -LiteralPath (Join-Path $src 'docker-compose.yml'))) { throw 'o pacote baixado não parece o ULTRON' }
  # pastas de código são espelhadas (sem tocar no .env nem nos dados, que ficam no Docker)
  foreach ($d in Get-ChildItem -LiteralPath $src -Directory) {
    & robocopy $d.FullName (Join-Path $Raiz $d.Name) /MIR /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "falha ao copiar a pasta $($d.Name)" }
  }
  Get-ChildItem -LiteralPath $src -File | Copy-Item -Destination $Raiz -Force -ErrorAction Stop
} catch {
  Escreva "Falha ao baixar a atualização: $($_.Exception.Message)" Red
  exit 1
} finally {
  Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
}

Escreva 'Reconstruindo o ULTRON (alguns minutos)...' Cyan
& docker compose up -d --build
if ($LASTEXITCODE -ne 0) { Escreva 'A construção falhou: a versão anterior continua no ar. Tente de novo mais tarde.' Red; exit 1 }
Set-Content -LiteralPath $versaoPath -Value $sha -Encoding ASCII
if (Aguardar-Ultron) { Mostrar-Enderecos }
