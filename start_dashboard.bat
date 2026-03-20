@echo off
chcp 65001 >nul
title Trading Bot - Dashboard
color 0B

echo.
echo ╔══════════════════════════════════════════════════════╗
echo ║          TRADING BOT - DASHBOARD                     ║
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

echo Avvio dashboard Streamlit...
echo La dashboard si aprirà nel browser: http://localhost:8501
echo.
echo Per fermare la dashboard: Ctrl+C
echo.

:: Avvia dashboard e apri browser
start /B "" python -m streamlit run dashboard/app.py --server.port=8501 --server.headless=false --browser.gatherUsageStats=false

:: Attendi e apri browser
timeout /t 3 /nobreak >nul
start "" "http://localhost:8501"

:: Mantieni la finestra aperta
echo Dashboard in esecuzione su http://localhost:8501
pause
