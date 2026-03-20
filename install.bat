@echo off
title Trading Bot - Installazione
color 0A

echo.
echo =====================================================
echo       TRADING BOT - INSTALLAZIONE AUTOMATICA
echo =====================================================
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
echo OK - Python trovato
echo.

:: Crea ambiente virtuale
echo [2/5] Creazione ambiente virtuale Python...
if not exist "venv" (
    python -m venv venv
    if %errorlevel% neq 0 (
        echo ERRORE creazione venv. Installo direttamente...
        goto install_direct
    )
    echo OK - Ambiente virtuale creato
) else (
    echo OK - Ambiente virtuale gia esistente
)
echo.

:: Attiva ambiente virtuale
echo [3/5] Attivazione ambiente virtuale...
call venv\Scripts\activate.bat
if %errorlevel% neq 0 (
    echo AVVISO: Attivazione venv fallita, installo nel Python di sistema...
    goto install_direct
)
echo OK - Ambiente virtuale attivo
goto install_deps

:install_direct
echo Installazione nel Python di sistema...

:install_deps
:: Aggiorna pip
echo [4/5] Aggiornamento pip...
python -m pip install --upgrade pip --quiet
echo OK - pip aggiornato
echo.

:: Installa dipendenze
echo [5/5] Installazione dipendenze (potrebbe richiedere alcuni minuti)...
echo.
python -m pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo.
    echo ERRORE durante l'installazione!
    echo Prova manualmente: python -m pip install -r requirements.txt
    pause
    exit /b 1
)

:: Crea directory necessarie
echo.
echo Creazione struttura cartelle...
if not exist "data" mkdir data
if not exist "data\historical" mkdir data\historical
if not exist "models" mkdir models
if not exist "logs" mkdir logs
if not exist "backtester\reports" mkdir backtester\reports
echo OK - Struttura cartelle creata

:: Download dati NLTK per NLP
echo.
echo Download risorse NLP...
python -c "try:\n    import nltk\n    nltk.download('vader_lexicon', quiet=True)\nexcept: pass" 2>nul
echo OK

echo.
echo =====================================================
echo          INSTALLAZIONE COMPLETATA!
echo =====================================================
echo.
echo PROSSIMI PASSI:
echo.
echo 1. config.yaml e' gia configurato con le tue API keys
echo 2. Doppio click su start_bot.bat per avviare
echo 3. Doppio click su start_dashboard.bat per la dashboard
echo.
pause
