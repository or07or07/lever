@echo off
REM Lever - Start the application server
REM
REM Usage:
REM   start.bat         - Start in production mode (no reload)
REM   start.bat --dev   - Start in dev mode (auto-reload on file changes)

setlocal enabledelayedexpansion
cd /d "%~dp0"

REM ---- Pre-flight checks ----
if not exist ".venv\Scripts\python.exe" (
    echo ERROR: Virtual environment not found. Run setup.bat first.
    pause & exit /b 1
)

if not exist ".env" (
    echo ERROR: .env file not found. Run setup.bat first.
    pause & exit /b 1
)

REM ---- Read settings from .env ----
set PORT=8500
set HOST=0.0.0.0
set DB_URL=

for /f "usebackq tokens=1,2 delims==" %%a in (".env") do (
    if "%%a"=="PORT" set PORT=%%b
    if "%%a"=="HOST" set HOST=%%b
    if "%%a"=="DATABASE_URL" set DB_URL=%%b
)

REM ---- Determine backend and reload mode ----
set RELOAD_FLAG=
set ENV_LABEL=production
if "%1"=="--dev" (
    set RELOAD_FLAG=--reload
    set ENV_LABEL=development
)

set DB_LABEL=SQLite (local)
echo !DB_URL! | findstr /i "postgresql" >nul
if !errorlevel! equ 0 set DB_LABEL=PostgreSQL (10.0.23.25)

echo.
echo =========================================
echo  Lever  ^|  %ENV_LABEL%
echo =========================================
echo   URL:      http://%HOST%:%PORT%
echo   API docs: http://%HOST%:%PORT%/api/docs
echo   Database: %DB_LABEL%
echo   Press Ctrl+C to stop.
echo =========================================
echo.

REM ---- Launch ----
.venv\Scripts\python -m uvicorn app:app --host %HOST% --port %PORT% %RELOAD_FLAG%

if %errorlevel% neq 0 (
    echo.
    echo ERROR: Server exited with error code %errorlevel%.
    echo.
    echo   Common causes:
    echo     - Port %PORT% already in use (another Lever instance running?)
    echo     - Database unreachable (check .env DATABASE_URL)
    echo     - Missing dependencies (run setup.bat again)
    echo.
    pause
)

