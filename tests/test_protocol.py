# SPDX-License-Identifier: GPL-3.0-or-later
# Windows ARM64 adaptation, modified 2026-11-20.
"""Protocol regression checks using a temporary spool and synthetic data."""
import http.client
from io import BytesIO
import os
from pathlib import Path
import socket
import struct
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

os.environ.setdefault('LOCALAPPDATA', tempfile.gettempdir())
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import ipp_codec as p
import ipp_jobs as ledger
import ipp_server
import spool


def message(operation, extra=(), data=b''):
    attrs = [p.Attr(p.TAG_CHARSET, 'attributes-charset', ['utf-8']),
             p.Attr(p.TAG_LANGUAGE, 'attributes-natural-language', ['en']),
             p.Attr(p.TAG_URI, 'printer-uri', ['ipp://127.0.0.1/ipp/print'])]
    attrs.extend(extra)
    return p.encode_response((2, 0), operation, 12, [(p.TAG_OPERATION, attrs)]) + data


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.patchers = [
            patch.object(spool, 'ROOT', root),
            patch.object(spool, 'STATE', root / 'status.json'),
            patch.object(spool, 'JOBS', root / 'jobs'),
            patch.object(ipp_server, 'ROOT', root),
            patch.object(ipp_server, 'JOBS', root / 'jobs'),
            patch.object(ledger, 'DATABASE', root / 'jobs.sqlite'),
        ]
        for patcher in self.patchers:
            patcher.start()
        spool.JOBS.mkdir()
        ledger.initialize()
        spool.update_status(usb='online', job_message='Ready')
        self.server = ipp_server.Server(('127.0.0.1', 0), ipp_server.Handler)
        self.server.wake = threading.Event()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp.cleanup()

    def request(self, body, headers=None, chunked=False):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=4)
        values = {'Content-Type': 'application/ipp'}
        values.update(headers or {})
        if chunked:
            body = iter([body[:11], body[11:]])
        conn.request('POST', '/ipp/print', body=body, headers=values, encode_chunked=chunked)
        response = conn.getresponse()
        data = response.read()
        conn.close()
        return response.status, data

    def test_online_offline_recovery(self):
        for usb, state in [('online', 3), ('disconnected', 5), ('unresponsive', 5), ('online', 3)]:
            with self.subTest(usb=usb):
                spool.update_status(usb=usb)
                code, data = self.request(message(p.OP_GET_PRINTER_ATTRIBUTES))
                response = p.decode_request(data)
                self.assertEqual(code, 200)
                self.assertEqual(response.value('printer-state', tag=p.TAG_PRINTER), state)
                self.assertFalse(response.value('color-supported', tag=p.TAG_PRINTER))
                self.assertTrue(response.value('printer-is-accepting-jobs', tag=p.TAG_PRINTER))

    def test_fixed_length_and_chunked_queries(self):
        for chunked in (False, True):
            with self.subTest(chunked=chunked):
                code, data = self.request(message(p.OP_GET_PRINTER_ATTRIBUTES), chunked=chunked)
                self.assertEqual((code, p.decode_request(data).operation), (200, p.STATUS_OK))

    def test_browser_and_foreign_host_rejected(self):
        for header in ({'Origin': 'https://example.invalid'},
                       {'Origin': 'null'}, {'Sec-Fetch-Site': 'cross-site'},
                       {'Host': 'example.invalid'}, {'Host': '127.0.0.1:16319:extra'}):
            with self.subTest(header=header):
                code, _ = self.request(message(p.OP_CREATE_JOB), header)
                self.assertIn(code, (400, 403))
                self.assertEqual(len(ledger.recent()), 0)

    def test_body_limits_in_both_framings(self):
        request = message(p.OP_GET_PRINTER_ATTRIBUTES)
        with patch.object(ipp_server, 'MAX_REQUEST_BYTES', 12):
            for chunked in (False, True):
                code, _ = self.request(request, chunked=chunked)
                self.assertEqual(code, 413)

    def test_ambiguous_length_closes_connection(self):
        body = message(p.OP_CREATE_JOB)
        code, data = self.request(body, {'Transfer-Encoding': 'chunked',
                                       'Content-Length': str(len(body))})
        self.assertEqual(code, 200)
        self.assertEqual(p.decode_request(data).operation, p.STATUS_BAD_REQUEST)
        self.assertEqual(len(ledger.recent()), 0)

    def test_incomplete_request_times_out(self):
        with patch.object(ipp_server, 'REQUEST_TIMEOUT', 0.2):
            conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
            conn.putrequest('POST', '/ipp/print')
            conn.putheader('Content-Type', 'application/ipp')
            conn.putheader('Content-Length', '100')
            conn.endheaders(b'\x02')
            response = conn.getresponse()
            self.assertEqual(response.status, 408)
            response.read()
            conn.close()

    def test_malformed_integer_is_bad_request(self):
        bad = struct.pack('>BBHI', 2, 0, p.OP_CREATE_JOB, 12)
        bad += bytes([p.TAG_OPERATION, p.TAG_INTEGER])
        bad += struct.pack('>H', 5) + b'limit' + struct.pack('>H', 1) + b'\x01' + bytes([p.TAG_END])
        code, data = self.request(bad)
        self.assertEqual((code, p.decode_request(data).operation), (200, p.STATUS_BAD_REQUEST))

    def test_queue_full_and_canceled_submission(self):
        with patch.object(ledger, 'MAX_UNFINISHED_JOBS', 2):
            first = ledger.new('Synthetic A')
            ledger.new('Synthetic B')
            code, data = self.request(message(p.OP_CREATE_JOB))
            self.assertEqual((code, p.decode_request(data).operation), (200, 0x0507))
            ipp_server.cancel(first)
            third = ledger.new('Synthetic C')
            self.assertGreater(third['id'], first['id'])
            with self.assertRaises(p.IppError):
                ipp_server.submit(first, BytesIO(b'%PDF-1.7\n%%EOF\n'), self.server.wake)
            self.assertEqual(list(spool.JOBS.iterdir()), [])

    def test_waiting_document_can_be_canceled_offline(self):
        spool.update_status(usb='disconnected')
        code, data = self.request(message(p.OP_PRINT_JOB,
                                          data=b'%PDF-1.7\n% synthetic test document\n%%EOF\n'))
        response = p.decode_request(data)
        self.assertEqual((code, response.operation), (200, p.STATUS_OK))
        job_id = response.value('job-id', tag=p.TAG_JOB)
        self.assertEqual(len(spool.job_files('pending')), 1)
        code, data = self.request(message(p.OP_CANCEL_JOB, [p.Attr(p.TAG_INTEGER, 'job-id', [job_id])]))
        self.assertEqual((code, p.decode_request(data).operation), (200, p.STATUS_OK))
        self.assertEqual(ledger.get(job_id)['state'], 7)
        self.assertEqual(list(spool.JOBS.iterdir()), [])

    def test_loopback_binding_required(self):
        with self.assertRaises(ValueError):
            ipp_server.Server(('0.0.0.0', 0), ipp_server.Handler)

    def test_connection_limit_recovers(self):
        # Occupy the single slot, reject another connection, then reuse the slot.
        with patch.object(ipp_server, 'MAX_CONNECTIONS', 1):
            limited = ipp_server.Server(('127.0.0.1', 0), ipp_server.Handler)
        limited.wake = threading.Event()
        thread = threading.Thread(target=limited.serve_forever, daemon=True)
        thread.start()
        try:
            limited.connections.acquire()
            rejected = socket.create_connection(limited.server_address)
            rejected.settimeout(2)
            rejected.sendall(b'GET / HTTP/1.0\r\n\r\n')
            try:
                self.assertEqual(rejected.recv(512), b'')
            except ConnectionResetError:
                pass
            rejected.close()
            limited.connections.release()
            conn = http.client.HTTPConnection(*limited.server_address, timeout=2)
            conn.request('GET', '/')
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            response.read()
            conn.close()
        finally:
            limited.shutdown()
            limited.server_close()
            thread.join(timeout=3)


if __name__ == '__main__':
    unittest.main()
