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

:: Usa sempre Python di sistema (i pacchetti sono installati li')
set PYTHON=python

:: Verifica che Python sia disponibile
%PYTHON% --version 2>nul
if %errorlevel% neq 0 (
    echo ERRORE: Python non trovato nel PATH!
    echo Scarica Python da: https://www.python.org/downloads/
    pause
    exit /b 1
)

:: Verifica config.yaml
if not exist "config.yaml" (
    echo ERRORE: config.yaml non trovato!
    pause
    exit /b 1
)

:: Verifica che yaml sia installato, altrimenti installa
%PYTHON% -c "import yaml" 2>nul
if %errorlevel% neq 0 (
    echo Dipendenze mancanti - installazione in corso...
    %PYTHON% -m pip install -r requirements.txt
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
