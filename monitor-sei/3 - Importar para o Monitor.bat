@echo off
chcp 65001 > nul
cd /d "%~dp0"

set "PY=%~dp0_portatil\python\python.exe"
set "PYTHONPATH=%~dp0"
set "PLAYWRIGHT_BROWSERS_PATH=%~dp0_portatil\navegador"

echo ========================================================
echo   IMPORTAR PROCESSOS PESQUISADOS PARA O MONITOR
echo ========================================================
echo.
if not exist "%PY%" (
  echo   ERRO: ambiente portatil nao encontrado.
  pause
  exit /b 1
)
if not exist "fila_resultado.csv" (
  echo   Nada para importar ainda. Rode primeiro o atalho
  echo   "2 - Pesquisar em Fila.bat".
  echo.
  pause
  exit /b 1
)
echo   Importando os processos achados e baixando o conteudo deles.
echo   Pode demorar alguns minutos. Aguarde...
echo.
"%PY%" importar_fila.py
echo.
pause > nul
