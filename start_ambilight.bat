@echo off
setlocal
cd /d "%~dp0"

set "PYW="
if exist ".venv\Scripts\pythonw.exe" set "PYW=.venv\Scripts\pythonw.exe"
if not defined PYW (
    where pythonw >nul 2>&1
    if not errorlevel 1 set "PYW=pythonw"
)
if not defined PYW (
    echo Python not found. Install Python 3.10+ or create .venv and pip install -r requirements.txt
    pause
    exit /b 1
)

start "" "%PYW%" "%~dp0ambilight.pyw"
exit /b 0
