# SPDX-License-Identifier: GPL-3.0-or-later
# Windows ARM64 adaptation, modified 2026-11-20.
"""Build the bundled ARM64 Hi-SCoA DLL from its included source."""
import argparse
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zig', default='zig', help='Path to Zig (tested with 0.15.2)')
    parser.add_argument('--output', type=Path, help='Override the output DLL path')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve() if args.output else root / 'app/hiscoa.dll'
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([args.zig, 'cc', '-target', 'aarch64-windows-gnu',
                    '-O2', '-shared', '-s', '-Icodec', 'codec/codec.c',
                    'codec/hiscoa-compress.c', 'codec/hiscoa-common.c',
                    '-o', str(output)], cwd=root, check=True)
    print('Built', output.name)


if __name__ == '__main__':
    main()
