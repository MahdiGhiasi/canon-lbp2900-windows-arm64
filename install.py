# SPDX-License-Identifier: GPL-3.0-or-later
# Windows ARM64 adaptation, modified 2026-11-20.
"""Per-user installation and one-time Windows printer registration."""
import ctypes
import filecmp
import http.client
import msvcrt
import os
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
import time
import uuid

PACKAGE = Path(__file__).resolve().parent
sys.path.insert(0, str(PACKAGE / 'app'))
import ipp_codec as ipp
from ipp_profile import HELPER_VERSION
from windows_queue import queue_handle

ROOT = Path(os.environ['LOCALAPPDATA']) / 'CanonLBP2900'
POWERSHELL = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
RENDER_CHECK = ("from importlib.metadata import version; "
                "assert version('Pillow') == '13.0.0'; "
                "assert version('pypdfium2') == '5.14.0'; "
                "from PIL import Image; import pypdfium2 as pdf; "
                "Image.new('1',(8,1)).tobytes('raw','1;I'); "
                "assert callable(pdf.PdfPage.render)")

SHORTCUTS = r"""
$ErrorActionPreference = 'Stop'
$shell = New-Object -ComObject WScript.Shell
function Set-CanonShortcut($folder, $title, $script) {
    $path = Join-Path ([Environment]::GetFolderPath($folder)) ($title + '.lnk')
    $link = $shell.CreateShortcut($path)
    $link.TargetPath = $env:CANON_PYTHONW
    $link.Arguments = '-E -s "' + (Join-Path $env:CANON_APP_DIR $script) + '"'
    $link.WorkingDirectory = $env:CANON_APP_DIR
    $link.IconLocation = "$env:WINDIR\System32\shell32.dll,16"
    $link.Save()
}
Set-CanonShortcut 'Startup' 'Canon LBP2900 USB' 'bridge.pyw'
Set-CanonShortcut 'Programs' 'Canon LBP2900 Print Status' 'status.pyw'
"""

RESTART_OLD_HELPER = r"""
$ErrorActionPreference = 'Stop'
$listener = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 16319 -State Listen -ErrorAction SilentlyContinue
if (!$listener) { return }
$process = Get-Process -Id $listener.OwningProcess
$null = $process.Handle
$info = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $process.Id)
$expected = '(?:^|\s)"?' + [regex]::Escape((Join-Path $env:CANON_APP_DIR 'bridge.pyw')) + '"?\s*$'
$owner = (Invoke-CimMethod -InputObject $info -MethodName GetOwnerSid).Sid
if ($info.Name -ne 'pythonw.exe' -or $info.CommandLine -notmatch $expected -or
    $owner -ne [Security.Principal.WindowsIdentity]::GetCurrent().User.Value) {
    throw 'Another process owns the Canon port. Setup could not restart the installed helper.'
}
$jobs = Join-Path (Split-Path -Parent $env:CANON_APP_DIR) 'jobs'
function Test-CanonBusy {
    if (Get-ChildItem -LiteralPath $jobs -File | Where-Object Name -Match '\.(active|pending)\.(pdf|pwg)$|\.part$') { return $true }
    if (Get-PrintJob -PrinterName 'Canon LBP2900' -ErrorAction SilentlyContinue) { return $true }
    return [bool](Get-NetTCPConnection -LocalPort 16319 -State Established -OwningProcess $process.Id -ErrorAction SilentlyContinue)
}
if (Test-CanonBusy) { exit 75 }
Start-Sleep -Milliseconds 400
if (Test-CanonBusy) { exit 75 }
if (!$process.HasExited) {
    $process.Kill()
    if (!$process.WaitForExit(5000)) { throw 'The previous Canon print helper is still running.' }
}
"""

