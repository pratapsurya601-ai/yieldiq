@echo off
:: ─────────────────────────────────────────────────────────────────────
:: setup_scheduler.bat
:: Registers the YieldIQ nightly batch job with Windows Task Scheduler.
:: Run this ONCE as Administrator to set up the schedule.
:: The job will run every night at 2:00 AM automatically.
:: ─────────────────────────────────────────────────────────────────────
echo.
echo  Registering YieldIQ Nightly Batch with Task Scheduler...
echo.

schtasks /create ^
  /tn "YieldIQ_NightlyBatch" ^
  /tr "\"C:\Users\vinit\Downloads\yieldiq_v6\yieldiq\batch\launch_batch.bat\"" ^
  /sc DAILY ^
  /st 02:00 ^
  /ru "%USERNAME%" ^
  /rl HIGHEST ^
  /f

if %ERRORLEVEL% EQU 0 (
    echo.
    echo  SUCCESS — Task registered: YieldIQ_NightlyBatch
    echo  Schedule : Daily at 2:00 AM
    echo  Run now  : schtasks /run /tn YieldIQ_NightlyBatch
    echo  View log : logs\nightly_batch.log
    echo.
) else (
    echo.
    echo  ERROR — Could not register task. Run this script as Administrator.
    echo.
)
pause
