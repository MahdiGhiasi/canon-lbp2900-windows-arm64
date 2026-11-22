# SPDX-License-Identifier: GPL-3.0-or-later
# Windows ARM64 adaptation, modified 2026-11-20.
"""Local IPP endpoint for the inbox Windows IPP class driver."""
import http.server
import logging
import os
import shutil
import socket
import struct
import tempfile
import threading
import time
from pathlib import Path

import ipp_codec as p
import ipp_jobs as ledger
from ipp_profile import FORMATS, HELPER_VERSION, IPP_PORT, URI, attributes, uptime
from spool import JOBS, ROOT, job_files, move_job, read_status

log = logging.getLogger('canon')
delivery = threading.Lock()
MAX_REQUEST_BYTES = 256 * 1024 * 1024
MAX_CONNECTIONS = 16
REQUEST_TIMEOUT = 120
REASONS = {3: 'job-queued', 4: 'job-hold-until-specified', 5: 'job-printing',
           7: 'job-canceled-by-user', 8: 'aborted-by-system', 9: 'job-completed-successfully'}


def job_group(job):
    A = p.Attr
    state = job['state']
    reason = 'job-incoming' if state == 3 and not job['submitted'] else REASONS[state]
    return (p.TAG_JOB, [
        A(p.TAG_INTEGER, 'job-id', [job['id']]),
        A(p.TAG_URI, 'job-uri', [f"{URI}/{job['id']}"]), A(p.TAG_URI, 'job-printer-uri', [URI]),
        A(p.TAG_NAME, 'job-name', [job['name']]), A(p.TAG_ENUM, 'job-state', [state]),
        A(p.TAG_KEYWORD, 'job-state-reasons', [reason]),
        A(p.TAG_TEXT, 'job-state-message', [job['message'] or reason]),
        A(p.TAG_INTEGER, 'job-impressions-completed', [job['pages']]),
        A(p.TAG_INTEGER, 'job-printer-up-time', [uptime()]),
        A(p.TAG_INTEGER, 'time-at-creation', [max(1, uptime()-int(time.time())+job['created'])]),
    ])


def find_job(req):
    job_id = req.value('job-id')
    if job_id is None:
        tail = str(req.value('job-uri', '')).rsplit('/', 1)[-1]
        job_id = int(tail) if tail.isdecimal() and len(tail) < 12 else 0
    job = ledger.get(job_id)
    if job is None:
        raise p.IppError(p.STATUS_NOT_FOUND, 'Unknown print job')
    return job


def validate(req):
    fmt = req.value('document-format', 'application/octet-stream')
    if fmt not in FORMATS:
        raise p.IppError(p.STATUS_DOCUMENT_FORMAT_NOT_SUPPORTED, 'Unsupported document format')
    if req.value('copies', 1, p.TAG_JOB) != 1:
        raise p.IppError(0x040B, 'The host must render the requested copies.')
    if req.value('print-color-mode', 'monochrome', p.TAG_JOB) not in ('auto', 'monochrome'):
        raise p.IppError(0x040B, 'This is a monochrome printer.')


def submit(job, doc, wake):
    with delivery:
        current = ledger.get(job['id'])
        if current['state'] == 7:
            raise p.IppError(p.STATUS_NOT_POSSIBLE, 'The job was canceled')
        if current['submitted']:
            return current
        if current['state'] in (8, 9):
            raise p.IppError(p.STATUS_NOT_POSSIBLE, 'The job has already finished')
        start = doc.tell()
        sig = doc.read(5)
        doc.seek(start)
        suffix = '.pdf' if sig == b'%PDF-' else '.pwg' if sig.startswith(b'RaS2') else None
        if not suffix:
            ledger.mark(job['key'], 8, 'Unrecognized document format')
            raise p.IppError(p.STATUS_DOCUMENT_FORMAT_NOT_SUPPORTED, 'Expected a PDF or PWG raster job')
        if suffix == '.pdf':
            end = doc.seek(0, os.SEEK_END)
            doc.seek(max(start, end-1024))
            if b'%%EOF' not in doc.read():
                ledger.mark(job['key'], 8, 'Incomplete PDF document')
                raise p.IppError(p.STATUS_BAD_REQUEST, 'Incomplete PDF document')
            doc.seek(start)
        part = JOBS / (job['key'] + '.part')
        try:
            with part.open('wb') as out:
                shutil.copyfileobj(doc, out, length=1024*1024)
                out.flush()
                os.fsync(out.fileno())
            # Record the submission before publishing the file to the worker.
            # A crash between these operations is recovered from the .part file.
            ledger.mark(job['key'], 3)
            ready = move_job(part, 'pending', suffix)
        except Exception:
            ledger.mark(job['key'], 8, 'Could not spool the print document')
            part.unlink(missing_ok=True)
            raise
        log.info('Received IPP job %d (%s, %d bytes)', job['id'], suffix, ready.stat().st_size)
        wake.set()
        return ledger.get(job['id'])


