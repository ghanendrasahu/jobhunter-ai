<#
.SYNOPSIS
    One-command runner for JobHunter AI (Windows).

.DESCRIPTION
    Installs dependencies (uv) and starts the app. Defaults to the Streamlit
    dashboard; use -Service to pick the CLI, the REST API, or Docker instead.

.EXAMPLE
    .\run.ps1                      # sync deps + open the dashboard
    .\run.ps1 -Service api         # sync deps + start FastAPI on :8000
    .\run.ps1 -Service cli         # sync deps + launch the interactive CLI
    .\run.ps1 -Service docker      # build + run via docker compose
    .\run.ps1 -Resume resume.pdf   # dashboard, plus run a PDF through the CLI
#>

[CmdletBinding()]
param(
    [ValidateSet("dashboard", "cli", "api", "docker")]
    [string]$Service = "dashboard",
    [string]$Resume = "",
    [switch]$SkipSync
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
