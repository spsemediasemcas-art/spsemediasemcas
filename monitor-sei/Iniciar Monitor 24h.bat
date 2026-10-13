@echo off
chcp 65001 > nul
cd /d "%~dp0"

REM Ambiente portatil - funciona em qualquer computador, sem instalar nada
set "PY=%~dp0_portatil\python\python.exe"
set "PYTHONPATH=%~dp0"
set "PLAYWRIGHT_BROWSERS_PATH=%~dp0_portatil\navegador"

if not exist "%PY%" (
  echo   ERRO: ambiente portatil nao encontrado.
  echo   A pasta "_portatil" precisa estar junto deste arquivo.
  echo.
  pause
  exit /b 1
)

echo ========================================================
echo   MONITOR DE PROCESSOS SEI 24H + SUPABASE
echo   Prefeitura de Sao Luis - MA
echo ========================================================
echo.
if exist "semcas_config.txt" (
  echo   Controle de Processos SEMCAS: LIGADO - envia ao sistema e atende "Verificar agora"
) else (
  echo   Controle de Processos SEMCAS: DESLIGADO - falta o semcas_config.txt
)
if exist "supabase_config.txt" (
  echo   Nuvem propria do monitor ^(opcional^): ATIVA
) else (
  echo   Nuvem propria do monitor ^(opcional^): nao usada
)
echo.
echo   Painel:  http://localhost:8765
echo   Inicio:  automatico com o Windows ^(veja LEIA-ME.txt^)
echo.
echo   NAO FECHE ESTA JANELA - o sistema roda 24h nela.
echo   Para encerrar: Ctrl+C ou fechar a janela.
echo ========================================================
echo   Desenvolvido por: Jurandy Santana
echo   WhatsApp: ^(98^) 98401-6496
echo ========================================================
echo.
"%PY%" sei_monitor.py
