<#============================================================================
  JobHunter AI — Run script
  Author: ghanendrasahu
  Purpose: One‑script launcher for the most common commands:
    • Install deps + Playwright browser
    • Run CLI (interactive or PDF)
    • Run Streamlit dashboard
    • Run FastAPI server
    • Run tests + coverage
    • Quick lint/mypy check
============================================================================#>

$VerbosePreference = "SilentlyContinue"
$ErrorActionPreference = "Stop"

# ---- Helper: ensure we're in the repo root ----
$RepoRoot = "C:\Users\ghane\Documents\ALL PROJECTS\DATA SCIENCE\JobHunter AI"
if (-not (Test-Path -Path "$RepoRoot\pyproject.toml")) {
    Write-Verbose "Not in repo root; using CWD: $($pwd.ProviderPath)"
    $RepoRoot = $pwd.ProviderPath
}
Set-Location -Path $RepoRoot

function Install-Deps {
    Write-Host "`n[1/5] Installing runtime + dev deps ..." -ForegroundColor Cyan
    & python -m pip install -r requirements.txt 2>&1 | Write-Progress -PassThru
    & python -m pip install -r requirements-dev.txt 2>&1 | Write-Progress -PassThru
    Write-Host "✅  Dependencies installed." -ForegroundColor Green
}

function Install-Browser {
    Write-Host "`n[2/5] Installing Playwright chromium ..."
    & python -m playwright install chromium 2>&1 | Write-Progress -PassThru
    Write-Host "✅  Browser installed." -ForegroundColor Green
}

function Run-CLI {
    Write-Host "`n[3/5] Running CLI ..." -ForegroundColor Cyan
    & python -m jobhunter 2>&1
}

function Run-Streamlit {
    Write-Host "`n[4/5] Launching Streamlit dashboard ..." -ForegroundColor Cyan
    & jobhunter-web 2>&1
}

function Run-API {
    Write-Host "`n[5/5] Starting FastAPI server (http://localhost:8000) ..." -ForegroundColor Cyan
    & uvicorn jobhunter.api:app --reload --port 8000 2>&1
}

function Run-Tests {
    Write-Host "`nRunning test suite ..." -ForegroundColor Cyan
    & python -m pytest -q 2>&1
    $passed = ($?)

    # coverage gate matches CI (≥40%)
    Write-Host "`n[Coverage] Running with --cov ..." -ForegroundColor Cyan
    & python -m pytest --cov=jobhunter --cov-report=term-missing --cov-fail-under=40 -q 2>&1
}

function Show-Menu {
    Clear-Host
    Write-Host "════════════════════════════════════════════════════════════════════════════" -ForegroundColor Yellow
    Write-Host "  JobHunter AI — Runtime Launcher" -ForegroundColor White
    Write-Host "════════════════════════════════════════════════════════════════════════════" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  1) Install dependencies + dev deps"
    Write-Host "  2) Install Playwright chromium browser"
    Write-Host "  3) Run CLI (interactive prompt)"
    Write-Host "  4) Run Streamlit dashboard (http://localhost:8501)"
    Write-Host "  5) Run FastAPI server (http://localhost:8000)"
    Write-Host "  6) Run tests + coverage gate (≥40%)"
    Write-Host "  7) Quick lint + mypy check"
    Write-Host "  0) Exit"
    Write-Host ""
    $choice = Read-Host "Select option"
    return $choice
}

# ---- Main dispatch ----
$choice = Show-Menu

switch ($choice) {
    "1" { Install-Deps }
    "2" { Install-Browser }
    "3" { Run-CLI }
    "4" { Run-Streamlit }
    "5" { Run-API }
    "6" { Run-Tests }
    "7" {
        Write-Host "`n--- ruff check ---" -ForegroundColor Cyan
        & ruff check src tests 2>&1
        Write-Host "`n--- mypy check ---" -ForegroundColor Cyan
        & mypy src 2>&1
    }
    "0" { Write-Host "Good bye!"; exit 0 }
    default { Write-Host "Invalid choice — try again."; Start-Sleep -Seconds 1 }
}