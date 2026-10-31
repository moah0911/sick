@echo off
rem sick - global launcher (Windows). Resolves the repo checkout and runs
rem the `sick` console script from its venv; falls back to `uv run`, then
rem to the Python launcher.
setlocal
for %%I in ("%~dp0..") do set "ROOT=%%~fI"
set "SICK_ROOT=%ROOT%"
if exist "%ROOT%\.venv\Scripts\sick.exe" (
    "%ROOT%\.venv\Scripts\sick.exe" %*
    exit /b %ERRORLEVEL%
)
where uv >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    uv run --project "%ROOT%" sick %*
    exit /b %ERRORLEVEL%
)
py -m sick.cli %*
exit /b %ERRORLEVEL%
