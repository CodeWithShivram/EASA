<#
.SYNOPSIS
    Runs the EASA quality checks for the API and the web app.

.DESCRIPTION
    Backend (apps/api): lockfile consistency, ruff format, ruff lint, pytest,
    and Alembic upgrade + drift check against a temporary SQLite database.
    Frontend (apps/web): ESLint, TypeScript, Vitest and a production build.

    Every check runs even if an earlier one fails; the script exits with code 1
    if any check failed. Dependencies must already be installed
    (`uv sync` in apps/api, `npm ci` in apps/web).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\check.ps1

.EXAMPLE
    scripts\check.ps1 -Backend
#>
[CmdletBinding()]
param(
    # Run only the backend checks.
    [switch]$Backend,
    # Run only the frontend checks.
    [switch]$Frontend,
    # Skip the (slow) Next.js production build.
    [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$apiDir = Join-Path $root 'apps\api'
$webDir = Join-Path $root 'apps\web'
$runBackend = $Backend -or -not $Frontend
$runFrontend = $Frontend -or -not $Backend
$env:NEXT_TELEMETRY_DISABLED = '1'

$results = New-Object System.Collections.Generic.List[object]

function Invoke-Check {
    param([string]$Name, [string]$Directory, [scriptblock]$Command)
    Write-Host ""
    Write-Host "==> $Name" -ForegroundColor Cyan
    $watch = [Diagnostics.Stopwatch]::StartNew()
    Push-Location $Directory
    try {
        & $Command
        $ok = ($LASTEXITCODE -eq 0)
    } catch {
        Write-Host $_ -ForegroundColor Red
        $ok = $false
    } finally {
        Pop-Location
    }
    $results.Add([pscustomobject]@{
        Check   = $Name
        Result  = $(if ($ok) { 'PASS' } else { 'FAIL' })
        Seconds = [int]$watch.Elapsed.TotalSeconds
    })
}

if ($runBackend) {
    Invoke-Check 'api: uv sync --locked' $apiDir { uv sync --locked }
    Invoke-Check 'api: ruff format --check' $apiDir { uv run ruff format --check . }
    Invoke-Check 'api: ruff check' $apiDir { uv run ruff check . }
    Invoke-Check 'api: pytest' $apiDir { uv run pytest }
    Invoke-Check 'api: alembic upgrade head + check (temporary database)' $apiDir {
        $dbFile = Join-Path ([IO.Path]::GetTempPath()) ("easa-check-{0}.db" -f [guid]::NewGuid().ToString('N'))
        $previous = $env:EASA_DATABASE_URL
        $env:EASA_DATABASE_URL = 'sqlite:///' + ($dbFile -replace '\\', '/')
        try {
            uv run alembic upgrade head
            if ($LASTEXITCODE -eq 0) { uv run alembic check }
        } finally {
            $env:EASA_DATABASE_URL = $previous
            if (Test-Path $dbFile) { Remove-Item $dbFile -Force }
        }
    }
}

if ($runFrontend) {
    if (-not (Test-Path (Join-Path $webDir 'node_modules'))) {
        Write-Host "apps/web/node_modules is missing; run 'npm ci' in apps/web first." -ForegroundColor Red
        $results.Add([pscustomobject]@{ Check = 'web: dependencies installed'; Result = 'FAIL'; Seconds = 0 })
    } else {
        Invoke-Check 'web: lint' $webDir { npm run lint }
        Invoke-Check 'web: typecheck' $webDir { npm run typecheck }
        Invoke-Check 'web: test' $webDir { npm test }
        if (-not $SkipBuild) {
            Invoke-Check 'web: build' $webDir { npm run build }
        }
    }
}

Write-Host ""
$results | Format-Table -AutoSize | Out-String | Write-Host
$failed = @($results | Where-Object { $_.Result -eq 'FAIL' }).Count
if ($failed -gt 0) {
    Write-Host "$failed check(s) failed." -ForegroundColor Red
    exit 1
}
Write-Host "All checks passed." -ForegroundColor Green
exit 0
