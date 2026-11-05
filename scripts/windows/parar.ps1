# Para o ULTRON (os dados continuam guardados). Use PARAR-ULTRON.bat (duplo clique).
. (Join-Path $PSScriptRoot 'comum.ps1')
Escreva '=== ULTRON: parar ===' Green
if (-not (Docker-Pronto)) { Escreva 'O Docker Desktop não está aberto: o ULTRON já está parado.' Cyan; exit 0 }
& docker compose --profile celular down
if ($LASTEXITCODE -eq 0) { Escreva 'ULTRON parado. Seus dados continuam guardados; para ligar de novo, use INICIAR-ULTRON.' Green }
