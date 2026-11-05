@echo off
rem ULTRON: atualizar (duplo clique). Detalhes em docs\INSTALACAO_NOTEBOOK.md
rem tudo numa linha: o cmd le a linha inteira antes de executar (a atualizacao pode substituir este arquivo)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\atualizar.ps1" & echo. & pause & exit /b
