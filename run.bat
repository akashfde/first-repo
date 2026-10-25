@echo off
setlocal
cd /d "%~dp0"



echo.
echo  o9 Self Heal Agent
echo  ==================
echo.

REM ── Check Python ──────────────────────────────────────────────────
where python >nul 2>&1
if errorlevel 1 (
    echo  [FAIL] Python not found.
    echo         Install Python 3.8+ from https://www.python.org/downloads/
    pause
    exit /b 1
)
echo  [OK] Python found

REM ── Check Claude CLI ───────────────────────────────────────────────
where claude >nul 2>&1
if errorlevel 1 (
    echo  [FAIL] Claude CLI ^(claude^) not found.
    echo         Install Claude Code from https://claude.ai/code then re-run.
    pause
    exit /b 1
)
echo  [OK] Claude CLI found

echo.
echo  Starting server on http://localhost:5173 ...
echo  Active Rule Triage : http://localhost:5173/
echo  Self Heal Agent    : http://localhost:5173/self-heal
echo.

REM Open browser after a short delay
start "" /b cmd /c "timeout /t 2 >nul && start http://localhost:5173"

REM Start Python server (foreground — Ctrl+C to stop)
python server.py

pause
