@echo off
cd /d "%~dp0"
python precheck_csv.py --input "%~1"
pause