@echo off
chcp 65001 > nul 2>&1
set PYTHONIOENCODING=utf-8
title Trading Bot - Installazione
color 0A

echo.
echo =====================================================
echo       TRADING BOT - INSTALLAZIONE AUTOMATICA
echo =====================================================
echo.

:: Verifica Python
echo [1/4] Verifica Python...
python --version 2>nul
if %errorlevel% neq 0 (
    echo ERRORE: Python non trovato!
    echo Scarica da: https://www.python.org/downloads/
    echo Seleziona "Add Python to PATH" durante l'installazione.
    pause
    exit /b 1
)
echo OK - Python trovato
echo.

:: Aggiorna pip
echo [2/4] Aggiornamento pip...
python -m pip install --upgrade pip --quiet
echo OK
echo.

:: Installa dipendenze
echo [3/4] Installazione dipendenze...
echo (potrebbe richiedere 2-5 minuti alla prima esecuzione)
echo.
python -m pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo.
    echo ERRORE durante l'installazione!
    echo Prova manualmente: python -m pip install -r requirements.txt
    pause
    exit /b 1
)
echo.

:: Crea directory necessarie
echo [4/4] Creazione struttura cartelle...
if not exist "data" mkdir data
if not exist "data\historical" mkdir data\historical
if not exist "models" mkdir models
if not exist "logs" mkdir logs
if not exist "backtester\reports" mkdir backtester\reports
echo OK - Cartelle create
echo.

:: Test rapido
echo Test importazione moduli...
python -c "import yaml, alpaca, pandas, streamlit; print('OK - Tutti i moduli caricati')"
if %errorlevel% neq 0 (
    echo AVVISO: Alcuni moduli potrebbero non essere installati correttamente.
)

echo.
echo =====================================================
echo          INSTALLAZIONE COMPLETATA!
echo =====================================================
echo.
echo PROSSIMI PASSI:
echo.
echo 1. Le API keys Alpaca sono gia configurate in config.yaml
echo 2. Doppio click su start_bot.bat per avviare il bot
echo 3. Doppio click su start_dashboard.bat per la dashboard
echo.
pause
