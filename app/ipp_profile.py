# SPDX-License-Identifier: GPL-3.0-or-later
# Windows ARM64 adaptation, modified 2026-11-20.
"""IPP attributes of the local USB LBP2900."""
import time
import uuid
import socket
import ipp_codec as p
from spool import printer_status

IPP_PORT = 16319
URI = f'ipp://127.0.0.1:{IPP_PORT}/ipp/print'
MODEL = 'Canon LBP2900'
HELPER_VERSION = 'CanonUSB/3'
DEVICE_UUID = uuid.uuid5(uuid.NAMESPACE_DNS, f'{socket.gethostname()}.canon-lbp2900.usb')
START = time.monotonic()
FORMATS = ['application/pdf', 'image/pwg-raster', 'application/octet-stream']
OPERATIONS = [p.OP_GET_PRINTER_ATTRIBUTES, p.OP_VALIDATE_JOB, p.OP_PRINT_JOB,
              p.OP_CREATE_JOB, p.OP_SEND_DOCUMENT, p.OP_GET_JOB_ATTRIBUTES,
              p.OP_GET_JOBS, p.OP_CANCEL_JOB, p.OP_CLOSE_JOB]
PAPERS = [('iso_a4_210x297mm', 21000, 29700), ('iso_a5_148x210mm', 14800, 21000),
          ('jis_b5_182x257mm', 18200, 25700), ('na_letter_8.5x11in', 21590, 27940),
          ('na_legal_8.5x14in', 21590, 35560), ('na_executive_7.25x10.5in', 18415, 26670)]


def uptime():
    return 1 + int(time.monotonic() - START)


def attributes(queued_jobs, printing, status):
    A = p.Attr
    I, E, B, K, T = p.TAG_INTEGER, p.TAG_ENUM, p.TAG_BOOLEAN, p.TAG_KEYWORD, p.TAG_TEXT
    C = p.TAG_BEGIN_COLLECTION
    sizes = [p.collection(x_dimension=(I, x), y_dimension=(I, y)) for _, x, y in PAPERS]
    media = [p.collection(media_size=(C, size), media_size_name=(K, name),
                          media_source=(K, 'main'), media_type=(K, 'stationery'),
                          media_left_margin=(I, 500), media_right_margin=(I, 500),
                          media_top_margin=(I, 500), media_bottom_margin=(I, 500))
             for (name, _, _), size in zip(PAPERS, sizes)]
    reason, message = printer_status(status)
    now = uptime()
    changed = max(1, now - max(0, int(time.time() - status.get('changed_at', time.time()))))
    features = [
        A(p.TAG_NAME, 'printer-name', [MODEL]), A(T, 'printer-info', [MODEL]),
        A(T, 'printer-make-and-model', [MODEL]), A(T, 'printer-location', ['USB on this PC']),
        A(T, 'printer-device-id', ['MFG:Canon;MDL:LBP2900;CMD:PDF,PWGRaster;CLS:PRINTER;DES:Canon LBP2900;']),
        A(p.TAG_URI, 'printer-uri-supported', [URI]),
        A(p.TAG_URI, 'printer-uuid', ['urn:uuid:' + str(DEVICE_UUID)]),
        A(K, 'uri-security-supported', ['none']), A(K, 'uri-authentication-supported', ['none']),
        A(E, 'printer-state', [5 if reason != 'none' else 4 if printing else 3]),
        A(K, 'printer-state-reasons', [reason]),
        A(T, 'printer-state-message', [message]),
        A(I, 'queued-job-count', [queued_jobs]), A(I, 'printer-up-time', [now]),
        A(I, 'printer-config-change-time', [1]), A(I, 'printer-state-change-time', [changed]),
        A(B, 'printer-is-accepting-jobs', [True]), A(K, 'printer-kind', ['document']),
        A(K, 'ipp-versions-supported', ['1.1', '2.0']),
        A(E, 'operations-supported', OPERATIONS),
        A(p.TAG_CHARSET, 'charset-configured', ['utf-8']), A(p.TAG_CHARSET, 'charset-supported', ['utf-8']),
        A(p.TAG_LANGUAGE, 'natural-language-configured', ['en']),
        A(p.TAG_LANGUAGE, 'generated-natural-language-supported', ['en']),
        A(p.TAG_MIME_TYPE, 'document-format-default', [FORMATS[0]]),
        A(p.TAG_MIME_TYPE, 'document-format-preferred', [FORMATS[0]]),
        A(p.TAG_MIME_TYPE, 'document-format-supported', FORMATS),
        A(K, 'compression-supported', ['none']), A(K, 'pdl-override-supported', ['attempted']),
        A(B, 'color-supported', [False]), A(K, 'print-color-mode-supported', ['monochrome']),
        A(K, 'print-color-mode-default', ['monochrome']),
        A(I, 'pages-per-minute', [12]), A(I, 'pages-per-minute-color', [0]),
        A(p.TAG_RESOLUTION, 'printer-resolution-default', [(600, 600, 3)]),
        A(p.TAG_RESOLUTION, 'printer-resolution-supported', [(600, 600, 3)]),
        A(p.TAG_RESOLUTION, 'pwg-raster-document-resolution-supported', [(600, 600, 3)]),
        A(K, 'pwg-raster-document-type-supported', ['sgray_8', 'black_1']),
        A(K, 'pwg-raster-document-sheet-back', ['normal']),
        A(K, 'sides-default', ['one-sided']), A(K, 'sides-supported', ['one-sided']),
        A(K, 'media-default', [PAPERS[0][0]]), A(K, 'media-ready', [PAPERS[0][0]]),
        A(K, 'media-supported', [name for name, _, _ in PAPERS]), A(C, 'media-size-supported', sizes),
        A(C, 'media-col-database', media), A(C, 'media-col-default', [media[0]]),
        A(C, 'media-col-ready', [media[0]]),
        A(K, 'media-col-supported', [a.name for a in media[0]]),
        A(K, 'media-source-default', ['main']), A(K, 'media-source-supported', ['main']),
        A(K, 'media-type-default', ['stationery']), A(K, 'media-type-supported', ['stationery']),
        A(K, 'output-bin-default', ['face-down']), A(K, 'output-bin-supported', ['face-down']),
        A(I, 'copies-default', [1]), A(p.TAG_RANGE, 'copies-supported', [(1, 1)]),
        A(E, 'print-quality-default', [4]), A(E, 'print-quality-supported', [4]),
        A(E, 'orientation-requested-default', [3]), A(E, 'orientation-requested-supported', [3, 4]),
        A(E, 'finishings-default', [3]), A(E, 'finishings-supported', [3]),
        A(I, 'number-up-default', [1]), A(I, 'number-up-supported', [1]),
        A(B, 'multiple-document-jobs-supported', [False]), A(I, 'multiple-operation-time-out', [60]),
        A(K, 'multiple-document-handling-default', ['separate-documents-collated-copies']),
        A(K, 'multiple-document-handling-supported', ['separate-documents-collated-copies']),
        A(K, 'which-jobs-supported', ['all', 'not-completed', 'completed']),
        A(K, 'job-creation-attributes-supported', ['media', 'media-col', 'sides', 'print-color-mode',
                                                  'printer-resolution', 'print-quality', 'copies']),
    ]
    features.extend(A(I, f'media-{side}-margin-supported', [500])
                    for side in ('left', 'right', 'top', 'bottom'))
    return features
