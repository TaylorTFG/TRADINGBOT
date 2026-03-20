@echo off
chcp 65001 >nul
title Trading Bot - In Esecuzione
color 0A

echo.
echo ╔══════════════════════════════════════════════════════╗
echo ║              TRADING BOT - AVVIO                     ║
echo ╚══════════════════════════════════════════════════════╝
echo.

:: Verifica ambiente virtuale
if not exist "venv\Scripts\activate.bat" (
    echo ERRORE: Ambiente virtuale non trovato.
    echo Esegui prima install.bat
    pause
    exit /b 1
)

:: Attiva ambiente virtuale
call venv\Scripts\activate.bat

:: Verifica config.yaml
if not exist "config.yaml" (
    echo ERRORE: config.yaml non trovato!
    echo Assicurati di essere nella cartella del bot.
    pause
    exit /b 1
)

echo Ambiente virtuale attivo
echo Avvio bot in modalità PAPER TRADING...
echo.
echo Per fermare il bot: Ctrl+C o usa stop_bot.bat
echo Per la dashboard: start_dashboard.bat (in una nuova finestra)
echo.
echo ═══════════════════════════════════════════════════════
echo.

:: Avvia il bot
python main.py bot

echo.
echo Bot fermato.
pause
