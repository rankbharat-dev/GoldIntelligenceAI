@echo off
REM ============================================================
REM  Candle Intelligence - one-click start (double-click me)
REM  Starts: Docker/PostgreSQL, MT5 terminal, Research API (:8000),
REM          Web app (:3000), then opens the browser.
REM  MCP agents (mt5 + research) are stdio servers: Claude Code
REM  starts them itself from .mcp.json once the API is up.
REM ============================================================
setlocal
cd /d "%~dp0"
title Candle Intelligence - Launcher

set "ROOT=%~dp0"
set "DOCKER_EXE=%LOCALAPPDATA%\Programs\DockerDesktop\Docker Desktop.exe"
if not exist "%DOCKER_EXE%" set "DOCKER_EXE=%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
set "MT5_EXE=%ProgramFiles%\MetaTrader 5\terminal64.exe"

echo.
echo  [1/5] Docker Desktop + PostgreSQL ...
docker info >nul 2>&1
if errorlevel 1 (
    if exist "%DOCKER_EXE%" (
        start "" "%DOCKER_EXE%"
        echo        Docker Desktop start ho raha hai, wait...
        set /a TRIES=0
        call :wait_docker
    ) else (
        echo        [!] Docker Desktop nahi mila - PostgreSQL skip.
    )
)
docker compose up -d
if errorlevel 1 echo        [!] docker compose fail hua - research ledger kaam nahi karega.

echo.
echo  [2/5] MetaTrader 5 terminal ...
tasklist /FI "IMAGENAME eq terminal64.exe" 2>nul | find /I "terminal64.exe" >nul
if errorlevel 1 (
    if exist "%MT5_EXE%" (
        start "" "%MT5_EXE%"
        echo        MT5 open kiya. Demo account + Algo Trading OFF check karein.
    ) else (
        echo        [!] MT5 nahi mila: %MT5_EXE%
    )
) else (
    echo        MT5 pehle se chal raha hai.
)

echo.
echo  [3/5] Research API  http://127.0.0.1:8000 ...
REM Always restart: the API has no auto-reload, so an old process keeps
REM serving old code (new endpoints then return 404 Not Found).
for /f "tokens=5" %%I in ('netstat -ano ^| findstr /R /C:":8000 .*LISTENING"') do (
    echo        Purana API process band kar raha hoon (PID %%I^)
    taskkill /PID %%I /T /F >nul 2>&1
)
ping -n 3 127.0.0.1 >nul
start "CI - Research API :8000" cmd /k ""%ROOT%.venv\Scripts\ci-api.exe""

echo.
echo  [4/5] Web app  http://localhost:3000 ...
call :port_open 3000
if errorlevel 1 (
    start "CI - Web App :3000" cmd /k "npm --prefix "%ROOT%apps\web" run dev"
) else (
    echo        Web app pehle se chal raha hai.
)

echo.
echo  [5/5] Servers ready hone ka wait ...
call :wait_url http://127.0.0.1:8000/api/strategies API
call :wait_url http://localhost:3000 Web

start "" http://localhost:3000
start "" http://127.0.0.1:8000/docs

echo.
echo  ============================================================
echo   Sab chalu hai:
echo     Web app     : http://localhost:3000
echo     Explorer    : http://localhost:3000/explorer
echo     API docs    : http://127.0.0.1:8000/docs
echo     PostgreSQL  : 127.0.0.1:5434
echo   MCP agents Claude Code khud start karta hai (.mcp.json).
echo   Band karne ke liye: Stop_Candle_Intelligence.bat
echo  ============================================================
echo.
pause
exit /b 0

REM ---------- helpers ----------
:wait_docker
ping -n 3 127.0.0.1 >nul
docker info >nul 2>&1
if not errorlevel 1 exit /b 0
set /a TRIES+=1
if %TRIES% GEQ 60 (
    echo        [!] Docker 3 minute mein ready nahi hua.
    exit /b 1
)
goto wait_docker

:port_open
netstat -ano | findstr /R /C:":%1 .*LISTENING" >nul
exit /b %errorlevel%

:wait_url
set /a W=0
:wait_url_loop
curl -sf -o nul --max-time 2 %1 && (echo        %2 ready. & exit /b 0)
set /a W+=1
if %W% GEQ 90 (echo        [!] %2 abhi ready nahi - uski window check karein. & exit /b 1)
ping -n 3 127.0.0.1 >nul
goto wait_url_loop
