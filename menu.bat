@echo off
chcp 65001 >nul
title NewsQuant - 메인 메뉴

:menu
cls
echo.
echo ========================================
echo     NewsQuant 뉴스 수집 시스템
echo ========================================
echo.
echo 실행할 옵션을 선택하세요:
echo.
echo   1. 전체 실행 (API 서버 + 스케줄러)
echo   2. API 서버만 실행
echo   3. 스케줄러만 실행
echo   4. 패키지 설치/업데이트
echo   5. 종료
echo.
echo ========================================
set /p choice="선택 (1-5): "

if "%choice%"=="1" goto start_full
if "%choice%"=="2" goto start_api
if "%choice%"=="3" goto start_scheduler
if "%choice%"=="4" goto install
if "%choice%"=="5" goto exit

echo.
echo 잘못된 선택입니다. 다시 선택해주세요.
timeout /t 2 >nul
goto menu

:start_full
cls
call start.bat
goto menu

:start_api
cls
call start_api_only.bat
goto menu

:start_scheduler
cls
call start_scheduler_only.bat
goto menu

:install
cls
call install.bat
echo.
echo 아무 키나 누르면 메뉴로 돌아갑니다...
pause >nul
goto menu

:exit
echo.
echo 프로그램을 종료합니다.
exit /b 0

