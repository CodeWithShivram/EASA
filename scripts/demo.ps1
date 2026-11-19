<#
.SYNOPSIS
    Starts the whole EASA stack in Docker with synthetic demo data (P8-M5, ADR-039).

.DESCRIPTION
    Builds and starts PostgreSQL, the API and the web app (and the local chat model
    when its file has been downloaded), then, once, creates three demo users with
    generated passwords, uploads the synthetic policy documents at three
    visibility levels and seeds synthetic tickets. The passwords are written only
    to var\demo\credentials.txt (git-ignored); they are never printed.

    The stack uses its own database (easa_app) on the Compose PostgreSQL server
    and its own upload volume, never the development database.

    Without the chat model file the API runs in development mode with the fake
    model, which quotes the first source instead of writing an answer. Without the
    embedding model, search uses the hashing embedder (not semantic).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\demo.ps1          # start (or restart)

.EXAMPLE
    scripts\demo.ps1 -Down      # stop the containers, keep the data
    scripts\demo.ps1 -Reset     # delete the demo data: the easa_app database, uploads, credentials
#>
[CmdletBinding()]
param(
    [switch]$Down,
    [switch]$Reset,
    # Use the fake model even if the chat model file exists.
    [switch]$NoModel
)

# Native commands report through exit codes, checked below; Windows PowerShell 5.1
# would turn their log output on stderr into errors under 'Stop'.
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$profiles = @('--profile', 'app', '--profile', 'llm')

docker info *> $null
if ($LASTEXITCODE -ne 0) { throw 'Docker is not running. Start Docker Desktop first.' }

if ($Down) {
    docker compose @profiles stop
    Write-Host 'Stopped; data kept.'
    exit 0
}
if ($Reset) {
    # Only the demo's own data: the development database and models are untouched.
    docker compose @profiles rm --stop --force api web app-db
    docker compose up -d --wait postgres
    docker compose exec -T postgres dropdb -U easa --if-exists --force easa_app
    if ($LASTEXITCODE -ne 0) { throw 'Could not drop the easa_app database.' }
    docker volume rm --force easa_uploads | Out-Null
    if (Test-Path 'var\demo') { Remove-Item -Recurse -Force 'var\demo' }
    Write-Host 'Demo data deleted (easa_app database, uploads, credentials).'
    exit 0
}

function New-Secret {
    $bytes = New-Object byte[] 24
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    return [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

# The database password lives in the git-ignored .env (compose.yaml reads it).
if (-not (Test-Path '.env')) {
    $template = Get-Content '.env.example' | ForEach-Object {
        if ($_ -match '^EASA_POSTGRES_PASSWORD=') { "EASA_POSTGRES_PASSWORD=$(New-Secret)" } else { $_ }
    }
    Set-Content -Path '.env' -Value $template -Encoding ascii
    Write-Host 'Created .env with a generated database password.'
}

$chatModel = 'apps\api\var\models\llm\qwen2.5-1.5b-instruct-q4_k_m.gguf'
$useModel = (Test-Path $chatModel) -and -not $NoModel
if ($useModel) {
    $env:EASA_APP_ENVIRONMENT = 'production'
    $env:EASA_APP_MODEL_PROVIDER = 'llamacpp'
    $up = $profiles
} else {
    Write-Warning 'No chat model (or -NoModel): the API runs in development mode with the fake model, which quotes the first source instead of answering. Download the model with "uv run python -m app.cli download-chat-model" (apps\api) for real answers.'
    $env:EASA_APP_ENVIRONMENT = 'development'
    $env:EASA_APP_MODEL_PROVIDER = 'fake'
    $up = @('--profile', 'app')
}
if (Test-Path 'apps\api\var\models\bge-small-en-v1.5') {
    $env:EASA_APP_EMBEDDING_PROVIDER = 'onnx'
} else {
    Write-Warning 'No embedding model: search uses the hashing embedder (not semantic). Download it with "uv run python -m app.cli download-embedding-model" (apps\api).'
    $env:EASA_APP_EMBEDDING_PROVIDER = 'hashing'
}

docker compose @up up -d --build --wait
if ($LASTEXITCODE -ne 0) { throw 'The stack did not start; see "docker compose --profile app logs".' }

# Text piped to docker must not start with a byte order mark (it would become
# part of the password).
$OutputEncoding = New-Object System.Text.UTF8Encoding $false

function Invoke-Api([string[]]$Arguments, [string]$Stdin = $null) {
    if ($null -ne $Stdin) {
        $Stdin | docker compose exec -T api python -m app.cli @Arguments *> $null
    } else {
        docker compose exec -T api python -m app.cli @Arguments *> $null
    }
    return $LASTEXITCODE
}

$credentials = 'var\demo\credentials.txt'
if (Test-Path $credentials) {
    Write-Host 'Demo data already loaded.'
} else {
    New-Item -ItemType Directory -Force 'var\demo' | Out-Null
    $tenant = 'Larkspur Analytics'
    $lines = @('EASA demo users (synthetic; generated passwords; delete with scripts\demo.ps1 -Reset)', '')
    foreach ($role in 'employee', 'manager', 'administrator') {
        $name = "demo-$role"
        $password = New-Secret
        $code = Invoke-Api @('create-user', '--tenant', $tenant, '--username', $name, '--role', $role, '--password-stdin') $password
        if ($code -ne 0) {
            throw "Could not create $name (it may exist from an earlier run whose credentials file is gone). Run scripts\demo.ps1 -Reset to start over."
        }
        $lines += "$role`t$name`t$password"
    }
    Set-Content -Path $credentials -Value $lines -Encoding ascii
    $uploads = @(
        @('demo-manager', 'employee', 'eval/corpus/*.txt'),
        @('demo-manager', 'manager', 'eval/access/manager_compensation.txt eval/access/team_restructuring.txt'),
        @('demo-administrator', 'administrator', 'eval/access/board_minutes.txt eval/access/security_incident.txt')
    )
    foreach ($u in $uploads) {
        docker compose exec -T api sh -c "python -m app.cli upload-documents --username $($u[0]) --min-role $($u[1]) $($u[2])" *> $null
        if ($LASTEXITCODE -ne 0) { throw "Uploading the $($u[1]) documents failed; see docker compose logs api." }
    }
    if ((Invoke-Api @('seed-tickets', '--username', 'demo-employee')) -ne 0) { throw 'Seeding tickets failed.' }
    Write-Host 'Demo data loaded: 3 users, 16 synthetic documents, 7 synthetic tickets.'
}

Write-Host ''
Write-Host 'EASA is running at http://localhost:3000' -ForegroundColor Green
Write-Host "Sign-in names and passwords: $credentials (git-ignored)."
Write-Host 'Stop with scripts\demo.ps1 -Down; delete the data with scripts\demo.ps1 -Reset.'
