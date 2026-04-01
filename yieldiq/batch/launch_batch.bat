@echo off
setlocal enabledelayedexpansion
title YieldIQ — Nightly Batch Pre-compute

cd /d "C:\Users\vinit\Downloads\yieldiq_v6\yieldiq"

:: Activate conda environment
call "C:\ProgramData\miniconda3\Scripts\activate.bat" dcf_screener

:: Load .env vars
if exist ".env" (
    for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
        set "_ln=%%A"
        if not "!_ln!"=="" if not "!_ln:~0,1!"=="#" set "%%A=%%B"
    )
)

echo.
echo  +----------------------------------------------+
echo  ^|   YieldIQ  -  Nightly Batch Runner           ^|
echo  ^|   Scope : All US + India tickers             ^|
echo  ^|   Output: data/screener_results.csv          ^|
echo  +----------------------------------------------+
echo.

:: Run the pre-compute script
"C:\ProgramData\miniconda3\envs\dcf_screener\python.exe" batch\nightly_precompute.py

echo.
echo  Batch complete. Results saved to data/screener_results.csv
echo  Log: logs/nightly_batch.log
echo.
pause
