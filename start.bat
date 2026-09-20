@echo off
setlocal enabledelayedexpansion

echo ==========================================
echo   OceanSight-V Startup
echo ==========================================
echo.

cd /d "%~dp0"

REM Activate virtual environment
if exist ".venv\Scripts\activate.bat" (
    echo Activating virtual environment...
    call .venv\Scripts\activate.bat
)

REM Start backend
echo Starting backend API server on http://127.0.0.1:8001...
start /B "" python -m uvicorn app.api:app --host 127.0.0.1 --port 8001
echo   Backend started

REM Wait for backend to be ready
echo Waiting for backend to be ready...
set /a counter=0
:wait_loop
curl -s http://127.0.0.1:8001/health >nul 2>&1
if %errorlevel% equ 0 (
    echo Backend is ready!
    goto frontend_start
)
set /a counter+=1
if !counter! geq 30 (
    echo Backend did not start in time, continuing anyway...
    goto frontend_start
)
timeout /t 1 /n >nul
goto wait_loop

:frontend_start
REM Start frontend
echo Starting frontend dev server on http://localhost:5173...
cd frontend
start /B "" npm run dev -- --host
cd ..

echo.
echo ==========================================
echo   OceanSight-V is running!
echo ==========================================
echo   Frontend:  http://localhost:5173
echo   Backend:   http://127.0.0.1:8001
echo   API Docs:  http://127.0.0.1:8001/docs
echo ==========================================
echo.