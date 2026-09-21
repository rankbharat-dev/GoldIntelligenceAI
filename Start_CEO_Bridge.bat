@echo off
REM ============================================================
REM  CEO Work Lab bridge (optional) - double-click to start.
REM  Lets the "Agents ko abhi chalao" button on /ceo-lab start the
REM  Research Director in Claude Code headless mode (your login).
REM  Needs: the app running (Start_Candle_Intelligence.bat) and the
REM  Claude Code CLI:  npm install -g @anthropic-ai/claude-code
REM  then run "claude" once to sign in. Close this window to stop.
REM ============================================================
setlocal
cd /d "%~dp0"
title Candle Intelligence - CEO bridge
where claude >/dev/null 2>&1
if errorlevel 1 echo  [!] Claude Code CLI nahi mila - bridge chalega par agents start nahi kar payega.
echo  CEO bridge chal raha hai. Band karne ke liye yeh window close karo.
".venv\Scripts\python.exe" -m ci_api.ceo_bridge
pause
