@echo off
chcp 65001 >nul
title NewsQuant - 뉴스 수집 시스템

echo ========================================
echo NewsQuant 뉴스 수집 시스템 시작
echo ========================================
echo.

REM Python 설치 확인
python --version >nul 2>&1
if errorlevel 1 (
    echo [오류] Python이 설치되어 있지 않습니다.
    echo Python을 설치한 후 다시 시도해주세요.
    pause
    exit /b 1
)

REM 현재 디렉토리로 이동
cd /d "%~dp0"

REM 가상환경 확인 (선택사항)
if exist "venv\Scripts\activate.bat" (
    echo 가상환경 활성화 중...
    call venv\Scripts\activate.bat
)

REM 메인 프로그램 실행
echo 프로그램을 시작합니다...
echo.
python main.py

REM 프로그램 종료 시
echo.
echo 프로그램이 종료되었습니다.
pause

