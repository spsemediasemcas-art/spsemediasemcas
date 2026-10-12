@echo off
chcp 65001 > nul
cd /d "%~dp0"

REM Python do ambiente do projeto (tem Playwright, OpenCV e scikit-learn).
REM NAO usar "python" generico do PATH: nao tem as bibliotecas e o script
REM quebra na primeira linha sem avisar.
set "PY=%~dp0_portatil\python\python.exe"
if not exist "%PY%" set "PY=C:\Users\PC\tse_automator_env\Scripts\python.exe"

echo ========================================================
echo     ROTULAGEM INTELIGENTE - SEI SAO LUIS
echo ========================================================
echo.
echo O navegador abrira e vai baixando captchas novos.
echo Cada caractere aparece colorido pela confianca do robo:
echo   verde = tem certeza, amarelo = duvida, vermelho = chute.
echo Clique nos botoes das alternativas para corrigir rapido.
echo Enter aceita tudo. Esc pula. Pode fechar quando quiser.
echo.
echo Ao sair, o modelo e retreinado com os rotulos novos.
echo.

"%PY%" "rotular_inteligente.py"

echo.
echo Retreinando o modelo com os rotulos atualizados...
"%PY%" "sei_captcha_pipeline.py" --treinar

echo.
echo ========================================================
echo   Desenvolvido por: Jurandy Santana
echo   WhatsApp: (98) 98401-6496
echo ========================================================
echo.
echo Pressione qualquer tecla para fechar...
pause > nul
