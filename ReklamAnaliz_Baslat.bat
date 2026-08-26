@echo off
setlocal
title ReklamAnaliz Baslatiliyor

set "ROOT_DIR=%~dp0"
set "SITE_URL=http://127.0.0.1:8000/"

if not exist "%ROOT_DIR%start_dev_server.cmd" goto :missing
if not exist "%ROOT_DIR%start_celery_worker.cmd" goto :missing
if not exist "%ROOT_DIR%start_celery_beat.cmd" goto :missing

echo [1/3] Web sunucusu baslatiliyor...
start "ReklamAnaliz - Web" /min cmd /c call "%ROOT_DIR%start_dev_server.cmd"
timeout /t 2 /nobreak >nul

echo [2/3] Celery worker baslatiliyor...
start "ReklamAnaliz - Celery Worker" /min cmd /c call "%ROOT_DIR%start_celery_worker.cmd"
timeout /t 1 /nobreak >nul

echo [3/3] Celery beat baslatiliyor...
start "ReklamAnaliz - Celery Beat" /min cmd /c call "%ROOT_DIR%start_celery_beat.cmd"

powershell -NoProfile -Command "$limit=(Get-Date).AddSeconds(60); do { try { $r=Invoke-WebRequest -UseBasicParsing -Uri '%SITE_URL%' -TimeoutSec 2; if($r.StatusCode -ge 200 -and $r.StatusCode -lt 500){exit 0} } catch {}; Start-Sleep -Milliseconds 500 } while((Get-Date)-lt $limit); exit 1"
if errorlevel 1 goto :failed

echo ReklamAnaliz hazir. Tarayici aciliyor...
start "" "%SITE_URL%"
exit /b 0

:missing
echo HATA: Uc baslatma dosyasindan biri bulunamadi.
pause
exit /b 1

:failed
echo HATA: Web sunucusu 60 saniye icinde hazir olmadi.
pause
exit /b 1
