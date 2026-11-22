# SPDX-License-Identifier: GPL-3.0-or-later
# Windows ARM64 adaptation, modified 2026-11-20.
"""Build a ZIP from the reviewed release manifest."""
from pathlib import Path, PurePosixPath
import zipfile

from verify_release import ROOT, verify


def main():
    verify()
    files = (ROOT / 'release-files.txt').read_text(encoding='utf-8').splitlines()
    if len(files) != len(set(files)):
        raise ValueError('Duplicate release manifest entry.')
    destination = ROOT / 'dist/Canon-LBP2900-Windows-ARM64.zip'
    destination.parent.mkdir(exist_ok=True)
    temporary = destination.with_suffix('.zip.new')
    with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in files:
            relative = PurePosixPath(name)
            source = (ROOT / name).resolve(strict=True)
            if (relative.is_absolute() or '..' in relative.parts or
                    not source.is_relative_to(ROOT) or not source.is_file()):
                raise ValueError('Invalid release path ' + name)
            info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED if name.endswith('.whl') else zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, source.read_bytes())
    with zipfile.ZipFile(temporary) as archive:
        if archive.testzip():
            raise ValueError('Release ZIP failed its integrity check.')
    temporary.replace(destination)
    print('Created', destination.relative_to(ROOT).as_posix())


if __name__ == '__main__':
    main()
