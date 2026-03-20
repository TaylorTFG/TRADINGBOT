@echo off
chcp 65001 >nul
title Trading Bot - Stop
color 0C

echo.
echo ╔══════════════════════════════════════════════════════╗
echo ║              TRADING BOT - STOP                      ║
echo ╚══════════════════════════════════════════════════════╝
echo.

:: Termina il processo Python del bot
echo Ricerca processi Trading Bot...
tasklist /FI "IMAGENAME eq python.exe" 2>NUL | find /I "python.exe"

if %errorlevel% == 0 (
    echo.
    echo Attenzione: Questo fermerà TUTTI i processi Python in esecuzione.
    echo Sei sicuro? (S/N)
    set /p confirm=
    if /i "%confirm%"=="S" (
        taskkill /F /IM python.exe /FI "WINDOWTITLE eq Trading Bot*" 2>nul
        echo Bot fermato.
    ) else (
        echo Operazione annullata.
    )
) else (
    echo Nessun processo bot trovato in esecuzione.
)

echo.
pause
