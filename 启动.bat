@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 用户整理工作台
set PORT=8901
echo ==============================================
echo  用户整理工作台 启动中
echo ==============================================
echo.

set PY=
where python >nul 2>nul && set PY=python
if not defined PY (where py >nul 2>nul && set PY=py)
if not defined PY (
  echo [X] 这台电脑没有 Python。
  echo.
  echo 请先装 Python：打开 https://www.python.org/downloads/ 
  echo 下载 Windows 版，安装时务必勾选 "Add python.exe to PATH"
  echo 装完重新双击本文件。
  echo.
  pause
  exit /b 1
)
echo [√] 使用 %PY%
for /f "tokens=*" %%v in (%PY% -V 2^>^&1) do echo [√] %%v
echo.

curl -s -o nul -m 2 http://127.0.0.1:%PORT%/api/status >nul 2>nul
if %errorlevel%==0 (
  echo [√] 服务已在运行
) else (
  echo -^> 正在启动服务...
  start "workbench-server" /min %PY% 壳服务.py
  timeout /t 4 /nobreak >nul
)

start "" http://127.0.0.1:%PORT%
echo.
echo ==============================================
echo  浏览器已打开： http://127.0.0.1:%PORT%
echo ==============================================
echo.
echo 第一次会看到初始化页面：贴 CRM 凭证（jsu_ 开头），点开始生成。
echo 以后再打开：双击本文件即可，不用再填凭证。
echo.
echo 这个窗口可以关掉，服务在后台继续运行。
timeout /t 6 /nobreak >nul
