import St from 'gi://St';
import Meta from 'gi://Meta';
import Shell from 'gi://Shell';
import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

const APP = 'io.github.clipdeck.ClipDeck';
const IFACE = 'io.github.clipdeck.Bridge';
const PATH = '/io/github/clipdeck/Bridge';
const MAX_BYTES = 8 * 1024 * 1024;
const PRIVATE = new Set(['x-kde-passwordManagerHint', 'application/x-kde-passwordManagerHint', 'application/x-keepassxc-clipboard', 'application/x-nspasteboard-concealed-type']);
const XML = '<node><interface name="io.github.clipdeck.Shell"><method name="Paste"/><method name="PreparePopup"/></interface></node>';

export default class ClipDeckCompanion extends Extension {
    enable() {
        this._enabled = true;
        this._serial = 0;
        this._target = null;
        this._timeouts = new Set();
        this._clipboard = St.Clipboard.get_default();
        this._selection = global.display.get_selection();
        this._changed = this._selection.connect('owner-changed', (_selection, type) => {
            if (type === Meta.SelectionType.SELECTION_CLIPBOARD)
                this._capture();
        });
        this._indicator = new PanelMenu.Button(0.0, 'ClipDeck');
        this._indicator.add_child(new St.Icon({icon_name: 'edit-paste-symbolic', style_class: 'system-status-icon'}));
        const open = new PopupMenu.PopupMenuItem('Clipboard   Super+V');
        open.connect('activate', () => this._show());
        this._indicator.menu.addMenuItem(open);
        const full = new PopupMenu.PopupMenuItem('Open full application');
        full.connect('activate', () => this._call('Show', null, true));
        this._indicator.menu.addMenuItem(full);
        const pause = new PopupMenu.PopupMenuItem('Pause / resume clipboard history');
        pause.connect('activate', () => this._call('TogglePause'));
        this._indicator.menu.addMenuItem(pause);
        Main.panel.addToStatusArea(this.uuid, this._indicator);
        this._dbus = Gio.DBusExportedObject.wrapJSObject(XML, this);
        this._dbus.export(Gio.DBus.session, '/io/github/clipdeck/Shell');
        this._heartbeat = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 20, () => {
            this._call('Heartbeat');
            return GLib.SOURCE_CONTINUE;
        });
        this._call('Heartbeat');
    }

    _call(method, value = null, autoStart = false) {
        Gio.DBus.session.call(APP, PATH, IFACE, method,
            value === null ? null : new GLib.Variant('(s)', [value]), null,
            autoStart ? Gio.DBusCallFlags.NONE : Gio.DBusCallFlags.NO_AUTO_START,
            2000, null, (connection, result) => {
                try { connection.call_finish(result); } catch (_) { /* App may be closed. */ }
            });
    }

    PreparePopup() {
        const focus = global.display.focus_window;
        if (focus && !String(focus.get_wm_class()).toLowerCase().includes('clipdeck')) {
            this._target = focus;
            this._targetTime = GLib.get_monotonic_time();
        }
    }

    _show() {
        this.PreparePopup();
        this._call('ShowPopup', null, true);
        this._call('Heartbeat');
    }

    _capture() {
        const serial = ++this._serial;
        const type = St.ClipboardType.CLIPBOARD;
        const types = this._clipboard.get_mimetypes(type) || [];
        if (types.some(t => PRIVATE.has(t))) return;
        const wanted = ['image/png', 'text/uri-list', 'text/html'];
        const textType = ['text/plain;charset=utf-8', 'text/plain', 'UTF8_STRING'].find(t => types.includes(t));
        if (textType) wanted.push(textType);
        if (!types.includes('text/uri-list') && types.includes('x-special/gnome-copied-files'))
            wanted.push('x-special/gnome-copied-files');
        const selected = wanted.filter(t => types.includes(t));
        const payload = {};
        let size = 0;
        const next = () => {
            if (!this._enabled || serial !== this._serial) return;
            const mime = selected.shift();
            if (!mime) {
                if (Object.keys(payload).length) this._call('Capture', JSON.stringify(payload));
                return;
            }
            this._clipboard.get_content(type, mime, (_clipboard, bytes) => {
                if (!this._enabled || serial !== this._serial) return;
                if (bytes && bytes.get_size() > 0) {
                    size += bytes.get_size();
                    if (size > MAX_BYTES) return;
                    let key = mime.startsWith('text/plain') || mime === 'UTF8_STRING' ? 'text/plain' : mime;
                    let data = bytes.get_data();
                    if (mime === 'x-special/gnome-copied-files') {
                        key = 'text/uri-list';
                        const text = new TextDecoder().decode(data).split(/\r?\n/).slice(1).join('\r\n');
                        data = new TextEncoder().encode(text);
                    }
                    payload[key] = GLib.base64_encode(data);
                }
                next();
            });
        };
        next();
    }

    PasteAsync(_params, invocation) {
        const target = this._target;
        this._target = null;
        if (!target || GLib.get_monotonic_time() - this._targetTime > 300 * 1000000 ||
            !global.get_window_actors().some(a => a.meta_window === target)) {
            invocation.return_dbus_error('io.github.clipdeck.Error.NoTarget', 'Open ClipDeck using the global shortcut first.');
            return;
        }
        target.activate(global.get_current_time());
        const id = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 180, () => {
            this._timeouts.delete(id);
            if (!this._enabled || global.display.focus_window !== target) {
                invocation.return_dbus_error('io.github.clipdeck.Error.Focus', 'The destination window is no longer focused.');
                return GLib.SOURCE_REMOVE;
            }
            try {
                this._keyboard ??= Clutter.get_default_backend().get_default_seat().create_virtual_device(Clutter.InputDeviceType.KEYBOARD_DEVICE);
                const now = GLib.get_monotonic_time();
                this._keyboard.notify_keyval(now, Clutter.KEY_Control_L, Clutter.KeyState.PRESSED);
                this._keyboard.notify_keyval(now, Clutter.KEY_v, Clutter.KeyState.PRESSED);
                this._keyboard.notify_keyval(now, Clutter.KEY_v, Clutter.KeyState.RELEASED);
                this._keyboard.notify_keyval(now, Clutter.KEY_Control_L, Clutter.KeyState.RELEASED);
                invocation.return_value(null);
            } catch (error) {
                invocation.return_dbus_error('io.github.clipdeck.Error.Paste', error.message);
            }
            return GLib.SOURCE_REMOVE;
        });
        this._timeouts.add(id);
    }

    disable() {
        this._enabled = false;
        ++this._serial;
        this._selection?.disconnect(this._changed);
        if (this._heartbeat) GLib.Source.remove(this._heartbeat);
        for (const id of this._timeouts) GLib.Source.remove(id);
        this._timeouts.clear();
        this._dbus?.unexport();
        this._indicator?.destroy();
        this._indicator = this._dbus = this._settings = this._selection = this._clipboard = this._keyboard = this._target = null;
    }
}
