# SPDX-License-Identifier: GPL-3.0-or-later
# Windows ARM64 adaptation, modified 2026-11-20.
"""On-disk queue shared by the Canon USB helper and its status window."""
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import threading
import time

ROOT = Path(os.environ['LOCALAPPDATA']) / 'CanonLBP2900'
JOBS = ROOT / 'jobs'
STATE = ROOT / 'status.json'
PORT = 16319
_status_lock = threading.Lock()

USB_MESSAGES = {
    'disconnected': ('shutdown-error', 'Offline. Turn on the Canon LBP2900 and connect its USB cable.'),
    'unresponsive': ('timed-out-error', 'Offline. The Canon LBP2900 is not responding over USB.'),
    'checking': ('other-error', 'Checking the Canon USB connection.'),
}


def move_job(path, stage, suffix=None):
    key = path.name.split('.')[0]
    return path.rename(JOBS / f'{key}.{stage}{suffix or path.suffix}')


def job_files(stage):
    return sorted([*JOBS.glob(f'*.{stage}.pdf'), *JOBS.glob(f'*.{stage}.pwg')])


def read_status():
    try:
        return json.loads(STATE.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def printer_status(state):
    usb = state.get('usb', 'checking')
    if usb in USB_MESSAGES:
        return USB_MESSAGES[usb]
    message = state.get('job_message', state.get('message', 'Ready'))
    if message.startswith(('Waiting for paper', 'Load paper')) or (usb == 'no-paper' and message == 'Ready'):
        return 'media-empty-error', 'Load paper in the Canon printer and press its paper button.'
    if message.startswith('Waiting for the printer'):
        return 'timed-out-error', message
    return 'none', message


def write_status(message, pages_completed=None):
    changes = {'job_message': message}
    if pages_completed is not None:
        changes['last_printed'] = datetime.now().astimezone().isoformat(timespec='seconds')
        changes['pages'] = pages_completed
    update_status(**changes)


def update_status(**changes):
    # The USB monitor and the print worker publish independently.
    with _status_lock:
        state = read_status()
        state.setdefault('job_message', state.get('message', 'Ready'))
        if (all(state.get(key) == value for key, value in changes.items())
                and state.get('message') == printer_status(state)[1]):
            return
        state.update(changes)
        state['message'] = printer_status(state)[1]
        state['changed_at'] = time.time()
        _save_status(state)


def _save_status(state):
    tmp = STATE.with_suffix('.new')
    # A status window or an indexer may briefly hold the destination open.
    # Progress reporting must never interrupt an active hardware transaction.
    for attempt in range(3):
        try:
            tmp.write_text(json.dumps(state), encoding='utf-8')
            tmp.replace(STATE)
            return
        except OSError:
            if attempt == 2:
                logging.getLogger('canon').warning('Could not update the status display')
            else:
                time.sleep(0.05)
