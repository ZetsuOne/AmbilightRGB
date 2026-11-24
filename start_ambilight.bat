@echo off
setlocal
cd /d "%~dp0"

tasklist /FI "IMAGENAME eq OpenRGB.exe" 2>NUL | find /I "OpenRGB.exe" >NUL
if not errorlevel 1 goto :start_ambilight

if not exist "bin\OpenRGB\openrgb.exe" goto :start_ambilight

rem First run if SMBus driver is missing or OpenRGB profile folder does not exist yet
set "FIRST_RUN=0"
sc query WinRing0_1_2_0 >nul 2>&1
if errorlevel 1 set "FIRST_RUN=1"
if not exist "%APPDATA%\OpenRGB\" set "FIRST_RUN=1"

if "%FIRST_RUN%"=="1" (
    echo First run: initializing OpenRGB / WinRing0 driver ^(one-time admin prompt^)...
    powershell -NoProfile -Command "Start-Process -FilePath '%~dp0bin\OpenRGB\openrgb.exe' -Verb RunAs"
    timeout /t 5 /nobreak >nul
) else (
    rem Driver + profile already present: start SDK server quietly, no UAC
    powershell -NoProfile -Command "Start-Process -FilePath '%~dp0bin\OpenRGB\openrgb.exe' -ArgumentList '--server','--startminimized'"
    timeout /t 3 /nobreak >nul
)

:start_ambilight
if exist ".venv\Scripts\pythonw.exe" (
    ".venv\Scripts\python.exe" ambilight.pyw
) else (
    python ambilight.pyw
)
pause
