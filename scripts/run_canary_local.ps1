# scripts/run_canary_local.ps1
# Run the canary-diff harness against a local FastAPI backend.
#
# Why this exists:
#   The harness defaults to https://api.yieldiq.in. The authed
#   /api/v1/analysis/{ticker} endpoint requires a Bearer JWT, so without
#   CANARY_AUTH_TOKEN every authed fetch returns HTTP 401 and gates 2/3/5
#   evaluate against null payloads — silently "passing" on empty data.
#
#   This script boots uvicorn locally with YIELDIQ_DEV_MODE=true so the
#   dev-bypass in backend/middleware/auth.py satisfies get_current_user
#   without a real token. See backend/middleware/auth.py:_dev_mode_user_or_none.
#
# Usage:
#   pwsh scripts/run_canary_local.ps1 -Mode snapshot
#   pwsh scripts/run_canary_local.ps1 -Mode diff -Snapshot scripts/snapshots/snapshot_*.json
#   pwsh scripts/run_canary_local.ps1 -Mode gates
#
# Constraint:
#   Refuses to run if RAILWAY_ENVIRONMENT=production.
[CmdletBinding()]
param(
    [ValidateSet('snapshot','diff','gates')]
    [string]$Mode = 'snapshot',
    [string]$Snapshot,
    [string]$Python = 'C:/ProgramData/miniconda3/python.exe',
    [int]$Port = 8765,
    [int]$BootTimeoutSecs = 60
)

$ErrorActionPreference = 'Stop'

if ($env:RAILWAY_ENVIRONMENT -in @('production','prod')) {
    throw "RAILWAY_ENVIRONMENT=$($env:RAILWAY_ENVIRONMENT). Refusing to enable dev-bypass against prod."
}

$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot
try {
    $env:YIELDIQ_DEV_MODE = 'true'
    $env:CANARY_API_BASE = "http://127.0.0.1:$Port"

    Write-Host "Booting uvicorn on port $Port (YIELDIQ_DEV_MODE=true)..." -ForegroundColor Cyan
    $logFile = Join-Path $env:TEMP "yieldiq_canary_uvicorn.log"
    if (Test-Path $logFile) { Remove-Item $logFile -Force }

    $proc = Start-Process -FilePath $Python `
        -ArgumentList @('-m','uvicorn','backend.main:app','--host','127.0.0.1','--port',"$Port",'--log-level','warning') `
        -WorkingDirectory $repoRoot `
        -RedirectStandardOutput $logFile `
        -RedirectStandardError "$logFile.err" `
        -PassThru -NoNewWindow

    try {
        # Poll /health.
        $deadline = (Get-Date).AddSeconds($BootTimeoutSecs)
        $ready = $false
        while ((Get-Date) -lt $deadline) {
            try {
                $r = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 3 -UseBasicParsing
                if ($r.StatusCode -eq 200) { $ready = $true; break }
            } catch { Start-Sleep -Milliseconds 700 }
        }
        if (-not $ready) {
            Write-Host "--- uvicorn log (boot failed) ---" -ForegroundColor Red
            if (Test-Path $logFile) { Get-Content $logFile -Tail 50 }
            if (Test-Path "$logFile.err") { Get-Content "$logFile.err" -Tail 50 }
            throw "uvicorn did not become healthy within $BootTimeoutSecs s"
        }
        Write-Host "Local backend healthy at http://127.0.0.1:$Port" -ForegroundColor Green

        # Smoke-test the dev-bypass actually works on the authed path.
        $au = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/v1/analysis/RELIANCE.NS?include_summary=false" `
            -TimeoutSec 90 -UseBasicParsing
        if ($au.StatusCode -ne 200) {
            throw "dev-bypass smoke-test failed: HTTP $($au.StatusCode) on /analysis/RELIANCE.NS"
        }
        Write-Host "Dev-bypass OK (RELIANCE.NS authed fetch returned 200)" -ForegroundColor Green

        # Build canary args.
        $canaryArgs = @('scripts/canary_diff.py','--api-base',"http://127.0.0.1:$Port")
        switch ($Mode) {
            'snapshot' { $canaryArgs += '--snapshot' }
            'diff'     {
                if (-not $Snapshot) { throw "-Snapshot is required when -Mode diff" }
                $canaryArgs += @('--diff-against',$Snapshot)
            }
            'gates'    { } # full gate run
        }

        Write-Host "Running: $Python $($canaryArgs -join ' ')" -ForegroundColor Cyan
        & $Python @canaryArgs
        $exit = $LASTEXITCODE
        Write-Host "canary_diff.py exit=$exit" -ForegroundColor Cyan
        exit $exit
    }
    finally {
        if ($proc -and -not $proc.HasExited) {
            Write-Host "Stopping uvicorn (PID $($proc.Id))..." -ForegroundColor Cyan
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        }
    }
}
finally {
    Pop-Location
}
