@echo off
rem Weekly FPL auto-lineup launcher. The PowerShell runner validates Claude's
rem explicit completion status and propagates authentication/tool failures to
rem Windows Task Scheduler instead of returning a false success.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\Users\pasca\dev\projects\fplbench\main\scripts\friday_lineup_runner.ps1"
exit /b %ERRORLEVEL%
