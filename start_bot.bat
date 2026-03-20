@echo off
chcp 65001 > nul 2>&1
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
title Trading Bot - In Esecuzione
color 0A

echo.
echo =====================================================
echo              TRADING BOT - AVVIO
echo =====================================================
echo.

:: Determina Python da usare (venv o sistema)
if exist "venv\Scripts\python.exe" (
    set PYTHON=venv\Scripts\python.exe
    echo Usando ambiente virtuale venv
) else (
    set PYTHON=python
    echo Usando Python di sistema
)

:: Verifica config.yaml
if not exist "config.yaml" (
    echo ERRORE: config.yaml non trovato!
    pause
    exit /b 1
)

:: Verifica che yaml sia installato
%PYTHON% -c "import yaml" 2>nul
if %errorlevel% neq 0 (
    echo.
    echo ATTENZIONE: Dipendenze mancanti. Installazione automatica...
    echo.
    %PYTHON% -m pip install -r requirements.txt --quiet
    echo.
)

echo Avvio bot in modalita PAPER TRADING...
echo.
echo Per fermare: Ctrl+C
echo Per la dashboard: start_dashboard.bat (in una nuova finestra)
echo.
echo =====================================================
echo.

%PYTHON% main.py bot

echo.
echo Bot fermato.
pause
