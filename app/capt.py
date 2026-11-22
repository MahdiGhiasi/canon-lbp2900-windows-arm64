"""Canon LBP2900 CAPT job and status protocol. SPDX-License-Identifier: GPL-3.0-or-later

Based on captdriver by Alexey Galakhov and contributors. The transaction order
and live extended status follow the LBP2900 work in suluoniu/captdriver-lbp2900.
"""
from dataclasses import dataclass
from datetime import datetime
import logging
import struct
import time

log = logging.getLogger('canon')


def packet(command, data=b''):
    return struct.pack('<HH', command, 4 + len(data)) + data


@dataclass(frozen=True)
class Status:
    flags: int
    engine: int
    decoding: int
    printing: int
    out: int
    completed: int
    received: int

    @property
    def paper_out(self):
        return bool(self.flags & 2 or self.engine & 0x4000)


class Capt:
    def __init__(self, usb, report=lambda message: None):
        self.usb = usb
        self.report = report
        self.job = None
        self.last_status = None

    def exchange(self, cmd, data=b''):
        self.usb.send(packet(cmd, data))
        reply = self.usb.receive()
        if len(reply) < 6:
            raise OSError(f'Short CAPT response to {cmd:04X}.')
        echo, size = struct.unpack_from('<HH', reply)
        if echo != cmd or size < 6:
            raise OSError(f'Unexpected CAPT reply {echo:04X} to {cmd:04X}.')
        # Some CAPT firmware writes reply length in packed decimal.
        digits = format(size, '04x')
        bcd = int(digits) if digits.isdecimal() else -1
        while len(reply) != size:
            if len(reply) == bcd and len(reply) > 6:
                break
            if len(reply) > size:
                raise OSError('Oversized CAPT reply.')
            reply += self.usb.receive()
        return reply[4:]

    def status(self):
        data = self.exchange(0xA0A8)
        if len(data) < 36:
            raise OSError('Incomplete extended status from the Canon printer.')
        words = struct.unpack_from('<18H', data)
        state = Status(words[0], words[4], *words[7:11], words[17])
        if state != self.last_status:
            log.debug('USB status %s', state)
            self.last_status = state
        return state

    def until(self, predicate, label, seconds=45, allow_timeout=False):
        end = time.monotonic() + seconds
        paper_deadline = None
        while True:
            state = self.status()
            if state.paper_out:
                if paper_deadline is None:
                    self.report('Load paper in the Canon printer and press its paper button.')
                    paper_deadline = time.monotonic() + 600
                if time.monotonic() >= paper_deadline:
                    raise TimeoutError('The printer is still out of paper.')
            else:
                if paper_deadline is not None:
                    self.report('Printing')
                    end = time.monotonic() + seconds
                    paper_deadline = None
                if predicate(state):
                    return state
                if time.monotonic() >= end:
                    if allow_timeout:
                        return state
                    raise TimeoutError(f'The printer did not confirm {label}. Last status {state}.')
            time.sleep(0.12)

    def ready(self):
        return self.until(lambda s: not (s.flags & 0x80), 'readiness')

    def phase(self, flag, page):
        now = datetime.now().astimezone()
        west = -int(now.utcoffset().total_seconds() / 60)
        payload = bytearray(72)
        struct.pack_into('<H', payload, 4, page)
        struct.pack_into('<BBHhhH6B', payload, 16, flag, 1, self.job,
                         west, west, now.year - 1900, now.month - 1, now.day,
                         now.hour, now.minute, now.second, 1)
        self.exchange(0xE1A1, payload)

    def begin(self):
        self.exchange(0xA1A1)
        time.sleep(1)
        self.status()
        self.exchange(0xA3A2)
        result = self.exchange(0xA2A0, bytes.fromhex('00 00 1e 00 00 00 00 00'))
        self.job = struct.unpack_from('<H', result, 2)[0]
        self.exchange(0xE1A2, b'\x13' + bytes(15))
        self.ready()
        self.phase(1, 0)
        self.ready()
        log.info('Opened USB CAPT job %s', self.job)

    def print_page(self, media, bands):
        base = self.status()
        if base.flags & 0x30:
            for cmd in (0xE0A3, 0xE0A2, 0xE0A4):
                self.exchange(cmd)
            self.ready()
            self.exchange(0xE0A5, bytes.fromhex('ee db ea ad') + bytes(12))
            self.ready()
        self.until(lambda s: not s.flags & 4, 'space in the printer buffer')
        params = bytearray.fromhex('00 00 30 2a 00 00 00 00 1c 1c 1c 1c 00 11 04 00 01 01 02 00 00 00')
        params[4] = media.code
        params += struct.pack('<6H', 120, 96, media.stride, media.lines, media.width, media.height)
        params += bytes.fromhex('00 00 01 00 00 00')
        self.usb.send(packet(0xD0A9, packet(0xD0A0, params) +
                             packet(0xD0A4, bytes.fromhex('01 04 01 01 00 f9 00 00')) +
                             packet(0xD0A1) + packet(0xD0A2)))
        for i, band in enumerate(bands):
            if i and i % 16 == 0:
                self.ready()
            for pos in range(0, len(band), 0xFF00):
                self.usb.send(packet(0xC0A0, band[pos:pos + 0xFF00]))
        self.usb.send(packet(0xC0A4))
        received = self.until(lambda s: s.received == s.decoding and
                              (s.received != base.received or s.decoding != base.decoding),
                              'receipt of the page', 20)
        page = received.decoding
        self.phase(2, page)
        self.ready()
        self.exchange(0xE0A7, struct.pack('<H', page))
        self.ready()
        self.phase(6, page)
        log.info('Printer accepted page %s (%s, %s compressed bytes)', page,
                 media.name, sum(map(len, bands)))
        # Some firmware only updates the output counters after the end-of-job
        # handshake. Give the engine time, then check the hardware again in end().
        self.until(lambda s: s.out == page or s.out != base.out,
                   'page output', 14, allow_timeout=True)
        return page

    def end(self, page):
        state = self.until(lambda s: s.completed == page, 'page completion', 4, allow_timeout=True)
        self.phase(4, page)
        self.exchange(0xE0A9, struct.pack('<H', self.job))
        self.job = None
        if state.completed != page:
            state = self.until(lambda s: s.completed == page, 'the final page counter', 45)
        log.info('Printer confirmed completion of page %s (output %s, completed %s)',
                 page, state.out, state.completed)

    def abort(self):
        if self.job is None:
            return
        try:
            state = self.status()
            self.exchange(0xE1A2, bytes(12))
            self.phase(4, state.completed)
            self.exchange(0xE0A9, struct.pack('<H', self.job))
        except OSError:
            log.exception('The printer could not acknowledge job cleanup')
        self.job = None

    def print_document(self, rendered_pages):
        page = None
        try:
            for index, (media, bands) in enumerate(rendered_pages, 1):
                if self.job is None:
                    self.begin()
                self.report(f'Printing page {index} on {media.name}')
                page = self.print_page(media, bands)
            if page is None:
                raise ValueError('No printable pages.')
            self.end(page)
            return index
        except BaseException:
            self.abort()
            raise
