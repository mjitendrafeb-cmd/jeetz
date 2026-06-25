@echo off
setlocal

echo ============================================================
echo  Claude PR Audit Automation
echo ============================================================
echo.

REM Move to the folder where this .bat lives so relative paths work
cd /d "%~dp0"

REM Check Python is available
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Install Python 3.13+ and add it to PATH.
    pause
    exit /b 1
)

REM Install / upgrade dependencies silently
echo Installing dependencies...
python -m pip install -q -r requirements.txt
if %errorlevel% neq 0 (
    echo [ERROR] Failed to install dependencies. Check requirements.txt.
    pause
    exit /b 1
)

REM Install Playwright browsers if needed (only Chrome channel is used)
echo Checking Playwright browser installation...
python -m playwright install chrome 2>nul

echo.
echo Starting automation...
echo.
python automation.py %*

echo.
if %errorlevel% equ 0 (
    echo Automation completed successfully.
) else (
    echo Automation finished with errors. Check logs\automation.log for details.
)

pause
endlocal
