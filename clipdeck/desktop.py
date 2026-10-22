"""GNOME shortcut integration. No system-wide settings or root privileges."""
import json
import os
from pathlib import Path
import shlex
import sys
from gi.repository import Gio

CUSTOM_PATH = '/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/clipdeck/'

def is_super_v(binding):
    return binding.lower().replace('<mod4>', '<super>') == '<super>v'


def popup_command():
    configured = os.environ.get('CLIPDECK_POPUP_COMMAND')
    if configured: return configured
    root = Path(__file__).resolve().parents[1]
    return shlex.join(['/usr/bin/python3', str(root/'launcher.py'), '--popup'])


def configure_shortcut(directory):
    source = Gio.SettingsSchemaSource.get_default()
    if not source or not source.lookup('org.gnome.settings-daemon.plugins.media-keys', True):
        return False
    media = Gio.Settings.new('org.gnome.settings-daemon.plugins.media-keys')
    shell = Gio.Settings.new('org.gnome.shell.keybindings')
    custom = Gio.Settings.new_with_path('org.gnome.settings-daemon.plugins.media-keys.custom-keybinding', CUSTOM_PATH)
    state_path = Path(directory)/'shortcut-backup.json'
    paths = list(media.get_strv('custom-keybindings'))
    backup = {'notification': list(shell.get_strv('toggle-message-tray')), 'conflicts': []}
    if state_path.exists():
        backup = json.loads(state_path.read_text())
    changes = []
    for path in paths:
        if path == CUSTOM_PATH: continue
        other = Gio.Settings.new_with_path('org.gnome.settings-daemon.plugins.media-keys.custom-keybinding', path)
        old = other.get_string('binding')
        if is_super_v(old):
            if not any(item['path'] == path for item in backup['conflicts']):
                backup['conflicts'].append({'path':path,'binding':old})
            changes.append(other)
    # Save before changing any bindings so the previous choices are recoverable.
    state_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(state_path, os.O_WRONLY|os.O_CREAT|os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f: json.dump(backup, f, indent=2)
    for other in changes: other.set_string('binding', '')
    current = list(shell.get_strv('toggle-message-tray'))
    shell.set_strv('toggle-message-tray', [binding for binding in current if not is_super_v(binding)])
    custom.set_string('name', 'ClipDeck clipboard')
    custom.set_string('command', popup_command())
    custom.set_string('binding', '<Super>v')
    if CUSTOM_PATH not in paths:
        media.set_strv('custom-keybindings', paths+[CUSTOM_PATH])
    Gio.Settings.sync()
    return True


def restore_shortcut(directory):
    path = Path(directory)/'shortcut-backup.json'
    if not path.exists(): return False
    backup = json.loads(path.read_text())
    media = Gio.Settings.new('org.gnome.settings-daemon.plugins.media-keys')
    custom = Gio.Settings.new_with_path('org.gnome.settings-daemon.plugins.media-keys.custom-keybinding', CUSTOM_PATH)
    if custom.get_string('name') != 'ClipDeck clipboard': return False
    media.set_strv('custom-keybindings', [p for p in media.get_strv('custom-keybindings') if p != CUSTOM_PATH])
    shell = Gio.Settings.new('org.gnome.shell.keybindings')
    current = list(shell.get_strv('toggle-message-tray'))
    for binding in backup['notification']:
        if is_super_v(binding) and binding not in current: current.append(binding)
    shell.set_strv('toggle-message-tray', current)
    for item in backup['conflicts']:
        other = Gio.Settings.new_with_path('org.gnome.settings-daemon.plugins.media-keys.custom-keybinding',item['path'])
        if not other.get_string('binding'): other.set_string('binding',item['binding'])
    Gio.Settings.sync()
    path.unlink()
    return True


def start_service(unit, restart=False, reload=False, timeout=15):
    """Use the session bus; this also works in desktop sandboxes with PID namespaces."""
    import time
    from gi.repository import GLib
    connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    def call(path, interface, method, parameters=None):
        return connection.call_sync('org.freedesktop.systemd1', path, interface, method,
                                    parameters, None, Gio.DBusCallFlags.NONE, 3000, None)
    manager = '/org/freedesktop/systemd1'
    if reload: call(manager, 'org.freedesktop.systemd1.Manager', 'Reload')
    call(manager, 'org.freedesktop.systemd1.Manager', 'RestartUnit' if restart else 'StartUnit', GLib.Variant('(ss)', (unit, 'replace')))
    path = call(manager, 'org.freedesktop.systemd1.Manager', 'GetUnit', GLib.Variant('(s)', (unit,))).unpack()[0]
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        state = call(path, 'org.freedesktop.DBus.Properties', 'Get', GLib.Variant('(ss)', ('org.freedesktop.systemd1.Unit','ActiveState'))).unpack()[0]
        if state == 'active': return True
        if state in ('failed','inactive'): return False
        time.sleep(.05)
    return False
