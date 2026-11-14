<#
.SYNOPSIS
    Starts the EASA API (port 8000, auto-reload) and web app (port 3000) together.

.DESCRIPTION
    Both servers run in this console and bind only to the local machine.
    Press Ctrl+C to stop; the script then stops both process trees.
    Run `uv run alembic upgrade head` in apps/api first if migrations changed.

    -SmokeTest starts both servers, checks that they respond, stops them and
    exits with code 0 (success) or 1 (failure). It exercises the same
    shutdown path as Ctrl+C.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\dev.ps1

.EXAMPLE
    scripts\dev.ps1 -SmokeTest
#>
[CmdletBinding()]
param(
    [switch]$SmokeTest,
    # Seconds to wait for both servers to respond.
    [int]$StartupTimeoutSeconds = 120
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$env:NEXT_TELEMETRY_DISABLED = '1'

$apiUrl = 'http://127.0.0.1:8000/api/v1/health'
$readyUrl = 'http://127.0.0.1:8000/api/v1/health/ready'
$webUrl = 'http://localhost:3000/'

function Test-PortInUse([int]$Port) {
    # Check IPv4 and IPv6 loopback: Node may bind "localhost" to ::1 only.
    foreach ($target in @(@('127.0.0.1', 'InterNetwork'), @('::1', 'InterNetworkV6'))) {
        $client = New-Object System.Net.Sockets.TcpClient ([System.Net.Sockets.AddressFamily]$target[1])
        try {
            $attempt = $client.BeginConnect($target[0], $Port, $null, $null)
            if ($attempt.AsyncWaitHandle.WaitOne(500) -and $client.Connected) { return $true }
        } catch {
            # Connection refused or address family unavailable: not in use on this address.
        } finally {
            $client.Close()
        }
    }
    return $false
}

function Test-Url([string]$Url) {
    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 10
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Stop-Tree($Process) {
    if ($Process -and -not $Process.HasExited) {
        & taskkill.exe /PID $Process.Id /T /F *> $null
    }
}

foreach ($port in 8000, 3000) {
    if (Test-PortInUse $port) {
        Write-Host "Port $port is already in use. Stop the process using it and try again." -ForegroundColor Red
        exit 1
    }
}

$api = $null
$web = $null
$exitCode = 0
try {
    Write-Host 'Starting API on http://127.0.0.1:8000 ...' -ForegroundColor Cyan
    $api = Start-Process -FilePath 'uv' -WorkingDirectory (Join-Path $root 'apps\api') -NoNewWindow -PassThru -ArgumentList @(
        'run', 'uvicorn', 'app.main:create_app', '--factory', '--reload',
        '--host', '127.0.0.1', '--port', '8000', '--no-access-log')

    Write-Host 'Starting web app on http://localhost:3000 ...' -ForegroundColor Cyan
    $web = Start-Process -FilePath 'npm.cmd' -WorkingDirectory (Join-Path $root 'apps\web') -NoNewWindow -PassThru -ArgumentList @('run', 'dev')

    $deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
    $apiUp = $false
    $webUp = $false
    while ((Get-Date) -lt $deadline -and -not ($apiUp -and $webUp)) {
        if ($api.HasExited -or $web.HasExited) { break }
        Start-Sleep -Milliseconds 500
        if (-not $apiUp) { $apiUp = Test-Url $apiUrl }
        if (-not $webUp) { $webUp = Test-Url $webUrl }
    }

    if (-not ($apiUp -and $webUp)) {
        Write-Host "Startup failed (API up: $apiUp, web up: $webUp)." -ForegroundColor Red
        $exitCode = 1
    } elseif ($SmokeTest) {
        $ready = Test-Url $readyUrl
        Write-Host "Smoke test: API live: $apiUp, API ready: $ready, web: $webUp" -ForegroundColor Cyan
        if (-not $ready) { $exitCode = 1 }
    } else {
        Write-Host ''
        Write-Host 'EASA is running:' -ForegroundColor Green
        Write-Host "  Web:  $webUrl"
        Write-Host "  API:  http://127.0.0.1:8000/docs"
        Write-Host 'Press Ctrl+C to stop both servers.'
        while (-not $api.HasExited -and -not $web.HasExited) {
            Start-Sleep -Seconds 1
        }
        Write-Host 'A server exited; stopping the other one.' -ForegroundColor Yellow
        $exitCode = 1
    }
} finally {
    Write-Host 'Stopping servers ...' -ForegroundColor Cyan
    Stop-Tree $web
    Stop-Tree $api
}
exit $exitCode
