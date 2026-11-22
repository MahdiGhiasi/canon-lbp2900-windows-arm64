# SPDX-License-Identifier: GPL-3.0-or-later
# Windows ARM64 adaptation, modified 2026-11-22.

function Get-CanonLocations {
    $base = [IO.Path]::GetFullPath([Environment]::GetFolderPath('LocalApplicationData'))
    [pscustomobject]@{
        Base = $base
        Root = Join-Path $base 'CanonLBP2900'
        Startup = Join-Path ([Environment]::GetFolderPath('Startup')) 'Canon LBP2900 USB.lnk'
        Status = Join-Path ([Environment]::GetFolderPath('Programs')) 'Canon LBP2900 Print Status.lnk'
    }
}

function Get-CanonPrinterUuid {
    # Match Python uuid.uuid5(NAMESPACE_DNS, hostname + suffix), in network order.
    $namespace = [byte[]](0x6b,0xa7,0xb8,0x10,0x9d,0xad,0x11,0xd1,0x80,0xb4,0x00,0xc0,0x4f,0xd4,0x30,0xc8)
    $name = [Text.Encoding]::UTF8.GetBytes([Net.Dns]::GetHostName() + '.canon-lbp2900.usb')
    $sha = [Security.Cryptography.SHA1]::Create()
    try { $bytes = $sha.ComputeHash([byte[]]($namespace + $name)) } finally { $sha.Dispose() }
    $bytes[6] = ($bytes[6] -band 15) -bor 80
    $bytes[8] = ($bytes[8] -band 63) -bor 128
    $hex = ([BitConverter]::ToString($bytes[0..15])).Replace('-', '')
    ([guid]::ParseExact($hex, 'N')).ToString('D')
}

function Assert-CanonQueue($queue, $uuid) {
    if (!$queue) { return }
    $matching = $false
    if ($queue.DriverName -eq 'Microsoft IPP Class Driver') {
        if ($queue.PortName -in 'http://127.0.0.1:16319/ipp/print', 'ipp://127.0.0.1:16319/ipp/print') {
            $matching = $true
        } elseif ($queue.PortName -like 'WSD-*') {
            $key = Join-Path 'HKLM:\SYSTEM\CurrentControlSet\Control\Print\Monitors\WSD Port\Ports' $queue.PortName
            $id = Get-ItemPropertyValue -LiteralPath $key -Name 'Printer UUID' -ErrorAction SilentlyContinue
            $matching = $id -and [guid]$id -eq [guid]$uuid
        }
    }
    if (!$matching) { throw 'The named queue could not be identified as this Canon USB installation.' }
}

function Remove-CanonQueue($uuid) {
    $queue = Get-Printer -ErrorAction Stop | Where-Object Name -eq 'Canon LBP2900'
    if (!$queue) { return }
    Assert-CanonQueue $queue $uuid
    $remove = {
        param($uuid)
        $ErrorActionPreference = 'Stop'
        Import-Module (Join-Path $PSHOME 'Modules\PrintManagement\PrintManagement.psd1')
        $queue = Get-Printer -ErrorAction Stop | Where-Object Name -eq 'Canon LBP2900'
        if (!$queue) { return }
        Assert-CanonQueue $queue $uuid
        Remove-Printer -Name 'Canon LBP2900' -ErrorAction Stop
        if (Get-Printer -ErrorAction Stop | Where-Object Name -eq 'Canon LBP2900') {
            throw 'Windows is still removing the printer. Run Uninstall.cmd again after the queue closes.'
        }
    }
    $principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
    if ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        & $remove $uuid
    } else {
        # Only the fixed queue operation and its identity check run elevated.
        $check = (Get-Item Function:\Assert-CanonQueue).ScriptBlock.ToString()
        $script = '& { function Assert-CanonQueue {' + $check + '}; & {' + $remove.ToString() + '} ' + ([guid]$uuid).ToString('D') + ' }'
        $arguments = '-NoLogo -NoProfile -NonInteractive -Command "' + $script + '"'
        Write-Host 'Approve the Windows administrator prompt to remove the printer queue.'
        $child = Start-Process -FilePath (Join-Path $PSHOME 'powershell.exe') -Verb RunAs -ArgumentList $arguments -WorkingDirectory ([Environment]::SystemDirectory) -WindowStyle Hidden -Wait -PassThru
        if ($child.ExitCode -ne 0) { throw 'Printer removal did not finish. Run Uninstall.cmd again to retry.' }
    }
    if (Get-Printer -ErrorAction Stop | Where-Object Name -eq 'Canon LBP2900') {
        throw 'Windows still has the Canon queue. Run Uninstall.cmd again to retry.'
    }
}

function Test-CanonScriptArgument($arguments, $expectedPaths) {
    if (!$arguments) { return $false }
    $match = [regex]::Match($arguments, '(?:^|\s)(?:"(?<path>[^"]+)"|(?<path>[^\s"]+))\s*$')
    if (!$match.Success) { return $false }
    $path = $match.Groups['path'].Value
    if (![IO.Path]::IsPathRooted($path)) { return $false }
    try {
        # Windows can store the same path using an 8.3 name in shortcuts.
        $full = [IO.Path]::GetFullPath($path)
        foreach ($expected in $expectedPaths) {
            if ($full.Equals([IO.Path]::GetFullPath($expected), [StringComparison]::OrdinalIgnoreCase)) {
                return $true
            }
        }
    } catch { return $false }
    return $false
}

