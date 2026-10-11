@echo off

set "CURRENT_PATH=%~dp0"

start "" "%CURRENT_PATH%venv-app-executer-main\Scripts\pythonw.exe" "%CURRENT_PATH%src\main.py"
