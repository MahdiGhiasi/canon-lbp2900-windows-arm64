# SPDX-License-Identifier: GPL-3.0-or-later
# Windows ARM64 adaptation, modified 2026-11-20.
"""Read monochrome PWG Raster (PWG 5102.4) one page at a time."""
import struct
from PIL import Image, ImageOps


def take(file, size):
    data = file.read(size)
    if len(data) != size:
        raise ValueError('Truncated PWG raster job.')
    return data


def images(path):
    with path.open('rb') as src:
        if take(src, 4) != b'RaS2':
            raise ValueError('Invalid PWG raster signature.')
        while first := src.read(1):
            header = first + take(src, 1795)
            xdpi, ydpi = struct.unpack_from('>II', header, 276)
            width, height = struct.unpack_from('>II', header, 372)
            bits, pixel_bits, stride, order, space = struct.unpack_from('>5I', header, 384)
            if (not 1 <= width <= 9000 or not 1 <= height <= 9000 or
                    width*height > 52_000_000 or not xdpi or not ydpi or order != 0 or
                    bits != pixel_bits or bits not in (1, 8) or space not in (0, 3, 18) or
                    stride != (width * bits + 7)//8):
                raise ValueError('Unsupported monochrome PWG page geometry.')
            blank = b'\x00' if space == 3 else b'\xff'
            raw = bytearray()
            rows = 0
            while rows < height:
                repeat = take(src, 1)[0] + 1
                line = bytearray()
                while len(line) < stride:
                    n = take(src, 1)[0]
                    if n == 128:
                        line.extend(blank * (stride - len(line)))
                    elif n < 128:
                        line.extend(take(src, 1) * (n + 1))
                    else:
                        line.extend(take(src, 257 - n))
                if len(line) != stride or rows + repeat > height:
                    raise ValueError('Invalid PWG raster line length or repeat count.')
                raw.extend(line * repeat)
                rows += repeat
            mode = '1' if bits == 1 else 'L'
            raster = Image.frombytes(mode, (width, height), bytes(raw)).convert('L')
            if space == 3:
                raster = ImageOps.invert(raster)
            yield raster, width / xdpi * 72, height / ydpi * 72
