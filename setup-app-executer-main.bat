@echo off

rem Prepares the app on this PC (venv + Start Menu shortcut + scheduler driver task).
rem Options: -Desktop (also a desktop shortcut), -NoShortcut, -NoScheduler, -RemoveScheduler (uninstall the driver).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup-app-executer-main.ps1" %*
set "EXIT_CODE=%ERRORLEVEL%"

pause
exit /b %EXIT_CODE%
