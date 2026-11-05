@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 排查
echo ===== 环境自检 =====
echo.
echo [1] 找 python：
where python 2>nul
if errorlevel 1 echo    （没有 python 命令）
echo.
echo [2] 找 py 启动器：
where py 2>nul
if errorlevel 1 echo    （没有 py 命令）
echo.
echo [3] 版本：
python -V 2>nul
py -3 -V 2>nul
echo.
echo [4] 尝试启动服务 5 秒：
python -u server.py
echo.
echo 退出码：%errorlevel%
echo.
echo 把上面整段截图发给管理员。
pause
