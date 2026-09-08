@echo off
chcp 65001 >nul
title Yangtze Cultural Knowledge Infrastructure - Auto Growth
cd /d "%~dp0"

echo ============================================================
echo   YCKI - Changjiang Culture Knowledge Base
echo   WebUI: http://localhost:9621/webui/
echo ============================================================
echo.

echo [1/4] Checking Docker Desktop ...
docker info >nul 2>&1
if errorlevel 1 (
    echo   Docker not ready - starting Docker Desktop, please wait ...
    start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"
:waitdocker
    timeout /t 10 /nobreak >nul
    docker info >nul 2>&1
    if errorlevel 1 goto waitdocker
)
echo   Docker OK.

echo [2/4] Starting containers (lightrag / postgres / searxng) ...
docker start lightrag-lightrag-1 ycki-postgres searxng >nul 2>&1

echo [3/4] Waiting for LightRAG health ...
:waithc
curl -s -m 8 http://localhost:9621/health >nul 2>&1
if errorlevel 1 (
    timeout /t 6 /nobreak >nul
    goto waithc
)
echo   LightRAG OK.

echo [3.5/4] Starting visual console at http://localhost:9622 ...
start "YCKI Console" /min python dashboard\app.py
timeout /t 4 /nobreak >nul

echo [4/4] Starting auto-growth engine (collect -^> extract -^> heal loop) ...
echo   It runs FOREVER until you close this window.
echo   Log: data\auto_growth.log
echo.
start "" http://localhost:9622
start "" http://localhost:9621/webui/
python auto_growth.py
pause
