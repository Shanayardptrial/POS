@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul 2>&1
title Restaurant POS System
color 0A

echo.
echo ========================================
echo   Restaurant POS System — Launcher
echo ========================================
echo.

REM -- Resolve script directory (so bat works from any cwd) --
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
cd /d "%ROOT%"

REM -- Load .env if present (simple KEY=VALUE parser) --
if exist ".env" (
    echo [INFO] Loading .env ...
    for /f "usebackq eol=# tokens=1,* delims==" %%A in (".env") do (
        if not "%%A"=="" if not "%%B"=="" (
            set "%%A=%%B"
        )
    )
)
if "%PORT%"=="" set "PORT=5500"
if "%HOST%"=="" set "HOST=127.0.0.1"
if "%HOST%"=="0.0.0.0" (
    set "BROWSER_HOST=127.0.0.1"
) else (
    set "BROWSER_HOST=%HOST%"
)
set "URL=http://%BROWSER_HOST%:%PORT%/"

REM -- Prefer .conda env if present --
set "PY_CMD=python"
if exist ".conda\Scripts\activate.bat" (
    echo [OK] Found .conda environment — activating ...
    call ".conda\Scripts\activate.bat"
    if exist ".conda\python.exe" set "PY_CMD=.conda\python.exe"
    goto :check_python
)
if exist ".conda\python.exe" (
    echo [OK] Found .conda\python.exe — using it
    set "PY_CMD=.conda\python.exe"
    set "PATH=%ROOT%\.conda;%ROOT%\.conda\Scripts;%PATH%"
    goto :check_python
)

REM -- Fallback: venv --
if exist "venv\Scripts\python.exe" (
    echo [OK] Found venv — activating
    call "venv\Scripts\activate.bat"
    set "PY_CMD=python"
    goto :check_python
)
if exist ".venv\Scripts\python.exe" (
    echo [OK] Found .venv — activating
    call ".venv\Scripts\activate.bat"
    set "PY_CMD=python"
    goto :check_python
)

:check_python
echo [INFO] Using Python: %PY_CMD%
%PY_CMD% --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Tried: %PY_CMD%
    echo         Install Python 3.10+ from https://www.python.org/downloads/
    echo         ^(check "Add Python to PATH" during install^)
    echo         Or create env:  python -m venv venv  ^&^&  venv\Scripts\activate
    pause
    exit /b 1
)
echo [OK] Python detected
%PY_CMD% --version

REM -- Check dependencies --
%PY_CMD% -c "import flask" >nul 2>&1
if errorlevel 1 (
    echo [INFO] Flask not found — installing dependencies ...
    if exist "requirements.txt" (
        %PY_CMD% -m pip install --upgrade pip
        %PY_CMD% -m pip install -r requirements.txt
        if errorlevel 1 (
            echo [ERROR] pip install failed. See above for details.
            pause
            exit /b 1
        )
        echo [OK] Dependencies installed
    ) else (
        echo [WARN] requirements.txt not found — skipping install
    )
) else (
    echo [OK] Flask is installed
)

REM -- Ensure data/log dirs exist --
if not exist "data" mkdir "data"
if not exist "data\admin" mkdir "data\admin"
if not exist "data\backups" mkdir "data\backups"
if not exist "logs" mkdir "logs"
if not exist "data\.gitkeep" type nul > "data\.gitkeep"
echo [OK] Data directories ready

REM -- Auto-open browser after short delay (non-blocking) --
echo [INFO] Will auto-open %URL% in 3s ...
start /b cmd /c "timeout /t 3 /nobreak >nul & start """" "%URL%""

echo.
echo ========================================
echo   Starting Restaurant POS Server...
echo   POS:   %URL%
echo   Admin: %URL%admin  (admin / admin123)
echo   Logs:  logs\pos.log  (also console)
echo   Press Ctrl+C to stop
echo ========================================
echo.

REM -- Show recent logs in background window if requested --
REM start "POS Logs" powershell -NoExit -Command "Get-Content -Wait -Tail 50 'logs\pos.log'"

%PY_CMD% pos_app.py
set "EXITCODE=%ERRORLEVEL%"

echo.
if not "%EXITCODE%"=="0" (
    echo [ERROR] Server exited with code %EXITCODE%
    echo         Check logs\pos.log for details
    if exist "logs\pos.log" (
        echo --- last 40 lines of logs\pos.log ---
        powershell -Command "Get-Content 'logs\pos.log' -Tail 40"
    )
    pause
    exit /b %EXITCODE%
)

pause
endlocal
