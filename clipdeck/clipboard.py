"""GTK clipboard transport, preserving multiple formats as one history entry."""
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gdk, Gio, GLib
from .store import MAX_ITEM

SENSITIVE = {'x-kde-passwordManagerHint', 'application/x-keepassxc-clipboard',
             'application/x-kde-passwordManagerHint', 'application/x-nspasteboard-concealed-type'}


class ClipboardMonitor:
    def __init__(self, callback, settings, error):
        self.clipboard = Gdk.Display.get_default().get_clipboard()
        self.callback, self.settings, self.error = callback, settings, error
        self.serial = 0
        self.cancel = None
        self.clipboard.connect('changed', self.capture)

    def capture(self, *_):
        self.serial += 1
        if self.cancel:
            self.cancel.cancel()
        if self.settings['paused'] or self.clipboard.is_local():
            return
        formats = set(self.clipboard.get_formats().get_mime_types())
        if {f.lower() for f in formats} & {f.lower() for f in SENSITIVE}:
            return
        self.cancel = Gio.Cancellable()
        token, cancel = self.serial, self.cancel
        wanted = []
        if self.settings['images'] and 'image/png' in formats:
            wanted.append('image/png')
        for mime in ('text/uri-list', 'text/html', 'text/plain;charset=utf-8', 'text/plain', 'UTF8_STRING'):
            if mime in formats and not (mime in ('text/plain', 'UTF8_STRING') and any(x.startswith('text/plain') for x in wanted)):
                wanted.append(mime)
        if 'text/uri-list' not in formats and 'x-special/gnome-copied-files' in formats:
            wanted.append('x-special/gnome-copied-files')
        collected = {}

        def next_format():
            if token != self.serial or cancel.is_cancelled():
                return
            if not wanted:
                if collected:
                    self.callback(collected)
                return
            mime = wanted.pop(0)
            self.clipboard.read_async([mime], GLib.PRIORITY_DEFAULT, cancel, opened, mime)

        def opened(clipboard, result, mime):
            try:
                stream, actual = clipboard.read_finish(result)
            except GLib.Error:
                next_format(); return
            chunks = bytearray()

            def received(source, res):
                try:
                    chunk = source.read_bytes_finish(res).get_data()
                    if token != self.serial or cancel.is_cancelled():
                        source.close(None); return
                    if len(chunks) + len(chunk) + sum(map(len, collected.values())) > MAX_ITEM:
                        source.close(None)
                        cancel.cancel()
                        self.error('Skipped an item larger than 8 MB')
                        return
                    if chunk:
                        chunks.extend(chunk)
                        source.read_bytes_async(65536, GLib.PRIORITY_DEFAULT, cancel, received)
                    else:
                        source.close(None)
                        key = 'text/plain' if mime.startswith('text/plain') or mime == 'UTF8_STRING' else mime
                        if mime == 'x-special/gnome-copied-files':
                            key = 'text/uri-list'
                            chunks[:] = b'\r\n'.join(bytes(chunks).splitlines()[1:])
                        if chunks:
                            collected[key] = bytes(chunks).rstrip(b'\0') if key.startswith('text/') else bytes(chunks)
                        next_format()
                except GLib.Error:
                    try:
                        source.close(None)
                    except GLib.Error:
                        pass
                    next_format()
            stream.read_bytes_async(65536, GLib.PRIORITY_DEFAULT, cancel, received)
        next_format()

    def copy(self, formats):
        providers = [Gdk.ContentProvider.new_for_bytes(key, GLib.Bytes.new(value)) for key, value in formats.items()]
        self.clipboard.set_content(Gdk.ContentProvider.new_union(providers))

    def clear(self):
        self.clipboard.set_content(None)