def cancel(job):
    with delivery:
        current = ledger.get(job['id'])
        if current['state'] in (5, 7, 8, 9):
            raise p.IppError(p.STATUS_NOT_POSSIBLE, 'The job is already printing or finished')
        if current['submitted']:
            files = [x for x in JOBS.glob(job['key'] + '.*') if x.suffix in ('.pdf', '.pwg')]
            if not files or files[0].name.split('.')[1] not in ('pending', 'held'):
                raise p.IppError(p.STATUS_NOT_POSSIBLE, 'The job is already printing')
            try:
                files[0].unlink()
            except FileNotFoundError:
                raise p.IppError(p.STATUS_NOT_POSSIBLE, 'The job is already printing')
            files[0].with_suffix('.txt').unlink(missing_ok=True)
        ledger.mark(job['key'], 7, 'Canceled')


def dispatch(req, data, wake):
    if req.version not in ((1, 1), (2, 0)):
        raise p.IppError(p.STATUS_VERSION_NOT_SUPPORTED, 'Use IPP 1.1 or 2.0')
    op = req.operation
    if op == p.OP_GET_PRINTER_ATTRIBUTES:
        active = job_files('active')
        group = attributes(len(job_files('pending')) + len(active), bool(active), read_status())
        requested = req.group(p.TAG_OPERATION).get('requested-attributes')
        broad = {'all', 'printer-description', 'job-template', 'printer-status', 'media-col-database'}
        if requested and not broad.intersection(requested.values):
            group = [a for a in group if a.name in requested.values]
        return [(p.TAG_PRINTER, group)]
    if op == p.OP_GET_JOBS:
        which = req.value('which-jobs', 'not-completed')
        jobs = ledger.recent()
        if which != 'all':
            jobs = [j for j in jobs if (j['state'] in (7, 8, 9)) == (which == 'completed')]
        limit = req.value('limit', 0)
        return [job_group(j) for j in (jobs[:limit] if isinstance(limit, int) and limit > 0 else jobs)]
    if op in (p.OP_VALIDATE_JOB, p.OP_CREATE_JOB, p.OP_PRINT_JOB):
        validate(req)
        if op == p.OP_VALIDATE_JOB:
            return []
        job = ledger.new(req.value('job-name', 'Windows print job'))
        return [job_group(submit(job, data, wake) if op == p.OP_PRINT_JOB else job)]
    if op in (p.OP_SEND_DOCUMENT, p.OP_CANCEL_JOB, p.OP_GET_JOB_ATTRIBUTES, p.OP_CLOSE_JOB):
        job = find_job(req)
        if op == p.OP_SEND_DOCUMENT:
            validate(req)
            if not req.value('last-document', True):
                raise p.IppError(p.STATUS_NOT_POSSIBLE, 'Send all pages as one document')
            job = submit(job, data, wake)
        elif op == p.OP_CANCEL_JOB:
            cancel(job)
            return []
        return [job_group(job)]
    raise p.IppError(p.STATUS_OPERATION_NOT_SUPPORTED, 'Unsupported operation')


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, *args, **kwargs):
        self.connections = threading.BoundedSemaphore(MAX_CONNECTIONS)
        super().__init__(*args, **kwargs)

    def server_bind(self):
        if self.server_address[0] != '127.0.0.1':
            raise ValueError('The print helper must listen on IPv4 loopback.')
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def process_request(self, request, client_address):
        if not self.connections.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.connections.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.connections.release()


