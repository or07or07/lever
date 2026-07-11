@echo off
REM Lever - First-time setup
REM Creates venv, installs deps, runs migrations, seeds the database.
REM
REM Usage:
REM   setup.bat            - Full setup (SQLite or Postgres based on .env)
REM   setup.bat --no-seed  - Setup without seeding demo data

setlocal enabledelayedexpansion
cd /d "%~dp0"

set SKIP_SEED=0
if "%1"=="--no-seed" set SKIP_SEED=1

echo.
echo =========================================
echo  Lever Setup
echo =========================================
echo.

REM ---- Check Python ----
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python not found. Install Python 3.10+ and re-run.
    pause & exit /b 1
)
for /f "tokens=*" %%i in ('python --version') do echo   Python: %%i

REM ---- Create virtual env ----
if not exist ".venv" (
    echo.
    echo [1/5] Creating virtual environment...
    python -m venv .venv
    if %errorlevel% neq 0 (
        echo ERROR: Failed to create virtual environment.
        pause & exit /b 1
    )
) else (
    echo [1/5] Virtual environment already exists, skipping.
)

REM ---- Install deps ----
echo.
echo [2/5] Installing dependencies...
.venv\Scripts\pip install -q --upgrade pip
.venv\Scripts\pip install -q -r requirements.txt
if %errorlevel% neq 0 (
    echo ERROR: pip install failed. Check requirements.txt and your network connection.
    pause & exit /b 1
)
echo   Dependencies installed.

REM ---- Copy env template ----
echo.
if not exist ".env" (
    if exist ".env.template" (
        copy ".env.template" ".env" >nul
        echo [3/5] Created .env from template.
        echo.
        echo   IMPORTANT: Open .env and review the settings.
        echo   - For PostgreSQL: uncomment the DATABASE_URL line and fill in your server details.
        echo   - Change SECRET_KEY before any network exposure.
        echo   - Change ADMIN_PASSWORD before any network exposure.
        echo.
        echo   Press any key when you have reviewed .env...
        pause >nul
    ) else (
        echo [3/5] No .env.template found - skipping.
    )
) else (
    echo [3/5] .env already exists, skipping.
)

REM ---- Load DATABASE_URL from .env to check backend type ----
set DB_URL=
for /f "usebackq tokens=1,2 delims==" %%a in (".env") do (
    if "%%a"=="DATABASE_URL" set DB_URL=%%b
)

REM ---- Run database migrations ----
echo.
echo [4/5] Running database migrations...

REM Check if this is PostgreSQL - test connectivity first
if not "!DB_URL!"=="" (
    echo   DATABASE_URL: !DB_URL!

    REM Extract host from PostgreSQL URL for connectivity check
    echo !DB_URL! | findstr /i "postgresql" >nul
    if !errorlevel! equ 0 (
        echo   Detected PostgreSQL backend.
        echo   Make sure you have run the Ubuntu setup script on 10.0.23.25 first.
        echo.
    )
)

REM Run Alembic migrations
.venv\Scripts\alembic upgrade head
if %errorlevel% neq 0 (
    echo.
    echo ERROR: Database migration failed.
    echo.
    echo   If using PostgreSQL:
    echo     1. Confirm the Ubuntu server setup script ran successfully.
    echo     2. Verify DATABASE_URL in .env is correct.
    echo     3. Test connectivity: Test-NetConnection 10.0.23.25 -Port 5432
    echo.
    echo   If using SQLite (default):
    echo     The data/ directory may have a permissions issue.
    echo.
    pause & exit /b 1
)
echo   Migrations complete.

REM ---- Seed demo data ----
echo.
if %SKIP_SEED%==1 (
    echo [5/5] Skipping seed (--no-seed flag set).
) else (
    echo [5/5] Seeding demo data...
    .venv\Scripts\python seed.py
    if %errorlevel% neq 0 (
        echo   WARNING: Seed step returned non-zero (database may already be seeded).
        echo   This is expected on re-runs. Use "python seed.py --reset" to force re-seed.
    ) else (
        echo   Demo data seeded successfully.
    )
)

echo.
echo =========================================
echo  Setup complete!
echo  Run start.bat to launch Lever.
echo =========================================
echo.
pause

