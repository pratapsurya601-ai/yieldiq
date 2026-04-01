@echo off
setlocal enabledelayedexpansion
title YieldIQ v6 - Admin Mode
color 0A

cd /d "C:\Users\vinit\Downloads\yieldiq_v6\yieldiq"

:: Activate conda environment
call "C:\ProgramData\miniconda3\Scripts\activate.bat" dcf_screener

:: Set admin + env vars
set YIELDIQ_ADMIN=1
set STREAMLIT_SERVER_PORT=8501

:: Load .env file (skip blank lines and comment lines starting with #)
if exist ".env" (
    for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
        set "_ln=%%A"
        if not "!_ln!"=="" (
            if not "!_ln:~0,1!"=="#" (
                set "%%A=%%B"
            )
        )
    )
)

echo.
echo  +----------------------------------------------+
echo  ^|   YieldIQ v6  -  ADMIN / PRO MODE            ^|
echo  ^|   URL  : http://localhost:8501               ^|
echo  ^|   Tier : PRO (Unlimited)                     ^|
echo  +----------------------------------------------+
echo.

:: Open browser after 4 second delay (background process)
start "" cmd /c "timeout /t 4 /nobreak >nul && start http://localhost:8501"

:: Launch Streamlit
"C:\ProgramData\miniconda3\envs\dcf_screener\Scripts\streamlit.exe" run dashboard/app.py ^
  --server.port 8501 ^
  --server.headless false ^
  --browser.gatherUsageStats false

echo.
echo  Dashboard stopped. Press any key to close.
pause >nul
