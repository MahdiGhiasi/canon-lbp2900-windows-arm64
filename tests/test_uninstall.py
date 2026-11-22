# SPDX-License-Identifier: GPL-3.0-or-later
# Windows ARM64 adaptation, modified 2026-11-22.
"""Exercise uninstall using temporary files and mocked Windows printer operations."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
PREAMBLE = r"""
$ErrorActionPreference = 'Stop'
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($env:TEST_SOURCE, [ref]$tokens, [ref]$errors)
if ($errors) { throw ($errors | Out-String) }
$definitions = $ast.EndBlock.Statements | Where-Object { $_ -is [Management.Automation.Language.FunctionDefinitionAst] }
. ([scriptblock]::Create(($definitions.Extent.Text -join [Environment]::NewLine)))
$script:removeImplementation=(Get-Item Function:\Remove-CanonQueue).ScriptBlock
$script:stopImplementation=(Get-Item Function:\Stop-CanonProcesses).ScriptBlock

$base = Join-Path $env:TEST_ROOT 'Local'
$root = Join-Path $base 'CanonLBP2900'
$script:locations = [pscustomobject]@{
    Base=$base; Root=$root
    Startup=(Join-Path $env:TEST_ROOT 'Startup.lnk')
    Status=(Join-Path $env:TEST_ROOT 'Status.lnk')
}
$script:queue = [pscustomobject]@{Name='Canon LBP2900'; DriverName='Microsoft IPP Class Driver'; PortName='http://127.0.0.1:16319/ipp/print'}
$script:answer='yes'
$script:removed=$false
$script:stopped=$false
function Get-CanonLocations { $script:locations }
function Import-Module { param($Name) }
function Get-Printer { param($Name,$ErrorAction) $script:queue }
function Get-PrintJob { param($PrinterName,$ErrorAction) [pscustomobject]@{Id=1} }
function Read-Host { param($Prompt) $script:answer }
function Stop-CanonProcesses { param($root) $script:stopped=$true }
function Remove-CanonQueue {
    param($uuid)
    $script:removed=$true
    $script:queue=$null
}
$null=New-Item -ItemType Directory -Path (Join-Path $root 'app') -Force
$null=New-Item -ItemType Directory -Path (Join-Path $root 'jobs') -Force
[IO.File]::WriteAllText((Join-Path $root 'jobs\test.held.pdf'), 'Synthetic test data')
[IO.File]::WriteAllText((Join-Path $root 'app\bridge.pyw'), 'Synthetic helper')
[IO.File]::WriteAllText((Join-Path $root 'history.log'), 'Synthetic history')
$shell=New-Object -ComObject WScript.Shell
foreach($entry in @(@($script:locations.Startup,'bridge.pyw'),@($script:locations.Status,'status.pyw'))) {
    $link=$shell.CreateShortcut($entry[0])
    $link.TargetPath=Join-Path $root 'runtime-312\Scripts\pythonw.exe'
    $link.Arguments='-E -s "'+(Join-Path (Join-Path $root 'app') $entry[1])+'"'
    $link.Save()
}
"""


@unittest.skipUnless(sys.platform == 'win32', 'Windows PowerShell uninstall checks')
class UninstallTests(unittest.TestCase):
    def check(self, body):
        powershell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        with tempfile.TemporaryDirectory(prefix='canon uninstall & qa ') as temporary:
            env = dict(os.environ, TEST_ROOT=temporary, TEST_SOURCE=str(ROOT / 'uninstall.ps1'))
            result = subprocess.run([str(powershell), '-NoLogo', '-NoProfile', '-NonInteractive',
                                     '-Command', PREAMBLE + '\n' + body],
                                    env=env, capture_output=True, text=True, timeout=25)
            if result.returncode == 77:
                self.skipTest('The environment does not permit creating NTFS junctions.')
            if result.returncode == 78:
                self.skipTest('The filesystem does not provide 8.3 path aliases.')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return result.stdout

    def test_uuid_matches_existing_installations(self):
        expected = str(uuid.uuid5(uuid.NAMESPACE_DNS, f'{socket.gethostname()}.canon-lbp2900.usb'))
        output = self.check('Write-Host (Get-CanonPrinterUuid)')
        self.assertIn(expected, output)

    def test_batch_entry_point(self):
        # Exercise the actual CMD wrapper with a disposable, empty installation.
        with tempfile.TemporaryDirectory(prefix='canon entry & qa ') as temporary:
            directory = Path(temporary)
            (directory / 'Uninstall.cmd').write_bytes((ROOT / 'Uninstall.cmd').read_bytes())
            script = (ROOT / 'uninstall.ps1').read_text(encoding='utf-8')
            injection = r"""
