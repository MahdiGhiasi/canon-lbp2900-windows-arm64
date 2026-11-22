# SPDX-License-Identifier: GPL-3.0-or-later
# Windows ARM64 adaptation, modified 2026-11-20.
"""Bounded Windows USBPRINT transfers for the Canon LBP2900."""
import ctypes as c
from ctypes import wintypes as w
import uuid


def api(dll, name, result, *args):
    proc = getattr(dll, name)
    proc.restype = result
    proc.argtypes = args
    return proc


class Overlapped(c.Structure):
    _fields_ = [('internal', c.c_size_t), ('count', c.c_size_t),
                ('offset', w.DWORD), ('offset_high', w.DWORD), ('event', w.HANDLE)]


k = c.WinDLL('kernel32', use_last_error=True)
cm = c.WinDLL('cfgmgr32')
pov = c.POINTER(Overlapped)
pdw = c.POINTER(w.DWORD)
open_file = api(k, 'CreateFileW', w.HANDLE, w.LPCWSTR, w.DWORD, w.DWORD,
                c.c_void_p, w.DWORD, w.DWORD, w.HANDLE)
close = api(k, 'CloseHandle', w.BOOL, w.HANDLE)
event = api(k, 'CreateEventW', w.HANDLE, c.c_void_p, w.BOOL, w.BOOL, w.LPCWSTR)
wait = api(k, 'WaitForSingleObject', w.DWORD, w.HANDLE, w.DWORD)
cancel = api(k, 'CancelIoEx', w.BOOL, w.HANDLE, pov)
result = api(k, 'GetOverlappedResult', w.BOOL, w.HANDLE, pov, pdw, w.BOOL)
read = api(k, 'ReadFile', w.BOOL, w.HANDLE, c.c_void_p, w.DWORD, pdw, pov)
write = api(k, 'WriteFile', w.BOOL, w.HANDLE, c.c_void_p, w.DWORD, pdw, pov)
ioctl = api(k, 'DeviceIoControl', w.BOOL, w.HANDLE, w.DWORD, c.c_void_p,
            w.DWORD, c.c_void_p, w.DWORD, pdw, pov)
list_size = api(cm, 'CM_Get_Device_Interface_List_SizeW', w.DWORD, pdw,
                c.c_void_p, w.LPCWSTR, w.DWORD)
list_paths = api(cm, 'CM_Get_Device_Interface_ListW', w.DWORD, c.c_void_p,
                 w.LPCWSTR, w.LPWSTR, w.DWORD, w.DWORD)
usbprint_guid = (c.c_ubyte * 16).from_buffer_copy(
    uuid.UUID('28d78fad-5a12-11d1-ae5b-0000f803a8c2').bytes_le)


def device_path():
    for _ in range(3):
        n = w.DWORD()
        if list_size(c.byref(n), usbprint_guid, None, 0):
            raise OSError('Windows could not enumerate USB printers.')
        buf = c.create_unicode_buffer(n.value)
        if list_paths(usbprint_guid, None, buf, n.value, 0):
            continue
        paths = [p for p in buf[:].split('\0')
                 if '#vid_04a9&pid_2676#' in p.lower()]
        if not paths:
            raise FileNotFoundError('Turn on the Canon LBP2900 and connect its USB cable.')
        if len(paths) > 1:
            raise OSError('More than one LBP2900 is connected.')
        return paths[0]
    raise OSError('USB printers changed during enumeration.')


class UsbPrinter:
    def __init__(self, path=None, timeout_ms=15000):
        self.path = path
        self.timeout_ms = timeout_ms

    def __enter__(self):
        self.handle = open_file(self.path or device_path(), 0xC0000000, 3, None, 3, 0x40000000, None)
        if self.handle == c.c_void_p(-1).value:
            raise c.WinError(c.get_last_error())
        return self

    def __exit__(self, *exc):
        close(self.handle)

    def _transfer(self, func, *args):
        op = Overlapped()
        op.event = event(None, True, False, None)
        if not op.event:
            raise c.WinError(c.get_last_error())
        count = w.DWORD()
        try:
            if not func(self.handle, *args, c.byref(count), c.byref(op)):
                err = c.get_last_error()
                if err != 997:  # ERROR_IO_PENDING
                    raise c.WinError(err)
                if wait(op.event, self.timeout_ms) != 0:
                    cancel(self.handle, c.byref(op))
                    result(self.handle, c.byref(op), c.byref(count), True)
                    raise TimeoutError('The Canon USB connection timed out.')
            if not result(self.handle, c.byref(op), c.byref(count), False):
                raise c.WinError(c.get_last_error())
            return count.value
        finally:
            close(op.event)

    def device_id(self):
        data = c.create_string_buffer(4096)
        n = self._transfer(ioctl, 0x00220034, None, 0, data, len(data))
        return data.raw[2:n].rstrip(b'\0').decode('ascii', 'replace')

    def send(self, data):
        for offset in range(0, len(data), 4096):
            chunk = data[offset:offset + 4096]
            if self._transfer(write, chunk, len(chunk)) != len(chunk):
                raise OSError('Incomplete write to the Canon printer.')

    def receive(self):
        data = c.create_string_buffer(4096)
        n = self._transfer(read, data, len(data))
        if not n:
            raise OSError('Empty response from the Canon printer.')
        return data.raw[:n]
