@echo off
REM Daily DWD Climate Data Center pull. Register in Windows Task Scheduler as
REM "DWD-Climate-daily" (see README, "Taeglich laufen lassen"). Only the
REM recent/ zips actually change day to day; historical/ is skipped once on
REM disk, so this finishes in minutes after the first full mirror.

cd /d "%~dp0"
if not exist logs mkdir logs
set PYTHONUTF8=1

echo. >> logs\daily.log
echo ==================== %DATE% %TIME% ==================== >> logs\daily.log
"C:\Users\emira\AppData\Local\Python\pythoncore-3.14-64\python.exe" fetch_dwd_climate.py >> logs\daily.log 2>&1