function Import-Module { param($Name) }
function Get-Printer { param($Name,$ErrorAction) }
function Get-CanonLocations {
    $base=Join-Path $env:TEST_ROOT 'EmptyLocal'
    [pscustomobject]@{Base=$base;Root=(Join-Path $base 'CanonLBP2900');Startup=(Join-Path $base 'Startup.lnk');Status=(Join-Path $base 'Status.lnk')}
}
"""
            marker = '\ntry {\n    Invoke-CanonUninstall'
            self.assertEqual(script.count(marker), 1)
            (directory / 'uninstall.ps1').write_text(script.replace(marker, injection + marker), encoding='utf-8')
            result = subprocess.run(['cmd.exe', '/d', '/c', 'Uninstall.cmd'], cwd=directory,
                                    env=dict(os.environ, TEST_ROOT=temporary),
                                    input='\n', capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('already uninstalled', result.stdout)

    def test_complete_removal_and_second_run(self):
        self.check(r"""
Invoke-CanonUninstall
if ((Test-Path -LiteralPath $root) -or (Test-Path -LiteralPath $script:locations.Startup) -or
    (Test-Path -LiteralPath $script:locations.Status) -or !$script:removed -or !$script:stopped) { throw 'Incomplete cleanup' }
Invoke-CanonUninstall
""")

    def test_cancel_keeps_installation(self):
        self.check(r"""
$script:answer='n'
Invoke-CanonUninstall
if (!(Test-Path -LiteralPath (Join-Path $root 'jobs\test.held.pdf')) -or
    !(Test-Path -LiteralPath $script:locations.Startup) -or $script:removed -or $script:stopped) { throw 'Canceled uninstall changed the installation' }
""")

    def test_short_path_shortcuts_are_removed(self):
        self.check(r"""
$shortRoot=(New-Object -ComObject Scripting.FileSystemObject).GetFolder($root).ShortPath
if ($shortRoot -eq [IO.Path]::GetFullPath($root)) { exit 78 }
foreach($entry in @(@($script:locations.Startup,'bridge.pyw'),@($script:locations.Status,'status.pyw'))) {
    $link=$shell.CreateShortcut($entry[0])
    $link.Arguments='-E -s "'+(Join-Path (Join-Path $shortRoot 'app') $entry[1])+'"'
    $link.Save()
}
Invoke-CanonUninstall
if ((Test-Path -LiteralPath $script:locations.Startup) -or
    (Test-Path -LiteralPath $script:locations.Status) -or (Test-Path -LiteralPath $root)) { throw 'Short-path cleanup failed' }
""")

    def test_unrelated_shortcut_is_preserved(self):
        self.check(r"""
$link=$shell.CreateShortcut($script:locations.Startup)
$link.Arguments='"'+(Join-Path $env:TEST_ROOT 'another-app.pyw')+'"'
$link.Save()
Invoke-CanonUninstall
if (!(Test-Path -LiteralPath $script:locations.Startup) -or
    (Test-Path -LiteralPath $script:locations.Status) -or (Test-Path -LiteralPath $root)) { throw 'Shortcut ownership check failed' }
""")

    def test_queue_failure_keeps_files_and_helper(self):
        self.check(r"""
function Remove-CanonQueue { throw 'Simulated UAC cancellation' }
$failure=$null
try { Invoke-CanonUninstall } catch { $failure=$_.Exception.Message }
if ($failure -ne 'Simulated UAC cancellation' -or
    !(Test-Path -LiteralPath (Join-Path $root 'app\bridge.pyw')) -or
    !(Test-Path -LiteralPath $script:locations.Startup) -or $script:stopped) { throw 'Failure was not safely handled' }
""")

    def test_different_printer_is_rejected(self):
        self.check(r"""
$script:queue.DriverName='Another driver'
$failure=$null
try { Invoke-CanonUninstall } catch { $failure=$_.Exception.Message }
if (!$failure -or $script:removed -or $script:stopped -or !(Test-Path -LiteralPath $root)) { throw 'Unrelated queue was touched' }
""")

    def test_setup_lock_prevents_concurrent_removal(self):
        self.check(r"""
