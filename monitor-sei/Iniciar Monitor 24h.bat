@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo ========================================================
echo   MONITOR DE PROCESSOS SEI 24H + SUPABASE
echo   Prefeitura de Sao Luis - MA
echo ========================================================
echo.
if exist "supabase_config.txt" (
  echo   Supabase: ATIVO - dados enviados para a nuvem
) else (
  echo   Supabase: DESATIVADO - operacao local
  echo   ^(para ativar, veja LEIA-ME.txt^)
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
"C:\Users\PC\tse_automator_env\Scripts\python.exe" sei_monitor.py
