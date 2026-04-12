@echo off
:: Change directory to where the batch file is located
cd /d "%~dp0"

:: Run using the venv's pythonw.exe
:: Assumes your venv folder is named 'venv'
start "" "venv\Scripts\pythonw.exe" "main.py"

exit