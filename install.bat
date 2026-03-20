@echo off
chcp 65001 >nul
title Trading Bot - Installazione
color 0A

echo.
echo ╔══════════════════════════════════════════════════════╗
echo ║       TRADING BOT - INSTALLAZIONE AUTOMATICA        ║
echo ╚══════════════════════════════════════════════════════╝
echo.

:: Verifica Python
echo [1/5] Verifica installazione Python...
python --version 2>nul
if %errorlevel% neq 0 (
    echo.
    echo ERRORE: Python non trovato!
    echo Scarica Python da: https://www.python.org/downloads/
    echo Assicurati di selezionare "Add Python to PATH" durante l'installazione.
    echo.
    pause
    exit /b 1
)

:: Verifica versione Python >= 3.11
python -c "import sys; exit(0 if sys.version_info >= (3,11) else 1)"
if %errorlevel% neq 0 (
    echo.
    echo ATTENZIONE: Python 3.11 o superiore richiesto.
    echo Aggiorna Python da: https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

echo OK - Python trovato
echo.

:: Crea ambiente virtuale
echo [2/5] Creazione ambiente virtuale Python...
if not exist "venv" (
    python -m venv venv
    echo OK - Ambiente virtuale creato
) else (
    echo OK - Ambiente virtuale già esistente
)
echo.

:: Attiva ambiente virtuale
echo [3/5] Attivazione ambiente virtuale...
call venv\Scripts\activate.bat
echo OK - Ambiente virtuale attivo
echo.

:: Aggiorna pip
echo [4/5] Aggiornamento pip...
python -m pip install --upgrade pip --quiet
echo OK - pip aggiornato
echo.

:: Installa dipendenze
echo [5/5] Installazione dipendenze (potrebbe richiedere alcuni minuti)...
echo.
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo.
    echo ERRORE durante l'installazione delle dipendenze!
    echo Prova ad eseguire manualmente: pip install -r requirements.txt
    pause
    exit /b 1
)

:: Crea directory necessarie
echo.
echo Creazione struttura cartelle...
mkdir data 2>nul
mkdir data\historical 2>nul
mkdir models 2>nul
mkdir logs 2>nul
mkdir backtester\reports 2>nul
echo OK - Struttura cartelle creata

:: Download dati NLTK per NLP
echo.
echo Download risorse NLP (VADER)...
python -c "import nltk; nltk.download('vader_lexicon', quiet=True); nltk.download('punkt', quiet=True)" 2>nul
echo OK - Risorse NLP scaricate

echo.
echo ╔══════════════════════════════════════════════════════╗
echo ║          INSTALLAZIONE COMPLETATA! ✓                 ║
echo ╚══════════════════════════════════════════════════════╝
echo.
echo PROSSIMI PASSI:
echo.
echo 1. Apri config.yaml con un editor di testo
echo 2. Inserisci le tue credenziali Alpaca:
echo    - alpaca.paper.api_key
echo    - alpaca.paper.api_secret
echo 3. (Opzionale) Configura il bot Telegram
echo 4. Doppio click su start_bot.bat per avviare
echo.
echo Per aprire la dashboard: start_dashboard.bat
echo Per il backtest: python main.py backtest
echo.
pause
