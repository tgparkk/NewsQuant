@echo off
chcp 65001 >nul
title NewsQuant - API 서버만 실행

echo ========================================
echo NewsQuant API 서버 시작 (스케줄러 제외)
echo ========================================
echo.

REM Python 설치 확인
python --version >nul 2>&1
if errorlevel 1 (
    echo [오류] Python이 설치되어 있지 않습니다.
    pause
    exit /b 1
)

REM 현재 디렉토리로 이동
cd /d "%~dp0"

REM 가상환경 확인 (선택사항)
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

echo API 서버만 실행합니다 (뉴스 수집 스케줄러는 실행되지 않습니다).
echo.
echo API 서버 주소: http://127.0.0.1:8000
echo API 문서: http://127.0.0.1:8000/docs
echo.
echo 종료하려면 Ctrl+C를 누르세요.
echo.

REM API 서버만 실행하는 Python 스크립트 실행
python run_api.py

pause

