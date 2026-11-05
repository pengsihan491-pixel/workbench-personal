@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 用户整理工作台
set PORT=8901
set LOG=%~dp0server.log
echo ==============================================
echo  用户整理工作台  启动中
echo ==============================================
echo.

rem ---------- 1. 找一个真正的 Python ----------
set PY=
py -3 -V >nul 2>&1 && set PY=py -3
if not defined PY (
  python -V >nul 2>&1 && set PY=python
)
if not defined PY goto NOPY

rem 排除微软商店的假 python（WindowsApps 里的空壳）
echo %PY% | findstr /i "WindowsApps" >nul && goto NOPY
where %PY% 2>nul | findstr /i "WindowsApps" >nul && goto NOPY

echo [OK] 找到 Python：
%PY% -V
echo.

rem ---------- 2. 端口已被占用？ ----------
%PY% -c "import socket,sys; s=socket.socket(); s.settimeout(1); sys.exit(0 if s.connect_ex((chr(49)+chr(50)+chr(55)+chr(46)+chr(48)+chr(46)+chr(48)+chr(46)+chr(49),8901))==0 else 1)" >nul 2>&1
if %errorlevel%==0 (
  echo [OK] 服务已在运行，直接打开
  goto OPEN
)

rem ---------- 3. 启动服务 ----------
echo --^> 正在启动服务，请稍等 ...
del "%LOG%" >nul 2>&1
start "workbench-server" /min cmd /c "%PY% -u server.py > "%LOG%" 2>&1"
ping -n 6 127.0.0.1 >nul

%PY% -c "import socket,sys; s=socket.socket(); s.settimeout(1); sys.exit(0 if s.connect_ex((chr(49)+chr(50)+chr(55)+chr(46)+chr(48)+chr(46)+chr(48)+chr(46)+chr(49),8901))==0 else 1)" >nul 2>&1
if not %errorlevel%==0 (
  echo.
  echo [X] 服务启动失败，下面是错误信息：
  echo ----------------------------------------------
  if exist "%LOG%" (type "%LOG%") else (echo 没有生成日志，Python 可能根本没跑起来)
  echo ----------------------------------------------
  echo.
  echo 把这段截图发给管理员。
  pause
  exit /b 1
)

:OPEN
start "" http://127.0.0.1:%PORT%
echo.
echo ==============================================
echo  浏览器已打开： http://127.0.0.1:%PORT%
echo ==============================================
echo.
echo 第一次：页面里贴 CRM 凭证（jsu_ 开头），点「开始生成我的工作台」。
echo 以后：双击本文件即可，不用再填凭证。
echo 这个窗口可以关，服务在后台继续运行。
ping -n 8 127.0.0.1 >nul
exit /b 0

:NOPY
echo [X] 没有找到可用的 Python。
echo.
echo 这台电脑可能：
echo   1. 完全没装 Python，或
echo   2. 装的是微软商店的假 python（双击只会弹商店）
echo.
echo 解决办法：
echo   1. 打开 https://www.python.org/downloads/ 下载 Windows 版
echo   2. 双击安装，第一屏最下面务必勾选 "Add python.exe to PATH"
echo   3. 装完重启这个窗口，重新双击 启动.bat
echo.
pause
exit /b 1
