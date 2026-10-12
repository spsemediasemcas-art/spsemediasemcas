@echo off
chcp 65001 > nul
cd /d "%~dp0"

REM Ambiente portatil - funciona em qualquer computador, sem instalar nada
set "PY=%~dp0_portatil\python\python.exe"
set "PYTHONPATH=%~dp0"
set "PLAYWRIGHT_BROWSERS_PATH=%~dp0_portatil\navegador"

echo ========================================================
echo   MONITOR DE PROCESSOS SEI - PREFEITURA DE SAO LUIS
echo ========================================================
echo.
if not exist "%PY%" (
  echo   ERRO: ambiente portatil nao encontrado.
  echo   A pasta "_portatil" precisa estar junto deste arquivo.
  echo.
  pause
  exit /b 1
)
if exist "supabase_config.txt" (
  echo   Nuvem: ATIVA - dados enviados automaticamente
) else (
  echo   Nuvem: desativada - operacao local
)
if exist "semcas_config.txt" (
  echo   Controle de Processos SEMCAS: LIGADO
) else (
  echo   Controle de Processos SEMCAS: desligado
)
echo.
echo   Painel:  http://localhost:8765
echo   Para encerrar: Ctrl+C ou fechar esta janela.
echo ========================================================
echo   Desenvolvido por: Jurandy Santana
echo   WhatsApp: (98) 98401-6496
echo ========================================================
echo.

"%PY%" sei_monitor.py
pause > nul
