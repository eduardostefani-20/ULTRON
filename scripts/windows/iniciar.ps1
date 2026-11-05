# Inicia o ULTRON neste computador (Windows). Use INICIAR-ULTRON.bat (duplo clique).
. (Join-Path $PSScriptRoot 'comum.ps1')
Escreva '=== ULTRON: iniciar ===' Green
Garantir-Docker

if (-not (Test-Path -LiteralPath $EnvPath)) {
  $linhas = @(
    '# Configuração do ULTRON neste computador (criada automaticamente). Não compartilhe este arquivo.',
    'ULTRON_ENV=production',
    "ULTRON_SECRET_KEY=$(Novo-Segredo 32)",
    "ULTRON_SETUP_TOKEN=$(Novo-Segredo 8)",
    'ULTRON_GITHUB_REPO=eduardostefani-20/ULTRON',
    'ULTRON_GIT_BASE_BRANCH=ccr-39385a67-fi2gyu',
    'ULTRON_MONTHLY_BUDGET_BRL=100',
    '# Endereço HTTPS para usar no celular de qualquer lugar (apague a linha abaixo para usar só no Wi-Fi de casa)',
    'COMPOSE_PROFILES=celular',
    '# Opcional: banco no Supabase (vazio = dados guardados neste computador)',
    'DATABASE_URL='
  )
  [IO.File]::WriteAllText($EnvPath, (($linhas -join "`n") + "`n"), (New-Object Text.UTF8Encoding($false)))
  Escreva 'Configuração criada (arquivo .env).' Cyan
}

Escreva 'Construindo e iniciando o ULTRON. Na primeira vez leva de 5 a 15 minutos...' Cyan
& docker compose up -d --build
if ($LASTEXITCODE -ne 0) {
  Escreva 'Não foi possível iniciar. Veja a mensagem acima; se for falha de internet, rode de novo.' Red
  exit 1
}
if (-not (Aguardar-Ultron)) {
  Escreva 'O ULTRON não respondeu a tempo. Veja os registros com: docker compose logs ultron' Red
  exit 1
}
Mostrar-Enderecos
Start-Process 'http://localhost:8000'
