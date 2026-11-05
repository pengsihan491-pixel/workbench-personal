@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 用户整理工作台
set PORT=8901
set LOG=%~dp0server.log

rem ============================================================
rem  优先用包里自带的免安装 Python（不需要在电脑上装任何东西）
rem ============================================================
set PYEXE=
if exist "%~dp0runtime\python\python.exe" set PYEXE=%~dp0runtime\python\python.exe

if not defined PYEXE goto TRYSYS
echo [OK] 使用内置 Python（免安装）
set SSL_CERT_FILE=%~dp0runtime\python\cacert.pem
goto CHECKPORT

:TRYSYS
rem 没带运行时就退回系统 Python（跳过微软商店假壳）
py -3 -V >nul 2>&1 && set PYEXE=py -3
if not defined PYEXE (
  python -V >nul 2>&1 && set PYEXE=python
)
if not defined PYEXE goto NOPY
echo %PYEXE% | findstr /i "WindowsApps" >nul && goto NOPY
echo [OK] 使用系统 Python

:CHECKPORT
echo.
%PYEXE% -c "import socket,sys; s=socket.socket(); s.settimeout(1); sys.exit(0 if s.connect_ex((chr(49)+chr(50)+chr(55)+chr(46)+chr(48)+chr(46)+chr(48)+chr(46)+chr(49),8901))==0 else 1)" >nul 2>&1
if %errorlevel%==0 (
  echo [OK] 服务已在运行
  goto OPEN
)

echo --^> 正在启动服务，第一次约 3-8 分钟 ...
del "%LOG%" >nul 2>&1
start "workbench-server" /min cmd /c ""%PYEXE%" -u server.py > "%LOG%" 2>&1"
ping -n 6 127.0.0.1 >nul

%PYEXE% -c "import socket,sys; s=socket.socket(); s.settimeout(1); sys.exit(0 if s.connect_ex((chr(49)+chr(50)+chr(55)+chr(46)+chr(48)+chr(46)+chr(48)+chr(46)+chr(49),8901))==0 else 1)" >nul 2>&1
if not %errorlevel%==0 (
  echo.
  echo [X] 服务没起来，错误信息：
  echo ----------------------------------------------
  if exist "%LOG%" (type "%LOG%") else (echo 没有日志，Python 可能没跑起来)
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
echo 第一次：贴 CRM 凭证（jsu_ 开头），点「开始生成我的工作台」
echo 以后：双击本文件即可，不用再填凭证
echo 这个窗口可以关，服务在后台继续运行
ping -n 8 127.0.0.1 >nul
exit /b 0

:NOPY
echo [X] 没有可用的 Python。
echo.
echo 正常情况包里自带 Python，不该出现这个提示。
echo 说明解压时 runtime 文件夹丢失了 —— 请把整个压缩包重新完整解压一次。
echo.
pause
exit /b 1
