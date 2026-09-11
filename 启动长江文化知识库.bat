@echo off
chcp 65001 >nul
title YCKI - 长江文化知识库
cd /d "%~dp0"
echo Starting YCKI...
python start_all.py
pause
