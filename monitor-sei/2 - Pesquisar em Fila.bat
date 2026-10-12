@echo off
chcp 65001 > nul
cd /d "%~dp0"

REM Ambiente portatil - funciona em qualquer computador, sem instalar nada
set "PY=%~dp0_portatil\python\python.exe"
set "PYTHONPATH=%~dp0"
set "PLAYWRIGHT_BROWSERS_PATH=%~dp0_portatil\navegador"

echo ========================================================
echo   PESQUISAR PROCESSOS NO SEI (em fila)
echo ========================================================
echo.
if not exist "%PY%" (
  echo   ERRO: ambiente portatil nao encontrado.
  pause
  exit /b 1
)
if not exist "numeros.txt" (
  echo   Coloque os numeros dos processos no arquivo "numeros.txt",
  echo   um por linha, e rode este atalho de novo.
  echo.
  pause
  exit /b 1
)
for /f %%c in ('type "numeros.txt" ^| find /c /v ""') do set TOTAL=%%c
echo   Numeros no arquivo: %TOTAL%
echo.
echo   O sistema vai pesquisar cada numero, achar o link e cadastrar
echo   no monitor. Pode deixar rodando - quem ja foi pesquisado nao
echo   e pesquisado de novo.
echo.
echo   Para pesquisar so uma parte:  digite a quantidade e Enter
echo   Para pesquisar todos:         so aperte Enter
echo.
set /p LIMITE="Quantidade (Enter = todos): "

if "%LIMITE%"=="" (
  "%PY%" pesquisar_fila.py
) else (
  "%PY%" pesquisar_fila.py %LIMITE%
)

echo.
echo   Pesquisa terminada. Os processos achados estao em fila_resultado.csv
echo   Para jogar no monitor: rode o atalho "3 - Importar para o Monitor.bat"
echo.
pause > nul
