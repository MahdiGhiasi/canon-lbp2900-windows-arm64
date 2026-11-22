# SPDX-License-Identifier: GPL-3.0-or-later
# Windows ARM64 adaptation, modified 2026-11-20.
"""Verify distributed binary hashes, wheel integrity and Python syntax."""
import hashlib
from pathlib import Path
import struct
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def verify():
    entries = {}
    for line in (ROOT / 'checksums.sha256').read_text(encoding='ascii').splitlines():
        digest, name = line.split('  ', 1)
        path = (ROOT / name).resolve(strict=True)
        if not path.is_relative_to(ROOT) or not path.is_file():
            raise ValueError('Checksum path leaves the repository.')
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != digest:
            raise ValueError('Binary checksum mismatch for ' + name)
        entries[name] = digest
    binaries = {p.relative_to(ROOT).as_posix()
                for folder in ('app', 'setup/wheels') for p in (ROOT / folder).iterdir()
                if p.is_file() and p.suffix in ('.dll', '.whl')}
    if set(entries) != binaries:
        raise ValueError('The checksum manifest must cover every distributed binary.')
    requirements = (ROOT / 'setup/requirements.txt').read_text(encoding='ascii')
    for name, digest in entries.items():
        if not name.endswith('.whl'):
            continue
        if digest not in requirements:
            raise ValueError('Wheel hash absent from pip requirements.')
        with zipfile.ZipFile(ROOT / name) as archive:
            if archive.testzip():
                raise ValueError('Corrupt wheel ' + name)
            if not any('license' in n.lower() for n in archive.namelist()):
                raise ValueError('Wheel has no embedded license notice.')
    dll = (ROOT / 'app/hiscoa.dll').read_bytes()
    offset = struct.unpack_from('<I', dll, 0x3c)[0]
    if dll[:2] != b'MZ' or dll[offset:offset+4] != b'PE\0\0' or struct.unpack_from('<H', dll, offset+4)[0] != 0xAA64:
        raise ValueError('The encoder DLL must be a Windows ARM64 binary.')
    for folder in (ROOT, ROOT / 'app', ROOT / 'scripts', ROOT / 'tests'):
        for path in folder.iterdir():
            if path.is_file() and path.suffix in ('.py', '.pyw'):
                compile(path.read_bytes(), path.relative_to(ROOT).as_posix(), 'exec')
    for name in ('Install.cmd', 'Uninstall.cmd'):
        batch = (ROOT / name).read_bytes()
        if b'\n' in batch.replace(b'\r\n', b''):
            raise ValueError(name + ' requires CRLF line endings.')
    print('Verified binary hashes, wheel licenses, ARM64 DLL, Python syntax and batch line endings.')


if __name__ == '__main__':
    verify()
