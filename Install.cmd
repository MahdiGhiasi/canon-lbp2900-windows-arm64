@echo off
setlocal EnableExtensions DisableDelayedExpansion
title Canon LBP2900 setup
pushd "%~dp0" || exit /b 1
set "CanonPS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if exist "%SystemRoot%\Sysnative\WindowsPowerShell\v1.0\powershell.exe" set "CanonPS=%SystemRoot%\Sysnative\WindowsPowerShell\v1.0\powershell.exe"

echo Setting up the Canon LBP2900 for this Windows account...
if not exist "app\hiscoa.dll" goto incomplete
if not exist "install.py" goto incomplete
call :run_with_python
set "result=%errorlevel%"
if not "%result%"=="81" goto finish

echo Installing Python 3.12 for Windows ARM64 with WinGet...
call :install_python
set "result=%errorlevel%"
if "%result%"=="82" goto get_winget
if not "%result%"=="0" goto finish
goto python_installed

:get_winget
echo Setting up Microsoft's Windows Package Manager for this account...
call :restore_winget
set "result=%errorlevel%"
if not "%result%"=="0" goto finish
call :install_python
set "result=%errorlevel%"
if not "%result%"=="0" goto finish

:python_installed
call :run_with_python
set "result=%errorlevel%"
if "%result%"=="81" echo Setup could not start a native ARM64 Python after WinGet finished.
goto finish

:incomplete
echo Extract the entire Canon LBP2900 ZIP before opening Install.cmd.
set "result=1"

:finish
popd
if not "%result%"=="0" (
    echo.
    echo Setup did not finish. Read the message above for the reason.
    pause
)
exit /b %result%

:run_with_python
rem Probe real interpreters, including custom installs registered under PEP 514.
rem The registry is updated immediately even when this console has the old PATH.
"%CanonPS%" -NoLogo -NoProfile -NonInteractive -Command ^
  "$ErrorActionPreference='Stop'; try {" ^
  "  $arch=Get-ItemPropertyValue -LiteralPath 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Environment' -Name PROCESSOR_ARCHITECTURE;" ^
  "  if($arch -ne 'ARM64'){throw 'This package requires Windows on ARM64.'};" ^
  "  $paths=@((Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312-arm64\python.exe'),(Join-Path $env:ProgramFiles 'Python312-arm64\python.exe'));" ^
  "  $keys=Get-ChildItem 'HKCU:\SOFTWARE\Python\PythonCore','HKLM:\SOFTWARE\Python\PythonCore' -ErrorAction SilentlyContinue;" ^
  "  foreach($k in $keys){$loc=$k.OpenSubKey('InstallPath'); if($loc){try{$exe=$loc.GetValue('ExecutablePath'); if(!$exe -and $loc.GetValue('')){$exe=Join-Path $loc.GetValue('') 'python.exe'}; if($exe){$paths+=$exe}}finally{$loc.Close()}}};" ^
  "  $paths+=@(Get-Command python.exe -CommandType Application -All -ErrorAction SilentlyContinue | Where-Object {$_.Source -notlike '*\Microsoft\WindowsApps\*'} | Select-Object -ExpandProperty Source);" ^
  "  foreach($exe in ($paths | Select-Object -Unique)){if(Test-Path -LiteralPath $exe -PathType Leaf){try{& $exe -E -B .\install.py --probe 2>$null; $ok=($LASTEXITCODE -eq 0)}catch{$ok=$false}; if($ok){& $exe -E -B -u .\install.py; exit $LASTEXITCODE}}};" ^
  "  exit 81" ^
  "} catch {Write-Host $_.Exception.Message; exit 1}"
exit /b %errorlevel%

