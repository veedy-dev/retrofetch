@echo off
setlocal
cd /d "%~dp0"

set VENV_PY=.venv\Scripts\python.exe

if not exist "%VENV_PY%" (
    echo First-run setup: creating .venv and installing retrofetch...
    python -m venv .venv
    if errorlevel 1 (
        echo Failed to create venv. Ensure 'python' 3.10+ is on PATH.
        pause
        exit /b 1
    )
    "%VENV_PY%" -m pip install --upgrade pip
    "%VENV_PY%" -m pip install -e .
    if errorlevel 1 (
        echo Install failed. See output above.
        pause
        exit /b 1
    )
)

"%VENV_PY%" -m retrofetch tui %*
set RC=%ERRORLEVEL%
if %RC% NEQ 0 pause
exit /b %RC%
