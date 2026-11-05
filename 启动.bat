@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 用户整理工作台
set PORT=8901
echo ==============================================
echo  用户整理工作台  启动中
echo ==============================================
echo.
set PY=
where python >nul 2>nul && set PY=python
if not defined PY (where py >nul 2>nul && set PY=py)
if not defined PY (
  echo [X] 这台电脑没装 Python。
  echo.
  echo 1. 打开 https://www.python.org/downloads/
  echo 2. 下载 Windows 版并安装
  echo 3. 安装第一步务必勾选 "Add python.exe to PATH"
  echo 4. 装完重新双击 启动.bat
  echo.
  pause
  exit /b 1
)
echo [OK] 使用 %PY%
%PY% -V
echo.
%PY% -c "import urllib.request as u; u.urlopen(chr(104)+chr(116)+chr(116)+chr(112)+chr(58)+chr(47)+chr(47)+chr(49)+chr(50)+chr(55)+chr(46)+chr(48)+chr(46)+chr(48)+chr(46)+chr(49)+chr(58)+chr(56)+chr(57)+chr(48)+chr(49)+chr(47)+chr(97)+chr(112)+chr(105)+chr(47)+chr(115)+chr(116)+chr(97)+chr(116)+chr(117)+chr(115),timeout=2)" >nul 2>nul
if %errorlevel%==0 (
  echo [OK] 服务已在运行
) else (
  echo --^> 正在启动服务 ...
  start "workbench-server" /min %PY% 壳服务.py
  ping -n 5 127.0.0.1 >nul
)
start "" http://127.0.0.1:%PORT%
echo.
echo ==============================================
echo  浏览器已打开： http://127.0.0.1:%PORT%
echo ==============================================
echo.
echo 第一次：在页面里贴 CRM 凭证（jsu_ 开头）再点开始。
echo 以后：双击本文件即可。
echo 这个窗口可以关掉，服务在后台继续运行。
ping -n 8 127.0.0.1 >nul
