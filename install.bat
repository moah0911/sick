@echo off
rem Double-click / cmd entry point for the PowerShell installer.
rem Usage: install.bat [-Global] [-WithVideo] [-Uninstall]
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
exit /b %ERRORLEVEL%
