@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul 2>&1
title Restaurant POS - Server
echo.
echo ========================================
echo   Restaurant POS — Server Runner
echo ========================================
echo.

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
cd /d "%ROOT%"

if exist ".env" (
    for /f "usebackq eol=# tokens=1,* delims==" %%A in (".env") do (
        if not "%%A"=="" if not "%%B"=="" set "%%A=%%B"
    )
)
if "%PORT%"=="" set "PORT=5500"
if "%HOST%"=="" set "HOST=127.0.0.1"
if "%HOST%"=="0.0.0.0" ( set "BROWSER_HOST=127.0.0.1" ) else ( set "BROWSER_HOST=%HOST%" )
set "URL=http://%BROWSER_HOST%:%PORT%/"

REM -- Resolve Python: .conda > venv > system --
set "PY_CMD=python"
if exist ".conda\Scripts\activate.bat" (
    call ".conda\Scripts\activate.bat" >nul 2>&1
    if exist ".conda\python.exe" set "PY_CMD=.conda\python.exe"
) else if exist ".conda\python.exe" (
    set "PY_CMD=.conda\python.exe"
    set "PATH=%ROOT%\.conda;%ROOT%\.conda\Scripts;%PATH%"
) else if exist "venv\Scripts\python.exe" (
    call "venv\Scripts\activate.bat" >nul 2>&1
) else if exist ".venv\Scripts\python.exe" (
    call ".venv\Scripts\activate.bat" >nul 2>&1
)

%PY_CMD% --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found ^(tried %PY_CMD%^). Install Python 3.10+
    pause
    exit /b 1
)

%PY_CMD% -c "import flask" >nul 2>&1
if errorlevel 1 (
    echo [INFO] Installing requirements ...
    %PY_CMD% -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] pip install failed
        pause
        exit /b 1
    )
)

if not exist "logs" mkdir "logs"
echo [INFO] Auto-opening %URL% in 2s ...
start /b cmd /c "timeout /t 2 /nobreak >nul & start """" "%URL%""
echo [INFO] POS at %URL%  | Admin at %URL%admin
echo        Host=%HOST%  Port=%PORT%  (override via .env or env vars)
echo        Logs: logs\pos.log
echo        Press Ctrl+C to stop
echo.

REM -- Honor env PORT/HOST/DEBUG via config.py; just exec --
%PY_CMD% pos_app.py
set "EC=%ERRORLEVEL%"
if not "%EC%"=="0" (
    echo [ERROR] Server exited %EC% — see logs\pos.log
    if exist "logs\pos.log" powershell -Command "Get-Content 'logs\pos.log' -Tail 60"
    pause
)
endlocal