# The elevated command consists only of fixed, local Windows operations. Python,
# the helper, its packages and the sign-in shortcut stay in the user's session.
REGISTER = r"""
$ErrorActionPreference = 'Stop'
$name = 'Canon LBP2900'
$queue = Get-Printer -Name $name -ErrorAction SilentlyContinue
if (!$queue -or $env:CANON_NEEDS_STATUS_ACCESS -eq '1') {
    $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $uuid = ([guid]$env:CANON_PRINTER_UUID).ToString('D')
    $add = {
        param($sid, $uuid)
        $ErrorActionPreference = 'Stop'
        Import-Module (Join-Path $PSHOME 'Modules\PrintManagement\PrintManagement.psd1')
        if ((Get-Service -Name Spooler).Status -ne 'Running') { Start-Service -Name Spooler }
        if (!(Get-Printer -Name 'Canon LBP2900' -ErrorAction SilentlyContinue)) {
            Add-Printer -Name 'Canon LBP2900' -IppURL 'http://127.0.0.1:16319/ipp/print' -ErrorAction Stop
        }
        # If a different administrator supplied UAC credentials, the signed-in
        # helper still needs Manage Printer access on this particular queue.
        $end = [DateTime]::UtcNow.AddSeconds(20)
        do {
            $queue = Get-Printer -Name 'Canon LBP2900' -Full
            if ($queue.PortName -in 'http://127.0.0.1:16319/ipp/print','ipp://127.0.0.1:16319/ipp/print') { break }
            $key = Join-Path 'HKLM:\SYSTEM\CurrentControlSet\Control\Print\Monitors\WSD Port\Ports' $queue.PortName
            $id = Get-ItemPropertyValue -LiteralPath $key -Name 'Printer UUID' -ErrorAction SilentlyContinue
            if ($id -or $queue.PortName -notlike 'WSD-*') { break }
            Start-Sleep -Milliseconds 300
        } while ([DateTime]::UtcNow -lt $end)
        if ($queue.PortName -notin 'http://127.0.0.1:16319/ipp/print','ipp://127.0.0.1:16319/ipp/print' -and
            !($id -and [guid]$id -eq [guid]$uuid)) {
            throw 'Windows could not confirm that this queue belongs to the Canon USB helper.'
        }
        $user = [Security.Principal.SecurityIdentifier]::new($sid)
        $acl = [Security.AccessControl.CommonSecurityDescriptor]::new($true, $false, $queue.PermissionSDDL)
        $allowed = $acl.DiscretionaryAcl | Where-Object { $_.SecurityIdentifier.Value -eq $sid -and
            $_.AceQualifier -eq [Security.AccessControl.AceQualifier]::AccessAllowed -and
            ([int]$_.AceFlags -band 8) -eq 0 -and ([int]$_.AccessMask -band 4) -ne 0 }
        if (!$allowed) {
            $acl.DiscretionaryAcl.AddAccess('Allow', $user, 4, 'None', 'None')
            Set-Printer -Name 'Canon LBP2900' -PermissionSDDL ($acl.GetSddlForm('All')) -ErrorAction Stop
        }
    }
    $principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
    if ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        & $add $sid $uuid
    } else {
        Write-Host 'Approve the Windows administrator prompt to set up the Canon LBP2900 queue.'
        $arguments = '-NoLogo -NoProfile -NonInteractive -Command "& {' + $add.ToString() + '} ' + $sid + ' ' + $uuid + '"'
        $child = Start-Process -FilePath (Join-Path $PSHOME 'powershell.exe') -Verb RunAs -ArgumentList $arguments -WorkingDirectory ([Environment]::SystemDirectory) -WindowStyle Hidden -Wait -PassThru
        if ($child.ExitCode -ne 0) {
            throw ('Windows could not register Canon LBP2900. Registration exit code: ' + $child.ExitCode)
        }
    }
}
$end = [DateTime]::UtcNow.AddSeconds(25)
do {
    $queue = Get-Printer -Name $name -ErrorAction SilentlyContinue
    if ($queue) {
        $portKey = Join-Path 'HKLM:\SYSTEM\CurrentControlSet\Control\Print\Monitors\WSD Port\Ports' $queue.PortName
        $identity = Get-ItemPropertyValue -LiteralPath $portKey -Name 'Printer UUID' -ErrorAction SilentlyContinue
        if (($identity -and [guid]$identity -ne [guid]$env:CANON_PRINTER_UUID) -or
            (!$identity -and $queue.DriverName -ne 'Microsoft IPP Class Driver')) {
            throw 'A different printer already uses the name Canon LBP2900.'
        }
        $config = Get-PrintConfiguration -PrinterName $name -ErrorAction SilentlyContinue
        if ($config -and $config.Color -eq $false) {
            Write-Host ('Verified Windows queue: ' + $queue.Name + ' / monochrome.')
            return
        }
    }
    Start-Sleep -Milliseconds 350
} while ([DateTime]::UtcNow -lt $end)
throw 'Windows did not confirm a monochrome Canon LBP2900 queue.'
"""


