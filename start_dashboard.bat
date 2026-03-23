@echo off
chcp 65001 > nul 2>&1
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
title Trading Bot - Dashboard
color 0B

echo.
echo =====================================================
echo          TRADING BOT - DASHBOARD
echo =====================================================
echo.

set PYTHON=python

REM Disabilita telemetry e prompt di Streamlit
set STREAMLIT_TELEMETRY_ENABLED=false
set STREAMLIT_CLIENT_TOOLBARMODE=minimal

echo Avvio Streamlit in background...
start "Streamlit Dashboard" cmd /k "%PYTHON% -m streamlit run dashboard/app.py --server.port=8501 --client.showErrorDetails=false"

echo Attendo avvio server (5 secondi)...
timeout /t 5 /nobreak > nul

echo Apertura browser su http://localhost:8501
start "" "http://localhost:8501"

echo.
echo Dashboard avviata! Controlla il browser.
echo Per fermare: chiudi la finestra "Streamlit" oppure premi Ctrl+C in essa.
echo.
pause
