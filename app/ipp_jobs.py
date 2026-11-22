# SPDX-License-Identifier: GPL-3.0-or-later
# Windows ARM64 adaptation, modified 2026-11-20.
"""Durable IPP job IDs and outcomes. Print documents live in the spool directory."""
from contextlib import closing, contextmanager
import sqlite3
import time
import uuid
from spool import ROOT
from ipp_codec import IppError

DATABASE = ROOT / 'ipp-jobs.sqlite3'
MAX_UNFINISHED_JOBS = 100


@contextmanager
def database():
    with closing(sqlite3.connect(DATABASE, timeout=10)) as db:
        db.row_factory = sqlite3.Row
        with db:
            yield db


def initialize():
    with database() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL, state INTEGER NOT NULL DEFAULT 3,
            submitted INTEGER NOT NULL DEFAULT 0, message TEXT NOT NULL DEFAULT '',
            pages INTEGER NOT NULL DEFAULT 0, created INTEGER NOT NULL)''')
        db.execute("UPDATE jobs SET state=8, message='Document did not arrive' "
                   "WHERE state=3 AND submitted=0 AND created < ?", (int(time.time())-120,))


def new(name):
    key = f'{time.time_ns():020d}-{uuid.uuid4().hex[:8]}'
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute("UPDATE jobs SET state=8, message='Document did not arrive' "
                   "WHERE state=3 AND submitted=0 AND created < ?", (int(time.time())-120,))
        count = db.execute('SELECT COUNT(*) FROM jobs WHERE state IN (3,4,5)').fetchone()[0]
        if count >= MAX_UNFINISHED_JOBS:
            raise IppError(0x0507, 'The local print queue is full. Complete or cancel waiting jobs.')
        db.execute('DELETE FROM jobs WHERE state IN (7,8,9) AND id < '
                   '(SELECT COALESCE(MAX(id),0)-100 FROM jobs)')
        cursor = db.execute('INSERT INTO jobs(key,name,created) VALUES (?,?,?)',
                            (key, str(name)[:255], int(time.time())))
        return db.execute('SELECT * FROM jobs WHERE id=?', (cursor.lastrowid,)).fetchone()


def get(job_id):
    with database() as db:
        return db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()


def recent():
    with database() as db:
        return db.execute('SELECT * FROM jobs ORDER BY id DESC').fetchall()


def mark(key, state, message='', pages=0):
    with database() as db:
        db.execute('UPDATE jobs SET state=?, message=?, pages=?, submitted=1 WHERE key=?',
                   (state, str(message)[:250], pages, key))


def is_complete(key):
    with database() as db:
        return db.execute('SELECT 1 FROM jobs WHERE key=? AND state=9', (key,)).fetchone() is not None
