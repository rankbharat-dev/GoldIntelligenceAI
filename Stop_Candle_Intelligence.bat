@echo off
REM Stops the Research API (:8000) and Web app (:3000) and the PostgreSQL container.
REM MT5 and Docker Desktop are left running.
setlocal
cd /d "%~dp0"
title Candle Intelligence - Stop

for %%P in (8000 3000) do (
    for /f "tokens=5" %%I in ('netstat -ano ^| findstr /R /C:":%%P .*LISTENING"') do (
        echo  Port %%P band kar raha hoon (PID %%I^)
        taskkill /PID %%I /T /F >nul 2>&1
    )
)
docker compose stop
echo.
echo  API, Web app aur PostgreSQL band. MT5 chalta rahega.
pause
