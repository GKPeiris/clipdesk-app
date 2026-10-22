#!/usr/bin/python3
"""Start the user service, then route a view request to its single GTK instance."""
import os
from pathlib import Path
import subprocess
import sys
from gi.repository import GLib
from clipdeck.desktop import start_service

ROOT = Path(__file__).resolve().parent

def main():
    args = sys.argv[1:]
    if any(a not in ('--full','--popup','--background') for a in args):
        print('Usage: clipdeck [--background | --popup | --full]', file=sys.stderr)
        return 2
    mode = '--full' if '--full' in args else '--popup' if '--popup' in args else '--background'
    service = os.environ.get('CLIPDECK_SERVICE', 'clipdeck.service' if str(ROOT) == '/usr/share/clipdeck' else 'clipdeck-local.service')
    started = False
    try:
        started = start_service(service)
    except (OSError, GLib.Error):
        pass
    command = ['/usr/bin/python3',str(ROOT/'run.py'),mode]
    if started:
        if mode != '--background': return subprocess.call(command)
        return 0
    # Desktops without a user systemd manager still get a detached resident app.
    subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)
    return 0

if __name__ == '__main__': raise SystemExit(main())
