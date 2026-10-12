@echo off
chcp 65001 > nul
cd /d "%~dp0"

set "PY=%~dp0_portatil\python\python.exe"
set "PYTHONPATH=%~dp0"
set "PLAYWRIGHT_BROWSERS_PATH=%~dp0_portatil\navegador"

echo ========================================================
echo     ATUALIZAR BASE DE RECONHECIMENTO - SEI SAO LUIS
echo ========================================================
echo.
if not exist "%PY%" (
  echo   ERRO: ambiente portatil nao encontrado.
  pause
  exit /b 1
)
echo O navegador abrira e vai baixando captchas novos.
echo Cada caractere aparece colorido pela certeza do sistema:
echo   verde = certeza, amarelo = duvida, vermelho = chute.
echo Clique nas alternativas para corrigir rapido.
echo Enter aceita tudo. Esc pula. Pode fechar quando quiser.
echo.
"%PY%" rotular_inteligente.py

echo.
echo Avaliando a base com os novos padroes...
"%PY%" sei_captcha_pipeline.py

echo.
pause > nul
