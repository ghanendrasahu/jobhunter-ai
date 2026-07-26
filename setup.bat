@echo off
title JobHunter AI Setup

echo ============================================
echo  JobHunter AI — One-Click Setup
echo ============================================
echo.

echo [1/3] Installing Python dependencies...
call pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo FAILED: pip install failed.
    pause
    exit /b 1
)
echo Done.
echo.

echo [2/3] Installing Playwright browser (Chromium)...
call playwright install chromium
if %errorlevel% neq 0 (
    echo WARNING: Playwright install failed. Job scraping won't work, but core features will still run.
)
echo Done.
echo.

echo [3/3] Creating .env file...
if not exist .env (
    copy .env.example .env >nul
    echo Created .env from .env.example — edit it to add your API keys.
) else (
    echo .env already exists — skipping.
)
echo.

echo ============================================
echo  Setup complete!
echo ============================================
echo.
echo  Run with one of these commands:
echo.
echo    python run.py                  (CLI)
echo    streamlit run streamlit_app.py (Dashboard)
echo    uvicorn app:app --port 8000    (API)
echo    python main.py                 (Dashboard - alias)
echo.
pause
