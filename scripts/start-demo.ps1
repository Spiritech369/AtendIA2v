# scripts/start-demo.ps1
#
# One-shot bring-up of AtendIA v2 for a local demo:
#   1. Docker Desktop (start if needed, wait for daemon)
#   2. docker compose up -d (postgres + redis)
#   3. uv sync + alembic upgrade head
#   4. seed demo tenant + operator (admin@demo.com / admin123)
#   5. pnpm install + pnpm build (skipped if already built)
#   6. open browser → uvicorn (foreground, Ctrl+C to stop)
#
# Usage from any directory:
#   powershell -ExecutionPolicy Bypass -File scripts/start-demo.ps1
#
# Stops cleanly on Ctrl+C; leaves docker containers UP so the next run is fast.

$ErrorActionPreference = "Stop"

# Repo root = parent of this script's directory.
$repo = (Resolve-Path "$PSScriptRoot/..").Path
Write-Host "Repo: $repo" -ForegroundColor DarkGray

# ---- 1. Docker Desktop ----
function Test-DockerDaemon {
    try { docker ps 2>$null | Out-Null; return $true } catch { return $false }
}

if (-not (Test-DockerDaemon)) {
    $dockerExe = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    if (Test-Path $dockerExe) {
        Write-Host "Starting Docker Desktop..." -ForegroundColor Yellow
        Start-Process $dockerExe | Out-Null
        Write-Host "Waiting for daemon..." -NoNewline
        $deadline = (Get-Date).AddMinutes(2)
        while (-not (Test-DockerDaemon)) {
            if ((Get-Date) -gt $deadline) {
                Write-Host ""
                Write-Error "Docker daemon did not start in 2 min."
                exit 1
            }
            Start-Sleep -Seconds 3
            Write-Host "." -NoNewline
        }
        Write-Host " ready." -ForegroundColor Green
    } else {
        Write-Error "Docker Desktop not found at $dockerExe. Install it or start manually."
        exit 1
    }
}

# ---- 2. Compose ----
Write-Host "Starting postgres + redis..." -ForegroundColor Cyan
Set-Location $repo
docker compose up -d

Write-Host "Waiting for postgres healthy..." -NoNewline
$deadline = (Get-Date).AddMinutes(2)
while ($true) {
    $status = docker inspect -f '{{.State.Health.Status}}' atendia_postgres_v2 2>$null
    if ($status -eq "healthy") { break }
    if ((Get-Date) -gt $deadline) {
        Write-Host ""
        Write-Error "postgres not healthy in 2 min."
        exit 1
    }
    Start-Sleep -Seconds 2
    Write-Host "." -NoNewline
}
Write-Host " ready." -ForegroundColor Green

# ---- 3. Backend deps + migrations ----
Set-Location "$repo\core"
if (-not (Test-Path .env)) {
    Write-Error "core/.env missing. Copy .env.example or set DATABASE_URL etc. first."
    exit 1
}
Write-Host "uv sync..." -ForegroundColor Cyan
uv sync | Out-Null
Write-Host "alembic upgrade head..." -ForegroundColor Cyan
uv run alembic upgrade head

# ---- 4. Seed ----
Write-Host "Seeding demo user (admin@demo.com / admin123)..." -ForegroundColor Cyan
uv run python scripts/seed_demo.py

# ---- 5. Frontend ----
Set-Location "$repo\frontend"
if (-not (Test-Path node_modules)) {
    Write-Host "pnpm install (5+ min cold; cached after)..." -ForegroundColor Cyan
    pnpm install
}
if (-not (Test-Path "dist/index.html")) {
    Write-Host "pnpm build..." -ForegroundColor Cyan
    pnpm build
}

# ---- 6. Uvicorn ----
Set-Location "$repo\core"
$url = "http://localhost:8001/login"
Write-Host ""
Write-Host "================================================================" -ForegroundColor Green
Write-Host " Backend: http://localhost:8001  (sirve dist/ en /)" -ForegroundColor Green
Write-Host " Login:   admin@demo.com / admin123" -ForegroundColor Green
Write-Host " Ctrl+C para detener uvicorn (containers se quedan arriba)" -ForegroundColor Green
Write-Host "================================================================" -ForegroundColor Green
Write-Host ""

# Abrir browser DESPUES de un segundo para dar chance a uvicorn de bind.
Start-Job -ScriptBlock {
    param($u)
    Start-Sleep -Seconds 2
    Start-Process $u
} -ArgumentList $url | Out-Null

uv run uvicorn atendia.main:app --port 8001
