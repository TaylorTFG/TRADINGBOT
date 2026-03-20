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

%PYTHON% -c "import streamlit" 2>nul
if %errorlevel% neq 0 (
    echo Installazione dipendenze...
    %PYTHON% -m pip install -r requirements.txt
)

echo Avvio dashboard su http://localhost:8501
echo Per fermare: Ctrl+C
echo.

start "" "http://localhost:8501"
%PYTHON% -m streamlit run dashboard/app.py --server.port=8501 --server.headless=false --browser.gatherUsageStats=false

pause
