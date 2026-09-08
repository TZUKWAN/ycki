@echo off
chcp 65001 >nul
echo Stopping YCKI containers (data is safe on disk) ...
docker stop lightrag-lightrag-1 ycki-postgres >nul 2>&1
echo Done. Data is persisted in ycki\deploy\lightrag\data and ycki-postgres volume.
pause
