<#============================================================================
  JobHunter AI — Run script
  Author: ghanendrasahu
  Purpose: One-script launcher for the most common commands:
    • Run the Streamlit dashboard (default — no prompt)
    • Show the interactive menu with all options (use: run.ps1 -Menu)
    • Install deps + Playwright browser, run CLI, run FastAPI,
      run tests + coverage, lint/mypy check
============================================================================#>

param(
    [switch]$Menu
)

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

function Invoke-CLI {
    Write-Host "`n[3/5] Running CLI ..." -ForegroundColor Cyan
    & python -m jobhunter 2>&1
}

function Invoke-Streamlit {
    Write-Host "`nLaunching JobHunter AI dashboard → http://localhost:8501 ..." -ForegroundColor Cyan
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        & uv run python -m jobhunter.web 2>&1
    } else {
        & python -m jobhunter.web 2>&1
    }
}

function Invoke-API {
    Write-Host "`n[5/5] Starting FastAPI server (http://localhost:8000) ..." -ForegroundColor Cyan
    & uvicorn jobhunter.api:app --reload --port 8000 2>&1
}

function Invoke-Tests {
    Write-Host "`nRunning test suite ..." -ForegroundColor Cyan
    & python -m pytest -q 2>&1

    # coverage gate matches CI (≥40%)
    Write-Host "`n[Coverage] Running with --cov ..." -ForegroundColor Cyan
    & python -m pytest --cov=jobhunter --cov-report=term-missing --cov-fail-under=40 -q 2>&1
}

function Start-JobHunterBrowser {
    Write-Host "`nLaunching the dedicated JobHunter Chrome window (automation profile, port 9222)..." -ForegroundColor Cyan
    $chrome = "$env:ProgramFiles\Google\Chrome\Application\chrome.exe"
    if (-not (Test-Path $chrome)) { $chrome = "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe" }
    if (-not (Test-Path $chrome)) { Write-Host "Chrome not found." -ForegroundColor Red; return }

    $profileDir = Join-Path $RepoRoot "data\browser_state\automation_profile"
    New-Item -ItemType Directory -Force -Path $profileDir | Out-Null

    # Your normal Chrome profile/window is never touched, and nothing is killed.
    Start-Process $chrome -ArgumentList "--user-data-dir=`"$profileDir`"", "--remote-debugging-port=9222", "--profile-directory=Default", "--no-first-run", "--no-default-browser-check", "--start-maximized"
    Start-Sleep -Seconds 3
    try {
        $json = Invoke-RestMethod "http://localhost:9222/json/version" -TimeoutSec 5
        Write-Host "✅ JobHunter browser ready: $($json.Browser)" -ForegroundColor Green
        Write-Host "   Log in to Naukri/Indeed once in this window — sessions persist between runs." -ForegroundColor Yellow
    } catch {
        Write-Host "Browser launched, but the debug port is not responding yet. Wait a few seconds, then re-run option 8." -ForegroundColor Yellow
    }
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
    Write-Host "  8) Launch dedicated JobHunter Chrome (persistent auto-apply window)"
    Write-Host "  0) Exit"
    Write-Host ""
    $choice = Read-Host "Select option"
    return $choice
}

# ---- Main dispatch ----
if ($Menu) {
    $choice = Show-Menu

    switch ($choice) {
        "1" { Install-Deps }
        "2" { Install-Browser }
        "3" { Invoke-CLI }
        "4" { Invoke-Streamlit }
        "5" { Invoke-API }
        "6" { Invoke-Tests }
        "7" {
            Write-Host "`n--- ruff check ---" -ForegroundColor Cyan
            & ruff check src tests 2>&1
            Write-Host "`n--- mypy check ---" -ForegroundColor Cyan
            & mypy src 2>&1
        }
        "8" { Start-JobHunterBrowser }
        "0" { Write-Host "Good bye!"; exit 0 }
        default { Write-Host "Invalid choice — try again."; Start-Sleep -Seconds 1 }
    }
} else {
    # Default: launch the project (Streamlit dashboard) directly.
    Invoke-Streamlit
}