$ErrorActionPreference = "Stop"

$RootDir = $PSScriptRoot
$ProjectDir = Join-Path $RootDir "instagram_reklam_analiz"
$PythonExe = Join-Path $RootDir ".venvs\instagram_reklam_analiz\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $PythonExe)) {
    throw "Python venv bulunamadi: $PythonExe"
}

if (-not (Test-Path -LiteralPath (Join-Path $ProjectDir "manage.py"))) {
    throw "Django proje dizini bulunamadi: $ProjectDir"
}

$env:DJANGO_SETTINGS_MODULE = "config.settings"
if (-not $env:REDIS_HOST) { $env:REDIS_HOST = "127.0.0.1" }
if (-not $env:REDIS_PORT) { $env:REDIS_PORT = "6379" }
if (-not $env:CACHE_REDIS_URL) { $env:CACHE_REDIS_URL = "redis://$($env:REDIS_HOST):$($env:REDIS_PORT)/3" }
if (-not $env:CELERY_BROKER_URL) { $env:CELERY_BROKER_URL = "redis://$($env:REDIS_HOST):$($env:REDIS_PORT)/0" }
if (-not $env:CELERY_RESULT_BACKEND) { $env:CELERY_RESULT_BACKEND = "redis://$($env:REDIS_HOST):$($env:REDIS_PORT)/1" }
if (-not $env:CHANNEL_REDIS_URL) { $env:CHANNEL_REDIS_URL = "redis://$($env:REDIS_HOST):$($env:REDIS_PORT)/2" }

$PreviousLocation = Get-Location
try {
    Set-Location -LiteralPath $ProjectDir

    $CeleryArgs = @(
        "-m", "celery",
        "-A", "config",
        "beat",
        "--loglevel=info"
    )

    if ($args.Count -gt 0) {
        $CeleryArgs += $args
    }

    & $PythonExe @CeleryArgs
    exit $LASTEXITCODE
}
finally {
    Set-Location -LiteralPath $PreviousLocation
}