:install_python
"%CanonPS%" -NoLogo -NoProfile -NonInteractive -Command ^
  "$ErrorActionPreference='Stop'; try {" ^
  "  function Find-WinGet { $alias=Join-Path $env:LOCALAPPDATA 'Microsoft\WindowsApps\winget.exe'; $pkg=Get-AppxPackage -Name Microsoft.DesktopAppInstaller -ErrorAction SilentlyContinue; $paths=@($alias); if($pkg){$paths+=Join-Path $pkg.InstallLocation 'winget.exe'}; $cmd=Get-Command winget.exe -CommandType Application -ErrorAction SilentlyContinue; if($cmd){$paths+=$cmd.Source}; foreach($file in ($paths | Select-Object -Unique)){if(Test-Path -LiteralPath $file -PathType Leaf){try{$null=& $file --version 2>$null; if($LASTEXITCODE -eq 0){return $file}}catch{}}} };" ^
  "  $wg=Find-WinGet; if(!$wg){try{Add-AppxPackage -RegisterByFamilyName -MainPackage Microsoft.DesktopAppInstaller_8wekyb3d8bbwe -ErrorAction Stop}catch{}; $wg=Find-WinGet}; if(!$wg){exit 82};" ^
  "  & $wg install --id Python.Python.3.12 --exact --architecture arm64 --scope user --source winget --silent --accept-source-agreements --accept-package-agreements --disable-interactivity --force --custom 'Include_launcher=0 InstallLauncherAllUsers=0 Include_pip=1 Include_tcltk=1';" ^
  "  if($LASTEXITCODE -notin 0,3010){throw ('WinGet could not install ARM64 Python. Exit code {0:X8}.' -f [int]$LASTEXITCODE)}; exit 0" ^
  "} catch {Write-Host $_.Exception.Message; exit 1}"
exit /b %errorlevel%

:restore_winget
rem Microsoft signs App Installer and its frameworks. Windows verifies them
rem when deploying the official stable release for the current user.
"%CanonPS%" -NoLogo -NoProfile -NonInteractive -Command ^
  "$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; try {" ^
  "  [Net.ServicePointManager]::SecurityProtocol=[Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12;" ^
  "  $release=Invoke-RestMethod -Uri 'https://api.github.com/repos/microsoft/winget-cli/releases/latest';" ^
  "  $bundle=$release.assets | Where-Object name -eq 'Microsoft.DesktopAppInstaller_8wekyb3d8bbwe.msixbundle'; $deps=$release.assets | Where-Object name -eq 'DesktopAppInstaller_Dependencies.zip'; if(!$bundle -or !$deps){throw 'Microsoft App Installer release assets were unavailable.'};" ^
  "  $dir=(New-Item -ItemType Directory -Path (Join-Path ([IO.Path]::GetTempPath()) ('Canon-WinGet-'+[guid]::NewGuid().ToString('N')))).FullName; $owned=@(); try {" ^
  "    $msix=Join-Path $dir $bundle.name; $owned+=$msix; Invoke-WebRequest -UseBasicParsing -Uri $bundle.browser_download_url -OutFile $msix;" ^
  "    try{Add-AppxPackage -Path $msix -ErrorAction Stop}catch{" ^
  "      $zip=Join-Path $dir $deps.name; $owned+=$zip; Invoke-WebRequest -UseBasicParsing -Uri $deps.browser_download_url -OutFile $zip;" ^
  "      Add-Type -AssemblyName System.IO.Compression.FileSystem; $archive=[IO.Compression.ZipFile]::OpenRead($zip); $frameworks=@(); try{foreach($entry in $archive.Entries){if($entry.FullName.Replace('\','/') -match '(?:^|/)(arm64|neutral)/[^/]+\.(appx|msix)$'){$leaf=[IO.Path]::GetFileName($entry.FullName); $file=Join-Path $dir $leaf; $owned+=$file; [IO.Compression.ZipFileExtensions]::ExtractToFile($entry,$file); $frameworks+=$file}}}finally{$archive.Dispose()};" ^
  "      if(!$frameworks){throw 'ARM64 App Installer frameworks were unavailable.'}; Add-AppxPackage -Path $msix -DependencyPath $frameworks -ErrorAction Stop" ^
  "    }" ^
  "  } finally { foreach($file in $owned){if(Test-Path -LiteralPath $file){Remove-Item -LiteralPath $file -ErrorAction SilentlyContinue}}; if(!(Get-ChildItem -LiteralPath $dir -Force)){[IO.Directory]::Delete($dir,$false)} }; exit 0" ^
  "} catch {Write-Host ('Could not set up Microsoft App Installer. '+$_.Exception.Message); exit 1}"
exit /b %errorlevel%
