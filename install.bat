@echo off
chcp 65001 >nul
title NewsQuant - 패키지 설치

echo ========================================
echo NewsQuant 패키지 설치
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

echo Python 버전 확인:
python --version
echo.

REM pip 업그레이드
echo pip 업그레이드 중...
python -m pip install --upgrade pip
echo.

REM requirements.txt 확인
if not exist "requirements.txt" (
    echo [오류] requirements.txt 파일을 찾을 수 없습니다.
    pause
    exit /b 1
)

REM 패키지 설치
echo 필요한 패키지를 설치합니다...
echo.
python -m pip install -r requirements.txt

if errorlevel 1 (
    echo.
    echo [오류] 패키지 설치 중 오류가 발생했습니다.
    pause
    exit /b 1
)

echo.
echo ========================================
echo 설치가 완료되었습니다!
echo ========================================
echo.
echo 이제 start.bat 파일을 실행하여 프로그램을 시작할 수 있습니다.
echo.
pause

