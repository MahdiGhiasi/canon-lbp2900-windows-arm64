# SPDX-License-Identifier: GPL-3.0-or-later
# Windows ARM64 adaptation, modified 2026-11-20.
"""Host the Windows IPP queue on loopback and deliver its documents over USB."""
import logging
from logging.handlers import RotatingFileHandler
import threading
import time

from capt import Capt
from pages import pages
from spool import JOBS, PORT, ROOT, job_files, move_job, read_status, update_status, write_status
from usbprinter import UsbPrinter, device_path
from ipp_server import Handler, Server
import ipp_jobs as ledger
from windows_queue import sync_offline

log = logging.getLogger('canon')
wake = threading.Event()
usb_lock = threading.Lock()


def monitor_usb():
    last_path = None
    state = 'checking'
    next_probe = next_sync = 0
    last_error = None
    while True:
        now = time.monotonic()
        previous = state
        try:
            path = device_path()
        except FileNotFoundError:
            path, state = None, 'disconnected'
        except OSError:
            path, state = None, 'unresponsive'
        else:
            if path != last_path:
                state, next_probe = 'checking', 0
            # PnP detects cable/power loss even during printing. The CAPT probe
            # also catches a nonresponding device and never shares a job's USB stream.
            if now >= next_probe and usb_lock.acquire(blocking=False):
                try:
                    with UsbPrinter(path, timeout_ms=1500) as usb:
                        state = 'no-paper' if Capt(usb).status().paper_out else 'online'
                except OSError:
                    state = 'unresponsive'
                finally:
                    usb_lock.release()
                next_probe = now + (12 if state == 'online' else 2)
        last_path = path
        update_status(usb=state)
        if state != previous:
            log.info('USB status: %s', state)
            wake.set()
        if state != 'checking' and (state != previous or now >= next_sync):
            try:
                sync_offline(state in ('disconnected', 'unresponsive'))
                last_error = None
            except (OSError, ValueError) as exc:
                if str(exc) != last_error:
                    log.info('Windows queue status update pending: %s', exc)
                    last_error = str(exc)
            next_sync = now + (4 if last_error else 10)
        time.sleep(2)


def print_next(pending):
    active = None
    key = pending.name.split('.')[0]
    try:
        with UsbPrinter() as usb:
            printer = Capt(usb, write_status)
            if printer.status().paper_out:
                write_status('Waiting for paper. Load the tray and press the paper button.')
                return False
            try:
                active = move_job(pending, 'active')
            except FileNotFoundError:  # Canceled from the status window.
                return True
            ledger.mark(key, 5)
            write_status('Preparing the print job')
            count = printer.print_document(pages(active))
            ledger.mark(key, 9, pages=count)
            active.unlink()
            active = None
            write_status('Ready', pages_completed=count)
            return True
    except Exception as exc:
        if active is None:
            write_status(f'Waiting for the printer. {exc}')
            return False
        log.exception('Print job paused')
        held = move_job(active, 'held')
        held.with_suffix('.txt').write_text(str(exc), encoding='utf-8')
        ledger.mark(key, 4, exc)
        write_status('Job held. Open Canon LBP2900 Print Status for details.')
        return True


def worker():
    while True:
        try:
            wake.clear()
            pending = job_files('pending')
            if pending and read_status().get('usb') == 'online':
                with usb_lock:
                    if print_next(pending[0]):
                        continue
            if not pending:
                msg = 'A job is held. Open Canon LBP2900 Print Status for details.'
                write_status(msg if job_files('held') else 'Ready')
            wake.wait(3)
        except Exception:
            log.exception('Print worker will retry')
            time.sleep(3)


def recover():
    for interrupted in job_files('active'):
        key = interrupted.name.split('.')[0]
        if ledger.is_complete(key):
            interrupted.unlink()
            continue
        held = move_job(interrupted, 'held')
        message = 'The helper stopped during printing.'
        held.with_suffix('.txt').write_text(message, encoding='utf-8')
        ledger.mark(key, 4, message)
    for part in JOBS.glob('*.part'):
        # Only files marked submitted in the database were fully flushed.
        key = part.name.split('.')[0]
        with ledger.database() as db:
            job = db.execute('SELECT submitted FROM jobs WHERE key=?', (key,)).fetchone()
        if job and job['submitted']:
            with part.open('rb') as file:
                suffix = '.pdf' if file.read(5) == b'%PDF-' else '.pwg'
            move_job(part, 'pending', suffix)
        else:
            part.unlink()


def serve():
    # Binding first makes startup and duplicate launches safe.
    try:
        server = Server(('127.0.0.1', PORT), Handler)
    except OSError as exc:
        if exc.winerror in (10048, 10013):
            return
        raise
    with server:
        JOBS.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(ROOT / 'bridge.log', maxBytes=512000,
                                      backupCount=2, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        log.addHandler(handler)
        log.setLevel(logging.INFO)
        ledger.initialize()
        recover()
        server.wake = wake
        update_status(usb='checking', job_message='Ready')
        threading.Thread(target=monitor_usb, daemon=True, name='Canon USB status').start()
        threading.Thread(target=worker, daemon=True, name='Canon USB').start()
        log.info('Canon LBP2900 monochrome IPP helper listening on 127.0.0.1:%d', PORT)
        server.serve_forever()


if __name__ == '__main__':
    serve()
