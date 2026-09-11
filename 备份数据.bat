@echo off
chcp 65001 >nul
title YCKI - 数据安全备份
cd /d "%~dp0"

set RAG_STORAGE=D:\长江学论纲\ycki\deploy\lightrag\data\rag_storage
set BACKUP_DIR=D:\长江学论纲\ycki\data\backups
set PG_CONTAINER=ycki-postgres

:: 创建备份目录
if not exist "%BACKUP_DIR%" mkdir "%BACKUP_DIR%"
if not exist "%BACKUP_DIR%\lightrag" mkdir "%BACKUP_DIR%\lightrag"
if not exist "%BACKUP_DIR%\postgres" mkdir "%BACKUP_DIR%\postgres"

echo [1/3] 备份 LightRAG 数据...
robocopy "%RAG_STORAGE%" "%BACKUP_DIR%\lightrag\latest" /E /XO /R:1 /W:1 /LOG:"%BACKUP_DIR%\lightrag\backup.log" /NFL /NDL
if %ERRORLEVEL% GEQ 8 (
    echo   LightRAG 备份失败！错误码 %ERRORLEVEL%
) else (
    echo   LightRAG 备份完成
)

echo [2/3] 备份 PostgreSQL 数据库...
docker exec %PG_CONTAINER% pg_dump -U postgres -d ycki --no-password --format=custom --file=/tmp/ycki_backup.dump 2>nul
if %ERRORLEVEL% EQU 0 (
    docker cp %PG_CONTAINER%:/tmp/ycki_backup.dump "%BACKUP_DIR%\postgres\ycki_backup_latest.dump" >nul 2>&1
    echo   PostgreSQL 备份完成
) else (
    echo   PostgreSQL 备份失败（容器未运行？）
)

echo [3/3] 清理旧备份（保留最近 7 天）...
forfiles /p "%BACKUP_DIR%\lightrag" /s /m *.* /d -7 /c "cmd /c del @path" 2>nul
forfiles /p "%BACKUP_DIR%\postgres" /s /m *.dump /d -7 /c "cmd /c del @path" 2>nul

echo.
echo 备份完成时间: %date% %time%
echo 备份位置: %BACKUP_DIR%
