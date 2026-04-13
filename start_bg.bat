@echo off
:: Change directory to where the batch file is located
cd /d "%~dp0"

:: Run using the env's pythonw.exe
:: Assumes your venv folder is named 'env'
start "" "env\Scripts\pythonw.exe" "main.py"

exit
