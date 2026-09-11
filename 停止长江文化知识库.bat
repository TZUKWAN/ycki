@echo off
chcp 65001 >nul
title YCKI - 安全停止（优雅停机）
cd /d "%~dp0"

echo.
echo ============================================================
echo   YCKI - 安全停止
echo   此脚本会优雅停止所有服务，确保数据完整写入硬盘
echo ============================================================
echo.
echo 正在停止自增长引擎...
taskkill /F /IM python.exe >nul 2>&1
echo   python 进程已停止

echo.
echo 正在优雅停止 LightRAG 容器（等待写入完成）...
docker stop --time 30 lightrag-lightrag-1 >nul 2>&1
echo   LightRAG 已停止

echo.
echo 正在停止 PostgreSQL 容器...
docker stop --time 10 ycki-postgres >nul 2>&1
echo   PostgreSQL 已停止

echo.
echo 正在停止 SearXNG...
docker stop searxng >nul 2>&1
echo   SearXNG 已停止

echo.
echo ============================================================
echo   所有服务已安全停止
echo   数据已完整保存到硬盘
echo   下次启动请运行: 启动长江文化知识库.bat
echo ============================================================
echo.
pause
