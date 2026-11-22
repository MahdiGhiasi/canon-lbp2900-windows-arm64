# SPDX-License-Identifier: GPL-3.0-or-later
# Windows ARM64 adaptation, modified 2026-11-20.
"""Publish USB availability to the Windows queue used by application print dialogs."""
from contextlib import contextmanager
import ctypes as c
from ctypes import wintypes as w
import uuid
import winreg

from ipp_profile import DEVICE_UUID, MODEL, URI

PRINTER_ACCESS_USE = 0x8
PRINTER_ACCESS_ADMINISTER = 0x4
PRINTER_STATUS_OFFLINE = 0x80
PRINTER_STATUS_PAUSED = 0x1
PRINTER_STATUS_PENDING_DELETION = 0x4
PRINTER_ATTRIBUTE_WORK_OFFLINE = 0x400


class PrinterDefaults(c.Structure):
    _fields_ = [('datatype', w.LPWSTR), ('devmode', c.c_void_p), ('access', w.DWORD)]


class PrinterInfo5(c.Structure):
    _fields_ = [('name', w.LPWSTR), ('port', w.LPWSTR), ('attributes', w.DWORD),
                ('device_timeout', w.DWORD), ('transmit_timeout', w.DWORD)]


spooler = c.WinDLL('winspool.drv', use_last_error=True)
spooler.OpenPrinterW.argtypes = [w.LPWSTR, c.POINTER(w.HANDLE), c.POINTER(PrinterDefaults)]
spooler.ClosePrinter.argtypes = [w.HANDLE]
spooler.GetPrinterW.argtypes = [w.HANDLE, w.DWORD, c.c_void_p, w.DWORD, c.POINTER(w.DWORD)]
spooler.SetPrinterW.argtypes = [w.HANDLE, w.DWORD, c.c_void_p, w.DWORD]


@contextmanager
def queue_handle():
    handle = w.HANDLE()
    defaults = PrinterDefaults(None, None, PRINTER_ACCESS_USE | PRINTER_ACCESS_ADMINISTER)
    if not spooler.OpenPrinterW(MODEL, c.byref(handle), c.byref(defaults)):
        raise c.WinError(c.get_last_error())
    try:
        yield handle
    finally:
        spooler.ClosePrinter(handle)


def printer_info(handle, level):
    size = w.DWORD()
    spooler.GetPrinterW(handle, level, None, 0, c.byref(size))
    if not size.value:
        raise c.WinError(c.get_last_error())
    data = c.create_string_buffer(size.value)
    if not spooler.GetPrinterW(handle, level, data, len(data), c.byref(size)):
        raise c.WinError(c.get_last_error())
    return data


def is_bridge_port(port):
    if port in (URI, URI.replace('ipp:', 'http:', 1)):
        return True
    if not port or not port.startswith('WSD-'):
        return False
    key = r'SYSTEM\CurrentControlSet\Control\Print\Monitors\WSD Port\Ports' + '\\' + port
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as opened:
        value = winreg.QueryValueEx(opened, 'Printer UUID')[0]
    return uuid.UUID(value) == DEVICE_UUID


def sync_offline(offline):
    with queue_handle() as handle:
        details = PrinterInfo5.from_buffer(printer_info(handle, 5))
        if not is_bridge_port(details.port):
            raise OSError('The named Windows queue belongs to a different printer.')
        if details.attributes & PRINTER_ATTRIBUTE_WORK_OFFLINE:
            return  # Preserve an explicit "Use Printer Offline" selection.
        status = w.DWORD.from_buffer(printer_info(handle, 6))
        if status.value & (PRINTER_STATUS_PAUSED | PRINTER_STATUS_PENDING_DELETION):
            return
        if bool(status.value & PRINTER_STATUS_OFFLINE) != offline:
            if offline:
                status.value |= PRINTER_STATUS_OFFLINE
            else:
                status.value &= ~PRINTER_STATUS_OFFLINE
            if not spooler.SetPrinterW(handle, 6, c.byref(status), 0):
                raise c.WinError(c.get_last_error())
