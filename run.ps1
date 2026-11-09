<#
.SYNOPSIS
    One-command runner for JobHunter AI (Windows).

.DESCRIPTION
    Defaults to the Streamlit dashboard. -Service picks the CLI, the REST API,
    or Docker instead. -Menu opens the interactive utility menu (install deps,
    install the browser, tests + coverage, lint + mypy). Everything uses uv.

.EXAMPLE
    .\run.ps1                      # sync deps + open the dashboard
    .\run.ps1 -Service api         # sync deps + start FastAPI on :8000
    .\run.ps1 -Service cli         # sync deps + launch the interactive CLI
    .\run.ps1 -Service docker      # build + run via docker compose
    .\run.ps1 -Resume resume.pdf   # dashboard, plus run a PDF through the CLI
    .\run.ps1 -Menu                # interactive utility menu
#>

[CmdletBinding()]
param(
    [ValidateSet("dashboard", "cli", "api", "docker")]
    [string]$Service = "dashboard",
    [string]$Resume = "",
    [switch]$SkipSync,
    [switch]$Menu
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $Root

function Write-Step($Message) { Write-Host "==> $Message" -ForegroundColor Cyan }

# --- prerequisites ---------------------------------------------------------
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Error "uv is not installed. Install it first: https://docs.astral.sh/uv/#installation"
}

if (-not (Test-Path -LiteralPath ".env")) {
    if (Test-Path -LiteralPath ".env.example") {
        Write-Step "No .env found - copying .env.example to .env"
        Copy-Item ".env.example" ".env"
        Write-Host "  Edit .env and add your API keys (OPENAI_API_KEY etc.) as needed." -ForegroundColor Yellow
    }
}

# --- interactive utility menu (-Menu) ---------------------------------------
function Show-Menu {
    Clear-Host
    Write-Host "============================================================" -ForegroundColor Yellow
    Write-Host "  JobHunter AI - Utility Menu" -ForegroundColor White
    Write-Host "============================================================" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  1) Sync dependencies (uv sync --locked)"
    Write-Host "  2) Install Playwright browser (chromium)"
    Write-Host "  3) Run the test suite + coverage"
    Write-Host "  4) Ruff check"
    Write-Host "  5) mypy (strict, src/)"
    Write-Host "  6) Run the Streamlit dashboard"
    Write-Host "  7) Run the FastAPI server"
    Write-Host "  8) Run the CLI"
    Write-Host "  0) Exit"
    Write-Host ""
    return Read-Host "Select option"
}

function Invoke-Menu {
    while ($true) {
        switch (Show-Menu) {
            "1" { Write-Step "Syncing dependencies"; & uv sync --locked }
            "2" { Write-Step "Installing Playwright chromium"; & uv run python -m playwright install chromium }
            "3" { Write-Step "Running tests with coverage"; & uv run pytest --cov=jobhunter --cov-report=term-missing }
            "4" { Write-Step "ruff check"; & uv run ruff check . }
            "5" { Write-Step "mypy"; & uv run mypy src }
            "6" { Write-Step "Starting dashboard"; & uv run jobhunter-web }
            "7" { Write-Step "Starting FastAPI on :8000"; & uv run uvicorn jobhunter.api:app --reload --port 8000 }
            "8" { Write-Step "Starting CLI"; & uv run python -m jobhunter }
            "0" { Write-Host "Good bye!"; break }
            default { Write-Host "Invalid choice - try again."; Start-Sleep -Seconds 1 }
        }
    }
}

if ($Menu) { Invoke-Menu; exit 0 }

# --- install dependencies --------------------------------------------------
if (-not $SkipSync) {
    Write-Step "Syncing dependencies (uv sync --locked)"
    & uv sync --locked
    if ($LASTEXITCODE -ne 0) { Write-Error "uv sync failed" }
}

# --- launch ----------------------------------------------------------------
switch ($Service) {
    "dashboard" {
        Write-Step "Starting Streamlit dashboard at http://localhost:8501"
        if ($Resume) {
            Write-Host "  Note: -Resume only applies to the CLI service." -ForegroundColor Yellow
        }
        & uv run jobhunter-web
    }
    "cli" {
        Write-Step "Starting JobHunter CLI"
        if ($Resume) {
            & uv run python -m jobhunter $Resume
        } else {
            & uv run python -m jobhunter
        }
    }
    "api" {
        Write-Step "Starting FastAPI at http://localhost:8000 (docs at /docs)"
        & uv run uvicorn jobhunter.api:app --reload --port 8000
    }
    "docker" {
        Write-Step "Building and starting via docker compose"
        & docker compose up --build
    }
}