class RequestTooLarge(ValueError):
    pass


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version = HELPER_VERSION

    def log_message(self, *args):
        pass

    def setup(self):
        super().setup()
        self.connection.settimeout(REQUEST_TIMEOUT)

    def response(self, code, mime, body):
        self.send_response(code)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.response(200, 'text/plain; charset=utf-8', b'Canon LBP2900 / USB / monochrome / 600 dpi\n')

    def copy_bytes(self, dest, size):
        if dest.tell() + size > MAX_REQUEST_BYTES:
            raise RequestTooLarge('The print request exceeds 256 MiB.')
        while size:
            remaining = self.body_deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('The print request took too long.')
            self.connection.settimeout(remaining)
            block = self.rfile.read1(min(size, 1024*1024))
            if not block:
                raise ValueError('Truncated HTTP print request')
            if shutil.disk_usage(ROOT).free < len(block) + 64 * 1024 * 1024:
                raise p.IppError(0x0507, 'Insufficient free space for the print request.')
            dest.write(block)
            size -= len(block)

    def body_line(self, limit):
        line = bytearray()
        while len(line) < limit:
            remaining = self.body_deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('The print request took too long.')
            self.connection.settimeout(remaining)
            char = self.rfile.read(1)
            line.extend(char)
            if char in (b'', b'\n'):
                break
        return bytes(line)

    def read_body(self, dest):
        self.body_deadline = time.monotonic() + REQUEST_TIMEOUT
        lengths = self.headers.get_all('Content-Length', [])
        transfers = self.headers.get_all('Transfer-Encoding', [])
        if len(lengths) > 1 or len(transfers) > 1 or (lengths and transfers):
            raise ValueError('Ambiguous HTTP request framing.')
        if transfers and transfers[0].lower() != 'chunked':
            raise ValueError('Unsupported transfer encoding.')
        if not transfers:
            if not lengths:
                raise ValueError('Missing content length.')
            size = int(lengths[0])
            if size < 0:
                raise ValueError('Invalid HTTP content length')
            self.copy_bytes(dest, size)
            return
        while True:
            line = self.body_line(256)
            if not line.endswith(b'\r\n'):
                raise ValueError('Invalid HTTP chunk header')
            size = int(line.split(b';', 1)[0].strip(), 16)
            if size < 0:
                raise ValueError('Invalid HTTP chunk size')
            if size == 0:
                # Trailer fields are unused by IPP. Bound their total size.
                total = 0
                while total < 8192:
                    line = self.body_line(8192 - total)
                    if line == b'\r\n':
                        return
                    if not line or not line.endswith(b'\r\n'):
                        break
                    total += len(line)
                raise ValueError('Invalid or oversized HTTP trailers.')
            self.copy_bytes(dest, size)
            if self.rfile.read(2) != b'\r\n':
                raise ValueError('Invalid HTTP chunk ending')

    def do_POST(self):
        hosts = self.headers.get_all('Host', [])
        allowed = {'127.0.0.1', 'localhost',
                   f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
        if len(hosts) != 1 or hosts[0].lower() not in allowed or self.headers.get_content_type() != 'application/ipp':
            self.send_error(400)
            return
        if self.headers.get('Origin') or self.headers.get('Sec-Fetch-Site'):
            self.send_error(403, 'Browser requests are not supported.')
            return
        if self.path.split('?', 1)[0].rstrip('/') != '/ipp/print' and not self.path.startswith('/ipp/print/'):
            self.send_error(404)
            return
        version, code, request_id, message = (2, 0), p.STATUS_OK, 0, ''
        groups = []
        try:
            with tempfile.SpooledTemporaryFile(max_size=1024*1024, dir=ROOT) as incoming:
                self.read_body(incoming)
                incoming.seek(0)
                prefix = incoming.read(1024*1024)
                req = p.decode_request(prefix)
                version, request_id = req.version, req.request_id
                incoming.seek(len(prefix) - len(req.data))
                groups = dispatch(req, incoming, self.server.wake)
        except RequestTooLarge as exc:
            self.send_error(413, str(exc))
            return
        except TimeoutError:
            self.send_error(408, 'The print request took too long.')
            return
        except p.IppError as exc:
            code, message = exc.status, str(exc)
            self.close_connection = True
        except (ValueError, TypeError, IndexError, RecursionError, struct.error):
            code, message = p.STATUS_BAD_REQUEST, 'Invalid IPP request'
            self.close_connection = True
        except Exception:
            log.exception('IPP request failed')
            code, message = p.STATUS_INTERNAL_ERROR, 'The local print helper could not process the request'
            self.close_connection = True
        attrs = [p.Attr(p.TAG_CHARSET, 'attributes-charset', ['utf-8']),
                 p.Attr(p.TAG_LANGUAGE, 'attributes-natural-language', ['en'])]
        if message:
            attrs.append(p.Attr(p.TAG_TEXT, 'status-message', [message[:250]]))
        reply = p.encode_response(version, code, request_id, [(p.TAG_OPERATION, attrs)] + groups)
        self.response(200, 'application/ipp', reply)
