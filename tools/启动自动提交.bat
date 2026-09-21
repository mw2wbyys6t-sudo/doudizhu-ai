@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title 自动提交守护

for %%I in ("%~dp0..") do set "ROOT=%%~fI"
set "SCRIPT=%ROOT%\tools\autocommit.py"

rem ---------- 找 Python（只用标准库，任何 3.8+ 都行）----------
set "PY="
where python >nul 2>&1 && set "PY=python"
if not defined PY if exist "%ROOT%\runtime\python\python.exe" set "PY=%ROOT%\runtime\python\python.exe"
if not defined PY if exist "%ROOT%\..\release\欢乐斗地主AI版\runtime\python\python.exe" set "PY=%ROOT%\..\release\欢乐斗地主AI版\runtime\python\python.exe"
if not defined PY if exist "C:\Python314\python.exe" set "PY=C:\Python314\python.exe"
if not defined PY if exist "C:\Python313\python.exe" set "PY=C:\Python313\python.exe"
if not defined PY (
    echo [x] 没找到 Python。请安装 Python 3.8+ 并把 python 加入 PATH 后重试。
    pause
    exit /b 1
)

if not exist "%SCRIPT%" (
    echo [x] 找不到 %SCRIPT%
    pause
    exit /b 1
)

rem ---------- 无参数时给出提示并直接进入监听 ----------
if "%~1"=="" (
    echo ==============================================
    echo    自动提交守护 —— 一有新内容就自动提交并推送
    echo ==============================================
    echo    停止：按 Ctrl+C
    echo    其它用法：
    echo      %~nx0 --install-hooks    启用 git 钩子（手动提交也会自动推送）
    echo      %~nx0 --once             只检查一次
    echo      %~nx0 --status           看哪些内容会被自动提交
    echo      %~nx0 --dry-run --once   试跑，不真正提交
    echo ==============================================
    echo.
)

"%PY%" "%SCRIPT%" %*
set RC=%errorlevel%
if %RC% neq 0 (
    echo.
    echo [退出码 %RC%] 如果报错看不懂，把上面的内容发给 AI 助手即可。
    pause
)
exit /b %RC%
