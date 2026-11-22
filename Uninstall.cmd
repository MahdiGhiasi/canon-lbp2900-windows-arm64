@echo off
setlocal EnableExtensions DisableDelayedExpansion
title Uninstall Canon LBP2900
set "CANON_UNINSTALL_DIR=%~dp0"
set "CanonPS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if exist "%SystemRoot%\Sysnative\WindowsPowerShell\v1.0\powershell.exe" set "CanonPS=%SystemRoot%\Sysnative\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%~dp0uninstall.ps1" (
    echo Extract the complete package before opening Uninstall.cmd.
    pause
    exit /b 1
)
"%CanonPS%" -NoLogo -NoProfile -Command "try { & ([scriptblock]::Create([IO.File]::ReadAllText((Join-Path $env:CANON_UNINSTALL_DIR 'uninstall.ps1')))) } catch { Write-Host $_.Exception.Message; exit 1 }"
set "result=%errorlevel%"
echo.
pause
exit /b %result%
