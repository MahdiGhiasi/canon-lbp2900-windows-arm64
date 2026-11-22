# SPDX-License-Identifier: GPL-3.0-or-later
# Windows ARM64 adaptation, modified 2026-11-20.
"""Show the local print queue and let the user manage jobs waiting for USB."""
from datetime import datetime
from pathlib import Path
import socket
import subprocess
import sys
import tkinter as tk
from tkinter import messagebox, ttk

from spool import PORT, job_files, move_job, printer_status, read_status
import ipp_jobs as ledger


def open_helper():
    try:
        with socket.create_connection(('127.0.0.1', PORT), timeout=0.5):
            return
    except OSError:
        pythonw = Path(sys.executable).with_name('pythonw.exe')
        subprocess.Popen([str(pythonw), '-E', '-s', str(Path(__file__).with_name('bridge.pyw'))],
                         creationflags=subprocess.CREATE_NO_WINDOW)


def job_label(path):
    timestamp, stage, _ = path.name.split('.')
    when = datetime.fromtimestamp(int(timestamp.split('-')[0]) / 1e9)
    label = {'active': 'Printing', 'held': 'Held', 'pending': 'Waiting'}[stage]
    return f'{when:%Y-%m-%d   %H:%M:%S}      {label}'


def refresh():
    state = read_status()
    message.set(printer_status(state)[1])
    if state.get('last_printed'):
        when = datetime.fromisoformat(state['last_printed']).strftime('%x %X')
        n = state['pages']
        last.set(f'Last completed: {when}   ({n} page{"s" if n != 1 else ""})')
    paths = sorted(job_files('active') + job_files('pending') + job_files('held'))
    if paths != shown:
        shown[:] = paths
        jobs.delete(0, tk.END)
        for path in paths:
            jobs.insert(tk.END, job_label(path))
        details.set('')
    selected()
    root.after(1200, refresh)


def selected(_event=None):
    selection = jobs.curselection()
    path = shown[selection[0]] if selection and selection[0] < len(shown) else None
    stage = path.name.split('.')[1] if path is not None else ''
    held = stage == 'held'
    waiting = stage == 'pending'
    retry.configure(state='normal' if held else 'disabled')
    cancel.configure(state='normal' if held or waiting else 'disabled')
    if held:
        try:
            details.set(path.with_suffix('.txt').read_text(encoding='utf-8'))
        except OSError:
            details.set('The previous print was interrupted.')
    else:
        details.set('')
    return path


def change_job(retry_it):
    path = selected()
    if path is None:
        return
    prompt = ('Print this job again from the first page?' if retry_it else
              'Remove this job from the local print queue?')
    if not messagebox.askyesno('Canon LBP2900', prompt, parent=root):
        return
    try:
        if retry_it:
            ledger.mark(path.name.split('.')[0], 3)
            move_job(path, 'pending')
        else:
            path.unlink()
            ledger.mark(path.name.split('.')[0], 7, 'Canceled')
        path.with_suffix('.txt').unlink(missing_ok=True)
    except FileNotFoundError:
        pass


if __name__ == '__main__':
    open_helper()
    root = tk.Tk()
    root.title('Canon LBP2900 Print Status')
    root.minsize(450, 285)
    frame = ttk.Frame(root, padding=16)
    frame.pack(fill='both', expand=True)
    message = tk.StringVar()
    last = tk.StringVar()
    details = tk.StringVar()
    ttk.Label(frame, textvariable=message, wraplength=450).pack(anchor='w')
    ttk.Label(frame, textvariable=last).pack(anchor='w', pady=(6, 12))
    ttk.Label(frame, text='Local print jobs').pack(anchor='w')
    jobs = tk.Listbox(frame, height=5, exportselection=False)
    jobs.pack(fill='both', expand=True, pady=(4, 6))
    jobs.bind('<<ListboxSelect>>', selected)
    ttk.Label(frame, textvariable=details, wraplength=450).pack(anchor='w')
    buttons = ttk.Frame(frame)
    buttons.pack(fill='x', pady=(8, 0))
    retry = ttk.Button(buttons, text='Retry', command=lambda: change_job(True))
    cancel = ttk.Button(buttons, text='Cancel job', command=lambda: change_job(False))
    retry.pack(side='left')
    cancel.pack(side='left', padx=6)
    ttk.Button(buttons, text='Close', command=root.destroy).pack(side='right')
    shown = []
    refresh()
    root.mainloop()