def renderers_available(python):
    try:
        probe = subprocess.run([str(python), '-I', '-B', '-c', RENDER_CHECK],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return probe.returncode == 0
    except OSError:
        return False


def suitable_python():
    if sys.version_info[:2] != (3, 12) or sysconfig.get_platform() != 'win-arm64':
        return False
    if not Path(sys.executable).with_name('pythonw.exe').is_file():
        return False
    try:
        import sqlite3
        import tkinter
    except (ImportError, OSError):
        return False
    try:
        tkinter.Tcl()
    except (tkinter.TclError, OSError, RuntimeError):
        return False
    return True


def ensure_runtime():
    base = Path(sys.executable)
    env_dir = ROOT / 'runtime-312'
    private = env_dir / 'Scripts/python.exe'
    if private.with_name('pythonw.exe').is_file() and renderers_available(private):
        return private
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError('The bundled rendering libraries require native Python 3.12.')
    print('Installing the bundled ARM64 rendering libraries for this account...')
    subprocess.run([str(base), '-E', '-m', 'venv', str(env_dir)], check=True)
    subprocess.run([str(private), '-I', '-m', 'pip', '--isolated', '--disable-pip-version-check',
                    'install', '--no-input', '--no-index', '--only-binary=:all:', '--no-deps',
                    '--require-hashes', '--find-links', str(PACKAGE / 'setup/wheels'),
                    '-r', str(PACKAGE / 'setup/requirements.txt')], check=True)
    if not renderers_available(private):
        raise RuntimeError('The installed ARM64 rendering libraries failed their startup check.')
    return private


def powershell(body, env, *, defer_busy=False):
    command = ("try {\n" + body + "\n} catch { "
               "Write-Host $_.Exception.Message; exit 1 }")
    result = subprocess.run([str(POWERSHELL), '-NoLogo', '-NoProfile', '-NonInteractive',
                             '-Command', command], env=env)
    if result.returncode and not (defer_busy and result.returncode == 75):
        raise RuntimeError('Windows setup did not finish. Run Install.cmd again to retry.')
    return result.returncode


def live_profile(*, with_version=False):
    group = [
        ipp.Attr(ipp.TAG_CHARSET, 'attributes-charset', ['utf-8']),
        ipp.Attr(ipp.TAG_LANGUAGE, 'attributes-natural-language', ['en']),
        ipp.Attr(ipp.TAG_URI, 'printer-uri', ['ipp://127.0.0.1:16319/ipp/print']),
        ipp.Attr(ipp.TAG_KEYWORD, 'requested-attributes',
                 ['printer-make-and-model', 'color-supported', 'printer-uuid']),
    ]
    request = ipp.encode_response((2, 0), ipp.OP_GET_PRINTER_ATTRIBUTES, 1, [(ipp.TAG_OPERATION, group)])
    conn = http.client.HTTPConnection('127.0.0.1', 16319, timeout=2)
    try:
        conn.request('POST', '/ipp/print', request, {'Content-Type': 'application/ipp'})
        response = conn.getresponse()
        if response.status != 200 or response.getheader('Content-Type', '').split(';')[0] != 'application/ipp':
            raise RuntimeError('Another program is using the Canon helper port (16319).')
        profile = ipp.decode_request(response.read(131072))
        if (profile.operation != ipp.STATUS_OK or profile.request_id != 1 or
                profile.value('printer-make-and-model', tag=ipp.TAG_PRINTER) != 'Canon LBP2900' or
                profile.value('color-supported', tag=ipp.TAG_PRINTER) is not False):
            raise RuntimeError('The local IPP endpoint did not identify a monochrome Canon LBP2900.')
        identifier = profile.value('printer-uuid', tag=ipp.TAG_PRINTER)
        identity = str(uuid.UUID(str(identifier).removeprefix('urn:uuid:')))
        return (identity, response.getheader('Server', '').partition(' ')[0]) if with_version else identity
    except (ConnectionRefusedError, ConnectionResetError, TimeoutError, http.client.RemoteDisconnected):
        return None
    finally:
        conn.close()


def ensure_helper(pythonw, app, env, files_changed):
    running = live_profile(with_version=True)
    if running:
        if running[1] == HELPER_VERSION and not files_changed:
            return running[0], True
        print('Updating the running Canon USB helper...')
        if powershell(RESTART_OLD_HELPER, env, defer_busy=True) == 75:
            return running[0], False
    print('Starting the Canon USB print helper...')
    process = subprocess.Popen([str(pythonw), '-E', '-s', str(app / 'bridge.pyw')], cwd=app,
                               creationflags=subprocess.CREATE_NO_WINDOW)
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        running = live_profile(with_version=True)
        if running and running[1] == HELPER_VERSION:
            return running[0], True
        if process.poll() is not None:
            break
        time.sleep(0.25)
    raise RuntimeError(f'The local print helper did not start. Check {ROOT / "bridge.log"}.')


def install():
    if not suitable_python():
        raise RuntimeError('Open Install.cmd to set up the required ARM64 Python.')
    ROOT.mkdir(parents=True, exist_ok=True)
    with (ROOT / 'setup.lock').open('a+b') as lock:
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise RuntimeError('Another Canon LBP2900 setup is already running.')
        pythonw = ensure_runtime().with_name('pythonw.exe')
        app = ROOT / 'app'
        app.mkdir(exist_ok=True)
        files_changed = False
        for src in (PACKAGE / 'app').iterdir():
            if src.is_file():
                dst = app / src.name
                if not dst.exists() or not filecmp.cmp(src, dst, shallow=False):
                    staged = dst.with_suffix(dst.suffix + '.new')
                    shutil.copyfile(src, staged)
                    staged.replace(dst)
                    files_changed = True
        ctypes.CDLL(str(app / 'hiscoa.dll'))
        env = dict(os.environ, CANON_PYTHONW=str(pythonw), CANON_APP_DIR=str(app))
        powershell(SHORTCUTS, env)
        env['CANON_PRINTER_UUID'], updated = ensure_helper(pythonw, app, env, files_changed)
        try:
            with queue_handle():
                pass
            env['CANON_NEEDS_STATUS_ACCESS'] = '0'
        except OSError:
            env['CANON_NEEDS_STATUS_ACCESS'] = '1'
        powershell(REGISTER, env)
        with queue_handle():
            pass
    if updated:
        print('Setup complete. Select Canon LBP2900 in the Windows print dialog.')
    else:
        print('Update installed. The previous helper is handling a connection or queued job.')
        print('The new helper starts at your next sign-in, or rerun Install.cmd when printing is idle.')


if __name__ == '__main__':
    if sys.argv[1:] == ['--probe']:
        sys.exit(0 if suitable_python() else 1)
    try:
        install()
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError, ipp.IppError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
