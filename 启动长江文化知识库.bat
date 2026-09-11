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

echo [1.5/4] Checking data integrity...
python -c "
import os, shutil, sys
sys.path.insert(0, r'D:\长江学论纲\ycki')
from pathlib import Path

RAG = Path(r'D:\长江学论纲\ycki\deploy\lightrag\dataag_storage')
GRAPH = RAG / 'graph_chunk_entity_relation.graphml'
BAK = RAG / 'graph_chunk_entity_relation.graphml.bak'

# 检查 GraphML 是否损坏（头部非 XML）
def is_corrupted(path):
    try:
        with open(path, 'rb') as f:
            head = f.read(200)
            return not head.startswith(b'<?xml')
    except:
        return True

if is_corrupted(GRAPH):
    print('  GraphML corrupted, restoring from backup...')
    if BAK.exists():
        shutil.copy2(BAK, GRAPH)
        print('  Restored from .bak')
    else:
        # 从 backups 恢复
        backup_dir = Path(r'D:\长江学论纲\ycki\dataackups\lightrag\latest')
        if (backup_dir / 'graph_chunk_entity_relation.graphml').exists():
            shutil.copy2(backup_dir / 'graph_chunk_entity_relation.graphml', GRAPH)
            print('  Restored from backups')
        else:
            print('  No backup found, creating minimal graph')
            minimal = '<?xml version='1.0' encoding='UTF-8'?>
<graphml xmlns='http://graphml.graphdrawing.org/xmlns'><graph id='G' edgedefault='directed'></graph></graphml>'
            GRAPH.write_text(minimal)
            print('  Created minimal graph')
else:
    print('  GraphML OK')
"
if errorlevel 1 (
    echo   数据完整性检查失败，但继续启动...
)

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
