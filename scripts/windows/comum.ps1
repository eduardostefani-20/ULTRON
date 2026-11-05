# Funções comuns dos scripts do ULTRON no Windows (usadas por iniciar, atualizar e parar).
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
$Raiz = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location -LiteralPath $Raiz
$EnvPath = Join-Path $Raiz '.env'

function Escreva([string]$Texto, [string]$Cor = 'Gray') { Write-Host $Texto -ForegroundColor $Cor }

function Novo-Segredo([int]$Bytes) {
  $b = New-Object byte[] $Bytes
  [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b)
  return (($b | ForEach-Object { $_.ToString('x2') }) -join '')
}

function Ler-Env([string]$Nome) {
  if (-not (Test-Path -LiteralPath $EnvPath)) { return '' }
  foreach ($l in Get-Content -LiteralPath $EnvPath) {
    if ($l -match "^\s*$Nome=(.*)$") { return $Matches[1].Trim() }
  }
  return ''
}

function Docker-Pronto { & docker info *> $null; return ($LASTEXITCODE -eq 0) }

function Garantir-Docker {
  if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Escreva 'O Docker Desktop não está instalado. Vou abrir a página de download.' Yellow
    Escreva 'Instale, reinicie o computador se ele pedir, abra o Docker Desktop uma vez e rode este arquivo de novo.' Yellow
    Start-Process 'https://www.docker.com/products/docker-desktop/'
    exit 1
  }
  if (Docker-Pronto) { return }
  $exe = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
  if (Test-Path -LiteralPath $exe) { Escreva 'Abrindo o Docker Desktop...' Cyan; Start-Process -FilePath $exe }
  Escreva 'Aguardando o Docker Desktop ficar pronto (até 3 minutos)...' Cyan
  for ($i = 0; $i -lt 90; $i++) {
    Start-Sleep -Seconds 2
    if (Docker-Pronto) { return }
  }
  Escreva 'O Docker Desktop não respondeu. Abra-o pelo menu Iniciar, espere ficar verde ("Engine running") e tente de novo.' Red
  exit 1
}

function Aguardar-Ultron {
  Escreva 'Aguardando o ULTRON responder...' Cyan
  for ($i = 0; $i -lt 90; $i++) {
    try { Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/health' -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop | Out-Null; return $true }
    catch { Start-Sleep -Seconds 2 }
  }
  return $false
}

function Endereco-Tunel {
  if ((Ler-Env 'COMPOSE_PROFILES') -notmatch 'celular') { return $null }
  for ($i = 0; $i -lt 30; $i++) {
    $log = (& docker compose logs tunnel 2>&1 | Out-String)
    $m = [regex]::Matches($log, 'https://[a-z0-9-]+\.trycloudflare\.com')
    if ($m.Count -gt 0) { return $m[$m.Count - 1].Value }
    Start-Sleep -Seconds 2
  }
  return $null
}

function Mostrar-Enderecos {
  Escreva ''
  Escreva 'ULTRON no ar!' Green
  Escreva '  Neste computador:            http://localhost:8000' White
  $ip = $null
  try {
    $cfg = Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq 'Up' } | Select-Object -First 1
    if ($cfg) { $ip = $cfg.IPv4Address | Select-Object -First 1 -ExpandProperty IPAddress }
  } catch { $ip = $null }
  if ($ip) { Escreva "  No celular (mesmo Wi-Fi):    http://${ip}:8000" White }
  $url = Endereco-Tunel
  if ($url) {
    Escreva "  No celular (qualquer lugar): $url" White
    Escreva '    O endereço muda quando o computador reinicia: o link e o QR code atuais aparecem na tela inicial do ULTRON.' DarkGray
    Set-Content -LiteralPath (Join-Path $Raiz 'ENDERECO-CELULAR.txt') -Value $url -Encoding ASCII
  }
  $tok = Ler-Env 'ULTRON_SETUP_TOKEN'
  if ($tok) { Escreva "  Token de configuração (só no primeiro acesso): $tok" Yellow }
}
