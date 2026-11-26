@echo off
setlocal EnableExtensions
cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
    echo [error] .venv not found. Create it and install requirements first:
    echo   python -m venv .venv
    echo   .venv\Scripts\activate
    echo   pip install -r requirements.txt
    exit /b 1
)

echo [1/2] Installing dependencies and building dist\ambilight.exe ...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m pip install -U pyinstaller
if errorlevel 1 exit /b 1

".venv\Scripts\pyinstaller.exe" ^
    --noconfirm --clean ^
    --onefile --noconsole --name ambilight ^
    --distpath dist ^
    --workpath build\pyinstaller ^
    --specpath build ^
    --hidden-import pystray._win32 ^
    --collect-submodules pystray ^
    ambilight.py
if errorlevel 1 exit /b 1

if not exist "dist\ambilight.exe" (
    echo [error] dist\ambilight.exe was not produced.
    exit /b 1
)
echo Built: dist\ambilight.exe

echo [2/2] Looking for Inno Setup ^(ISCC.exe^) ...
set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"
if not defined ISCC (
    where ISCC >nul 2>&1
    if not errorlevel 1 (
        for /f "delims=" %%I in ('where ISCC 2^>nul') do (
            if not defined ISCC set "ISCC=%%I"
        )
    )
)

if not defined ISCC (
    echo Inno Setup not found — skipped AmbilightRGB-Setup.exe
    echo Install Inno Setup 6 and re-run to produce the installer.
    exit /b 0
)

echo Compiling build\installer.iss with:
echo   %ISCC%
"%ISCC%" "%~dp0installer.iss"
if errorlevel 1 exit /b 1

if exist "dist\AmbilightRGB-Setup.exe" (
    echo Done: dist\AmbilightRGB-Setup.exe
) else (
    echo [warn] ISCC finished but dist\AmbilightRGB-Setup.exe not found.
)
exit /b 0
