@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0.."
if not exist logs mkdir logs
REM log date via PowerShell (locale independent)
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd"') do set LOGDATE=%%i
"C:\Program Files (x86)\Microsoft Visual Studio\Shared\Python39_64\python.exe" scripts\snapshot_naver_themes.py --config D:/GIT/NewsQuant/config.yaml >> "logs\theme_snapshot_%LOGDATE%.log" 2>&1
exit /b %errorlevel%