function Stop-CanonProcesses($root) {
    $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $app = Join-Path $root 'app'
    $scripts = @((Join-Path $app 'bridge.pyw'), (Join-Path $app 'status.pyw'))
    $candidates = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'"
    foreach ($info in $candidates) {
        if (!(Test-CanonScriptArgument $info.CommandLine $scripts)) { continue }
        if ((Invoke-CimMethod -InputObject $info -MethodName GetOwnerSid).Sid -ne $sid) { continue }
        $process = Get-Process -Id $info.ProcessId -ErrorAction SilentlyContinue
        if (!$process) { continue }
        $null = $process.Handle
        # Recheck after opening the handle to avoid a recycled process ID.
        $current = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $process.Id)
        if (!$current -or $current.CreationDate -ne $info.CreationDate -or
            !(Test-CanonScriptArgument $current.CommandLine $scripts)) { continue }
        if (!$process.HasExited) {
            $process.Kill()
            if (!$process.WaitForExit(5000)) { throw 'A Canon helper process is still running. Run Uninstall.cmd again.' }
        }
    }
}

function Remove-CanonShortcut($path, $root, $script) {
    if (!(Test-Path -LiteralPath $path)) { return }
    $item = Get-Item -LiteralPath $path -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        [IO.File]::Delete($item.FullName)
        return
    }
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($path)
    $expected = Join-Path (Join-Path $root 'app') $script
    if (!(Test-CanonScriptArgument $shortcut.Arguments @($expected))) {
        Write-Host 'Kept a same-named shortcut that points to another application.'
        return
    }
    Remove-Item -LiteralPath $path -Force
}

function Remove-CanonTree($path, $root) {
    $full = [IO.Path]::GetFullPath($path)
    if ($full -ne $root -and !$full.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'A cleanup path leaves the Canon installation directory.'
    }
    $item = Get-Item -LiteralPath $full -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        # Delete the link itself. Its target can be outside this installation.
        if ($item.PSIsContainer) { [IO.Directory]::Delete($full, $false) }
        else { [IO.File]::Delete($full) }
        return
    }
    if ($item.PSIsContainer) {
        foreach ($child in (Get-ChildItem -LiteralPath $full -Force)) {
            Remove-CanonTree $child.FullName $root
        }
        [IO.Directory]::Delete($full, $false)
    } else {
        Remove-Item -LiteralPath $full -Force
    }
}

function Invoke-CanonUninstall {
    $ErrorActionPreference = 'Stop'
    Import-Module (Join-Path $PSHOME 'Modules\PrintManagement\PrintManagement.psd1')
    $locations = Get-CanonLocations
    $root = [IO.Path]::GetFullPath($locations.Root)
    $base = [IO.Path]::GetFullPath($locations.Base).TrimEnd('\')
    if ([IO.Path]::GetDirectoryName($root) -ne $base -or [IO.Path]::GetFileName($root) -ne 'CanonLBP2900') {
        throw 'The Canon installation path could not be verified.'
    }
    if ($env:CANON_UNINSTALL_DIR -and
        ([IO.Path]::GetFullPath($env:CANON_UNINSTALL_DIR).TrimEnd('\') + '\').StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Run Uninstall.cmd from the extracted download folder.'
    }
    $queue = Get-Printer -ErrorAction Stop | Where-Object Name -eq 'Canon LBP2900'
    $uuid = Get-CanonPrinterUuid
    Assert-CanonQueue $queue $uuid
    $jobs = Join-Path $root 'jobs'
    $saved = @(Get-ChildItem -LiteralPath $jobs -File -ErrorAction SilentlyContinue | Where-Object Extension -in '.pdf', '.pwg', '.part')
    $windowsJobs = @()
    if ($queue) { $windowsJobs = @(Get-PrintJob -PrinterName 'Canon LBP2900' -ErrorAction Stop) }
    if (!$queue -and !(Test-Path -LiteralPath $root) -and
        !(Test-Path -LiteralPath $locations.Startup) -and !(Test-Path -LiteralPath $locations.Status)) {
        Write-Host 'Canon LBP2900 is already uninstalled for this Windows account.'
        return
    }
    Write-Host 'This removes the Canon printer queue, helper, shortcuts, private runtime, and local job history.'
    if ($saved.Count -or $windowsJobs.Count) {
        Write-Host ('This also stops printing and permanently deletes {0} saved documents and {1} Windows print jobs.' -f $saved.Count, $windowsJobs.Count)
    }
    if ((Read-Host 'Uninstall Canon LBP2900? [y/N]') -notin 'y', 'yes') {
        Write-Host 'Uninstall canceled.'
        return
    }
    $lock = $null
    try {
        if (Test-Path -LiteralPath $root) {
            $item = Get-Item -LiteralPath $root -Force
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw 'The installation directory is a link. Review its target before uninstalling.'
            }
            $lockPath = Join-Path $root 'setup.lock'
            if ((Get-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue).Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw 'The setup lock is a link. Review the installation directory before uninstalling.'
            }
            $lock = [IO.File]::Open($lockPath, 'OpenOrCreate', 'ReadWrite', 'None')
        }
        Remove-CanonQueue $uuid
        Remove-CanonShortcut $locations.Startup $root 'bridge.pyw'
        Remove-CanonShortcut $locations.Status $root 'status.pyw'
        Stop-CanonProcesses $root
    } finally {
        if ($lock) { $lock.Dispose() }
    }
    if (Test-Path -LiteralPath $root) { Remove-CanonTree $root $root }
    Write-Host 'Canon LBP2900 has been uninstalled.'
}

try {
    Invoke-CanonUninstall
} catch {
    Write-Host ('Uninstall did not finish. ' + $_.Exception.Message)
    exit 1
}