$lock=[IO.File]::Open((Join-Path $root 'setup.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
try {
    $failure=$null
    try { Invoke-CanonUninstall } catch { $failure=$_.Exception.Message }
    if (!$failure -or $script:removed -or $script:stopped) { throw 'Setup lock was ignored' }
} finally { $lock.Dispose() }
""")

    def test_junction_target_survives_cleanup(self):
        self.check(r"""
$outside=Join-Path $env:TEST_ROOT 'Outside'
$null=New-Item -ItemType Directory -Path $outside
[IO.File]::WriteAllText((Join-Path $outside 'keep.txt'), 'Keep this file')
$junction=Join-Path $root 'linked-folder'
try { $null=New-Item -ItemType Junction -Path $junction -Value $outside }
catch {
    if ($_.Exception.Message -match 'Access is denied|privilege') { exit 77 }
    throw
}
Invoke-CanonUninstall
if (!(Test-Path -LiteralPath (Join-Path $outside 'keep.txt')) -or (Test-Path -LiteralPath $root)) { throw 'Cleanup followed a junction' }
""")

    def test_wrong_root_is_rejected(self):
        self.check(r"""
$script:locations.Root=$base
$failure=$null
try { Invoke-CanonUninstall } catch { $failure=$_.Exception.Message }
if (!$failure -or $script:removed -or !(Test-Path -LiteralPath $root)) { throw 'Root validation failed' }
""")

    def test_uac_queue_removal_arguments(self):
        self.check(r"""
Set-Item Function:\Remove-CanonQueue -Value $script:removeImplementation
function Remove-Printer {
    param($Name,$ErrorAction)
    if($Name -ne 'Canon LBP2900'){throw 'Wrong queue'}
    $script:removed=$true
    $script:queue=$null
}
function Start-Process {
    param($FilePath,$Verb,$ArgumentList,$WorkingDirectory,$WindowStyle,[switch]$Wait,[switch]$PassThru)
    if($Verb -ne 'RunAs' -or $WindowStyle -ne 'Hidden' -or !$Wait -or !$PassThru -or
       $FilePath -ne (Join-Path $PSHOME 'powershell.exe') -or $WorkingDirectory -ne [Environment]::SystemDirectory){throw 'Incorrect UAC arguments'}
    $prefix='-NoLogo -NoProfile -NonInteractive -Command "'
    if(!$ArgumentList.StartsWith($prefix) -or !$ArgumentList.EndsWith('"')){throw 'Incorrect command quoting'}
    $payload=$ArgumentList.Substring($prefix.Length,$ArgumentList.Length-$prefix.Length-1)
    . ([scriptblock]::Create($payload))
    [pscustomobject]@{ExitCode=0}
}
Remove-CanonQueue (Get-CanonPrinterUuid)
if(!$script:removed -or $script:queue){throw 'Queue removal failed'}
""")

    def test_only_owned_helper_processes_stop(self):
        self.check(r"""
Set-Item Function:\Stop-CanonProcesses -Value $script:stopImplementation
$script:stoppedIds=@()
$script:currentSid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$expected=Join-Path $root 'app\bridge.pyw'
$script:processes=@(
    [pscustomobject]@{ProcessId=100;CommandLine=('pythonw.exe -E -s "'+$expected+'"');CreationDate=1;Owned=$true},
    [pscustomobject]@{ProcessId=101;CommandLine='pythonw.exe other.pyw';CreationDate=1;Owned=$true},
    [pscustomobject]@{ProcessId=102;CommandLine=('pythonw.exe "'+$expected+'"');CreationDate=1;Owned=$false}
)
function Get-CimInstance {
    param($ClassName,$Filter)
    if($Filter -like 'ProcessId=*') { $script:processes | Where-Object ProcessId -eq ([int]$Filter.Split('=')[1]) }
    else { $script:processes }
}
function Invoke-CimMethod {
    param($InputObject,$MethodName)
    if($InputObject.Owned){[pscustomobject]@{Sid=$script:currentSid}}
    else {[pscustomobject]@{Sid='S-1-0-0'}}
}
function Get-Process {
    param($Id,$ErrorAction)
    $p=[pscustomobject]@{Id=$Id;Handle=0;HasExited=$false}
    $p | Add-Member ScriptMethod Kill {$script:stoppedIds+=$this.Id}
    $p | Add-Member ScriptMethod WaitForExit {param($timeout) $true}
    $p
}
Stop-CanonProcesses $root
if($script:stoppedIds.Count -ne 1 -or $script:stoppedIds[0] -ne 100){throw 'Wrong processes stopped'}
""")


if __name__ == '__main__':
    unittest.main()
