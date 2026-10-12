@echo off
chcp 65001 > nul
cd /d "%~dp0"
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

python "rotular_inteligente.py"

echo.
echo Avaliando a pipeline com os novos rotulos...
python "sei_captcha_pipeline.py"

echo.
echo Pressione qualquer tecla para fechar...
pause > nul
