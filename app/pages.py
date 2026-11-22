# SPDX-License-Identifier: GPL-3.0-or-later
# Windows ARM64 adaptation, modified 2026-11-20.
"""Turn Windows spool PDFs into 600 dpi monochrome CAPT bands."""
import ctypes as c
from dataclasses import dataclass
from pathlib import Path

from PIL import Image
import pypdfium2 as pdfium
import pwg


@dataclass(frozen=True)
class Media:
    name: str
    code: int
    width: int
    height: int
    stride: int
    lines: int


# LBP2900/3000 standard media geometry, in 600 dpi device pixels.
MEDIA = (
    Media('A4', 0x02, 4960, 7014, 592, 6776),
    Media('Letter', 0x0D, 5100, 6600, 608, 6362),
    Media('Legal', 0x0C, 5100, 8400, 608, 8162),
    Media('A5', 0x03, 3496, 4960, 408, 4722),
    Media('JIS B5', 0x07, 4298, 6070, 508, 5832),
    Media('Executive', 0x0A, 4350, 6300, 516, 6062),
)
_codec = c.CDLL(str(Path(__file__).with_name('hiscoa.dll')))
_encode = _codec.encode_band
_encode.argtypes = (c.c_void_p, c.c_size_t, c.c_void_p, c.c_uint, c.c_uint)
_encode.restype = c.c_size_t


def select_media(w, h):
    short, long = sorted((w, h))
    if short <= 0 or long <= 0:
        raise ValueError('Invalid page dimensions.')
    return next((m for m in MEDIA if abs(short * 600/72 - m.width) < 20
                 and abs(long * 600/72 - m.height) < 20), MEDIA[0])


def pdf_images(path):
    with pdfium.PdfDocument(str(path)) as doc:
        if not len(doc):
            raise ValueError('The Windows print job contains no pages.')
        doc.init_forms()
        for index in range(len(doc)):
            page = doc[index]
            try:
                w, h = page.get_size()
                short, long = sorted((w, h))
                media = select_media(w, h)
                scale = min(media.width / short, media.height / long)
                bitmap = page.render(scale=scale, rotation=90 if w > h else 0, grayscale=True)
                try:
                    img = bitmap.to_pil().convert('L')
                finally:
                    bitmap.close()
            finally:
                page.close()
            yield media, img


def raster_images(path):
    for img, w, h in pwg.images(path):
        media = select_media(w, h)
        if w > h:
            img = img.transpose(Image.Transpose.ROTATE_270)
        factor = min(media.width / img.width, media.height / img.height)
        size = (round(img.width * factor), round(img.height * factor))
        if img.size != size:
            img = img.resize(size, Image.Resampling.LANCZOS)
        yield media, img


def pages(path):
    path = Path(path)
    images = raster_images(path) if path.suffix == '.pwg' else pdf_images(path)
    for media, img in images:
        if img.size != (media.width, media.height):
            sheet = Image.new('L', (media.width, media.height), 255)
            sheet.paste(img, ((media.width-img.width)//2, (media.height-img.height)//2))
            img.close()
            img = sheet
        left = (media.width - media.stride * 8) // 2
        top = (media.height - media.lines) // 2
        crop = img.crop((left, top, left + media.stride * 8, top + media.lines))
        img.close()
        # Conversion dithers grayscale. CAPT uses a set bit for black toner.
        mono = crop.convert('1')
        pixels = mono.tobytes('raw', '1;I')
        mono.close()
        crop.close()
        bands = []
        for row in range(0, media.lines, 70):
            rows = min(70, media.lines - row)
            data = pixels[row * media.stride:(row + rows) * media.stride]
            buf = c.create_string_buffer(len(data) * 2 + 16)
            size = _encode(buf, len(buf), data, media.stride, rows)
            if not 0 < size < len(buf):
                raise OSError('Hi-SCoA band encoding failed.')
            bands.append(buf.raw[:size])
        yield media, bands
