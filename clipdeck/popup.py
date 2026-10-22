"""Compact clipboard view. The main application's controls stay in its own window."""
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gtk, Gdk, GLib, Pango
from .store import decode_formats


class ClipboardPopup(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title='Clipboard', default_width=370, default_height=480, resizable=False)
        self.app = app
        self.had_focus = False
        self.item_ids = []
        self.add_css_class('clipboard-popup')
        self.set_hide_on_close(True)
        self.connect('close-request', self.close_popup)
        self.connect('notify::is-active', self.focus_changed)
        header = Gtk.HeaderBar(show_title_buttons=False)
        header.set_title_widget(Gtk.Label(label='Clipboard', css_classes=['popup-title']))
        close = Gtk.Button(icon_name='window-close-symbolic', tooltip_text='Close clipboard', css_classes=['flat'])
        close.connect('clicked', lambda *_: self.set_visible(False))
        header.pack_end(close)
        self.set_titlebar(header)
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root.append(Gtk.Label(label='Select to copy · Esc to close', xalign=0, css_classes=['popup-hint']))
        scroll = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.items = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, css_classes=['popup-items'])
        scroll.set_child(self.items)
        root.append(scroll)
        self.set_child(root)
        keys = Gtk.EventControllerKey()
        keys.connect('key-pressed', self.key_pressed)
        self.add_controller(keys)

    def key_pressed(self, controller, keyval, keycode, state):
        if keyval == Gdk.KEY_Escape:
            self.set_visible(False)
            return True
        return False

    def close_popup(self, *_):
        self.set_visible(False)
        return True

    def focus_changed(self, *_):
        if self.is_active():
            self.had_focus = True
        elif self.had_focus:
            self.set_visible(False)
            self.had_focus = False

    def show_history(self):
        self.had_focus = False
        self.refresh()
        self.present()
        first = self.items.get_first_child()
        if isinstance(first, Gtk.Button):
            first.grab_focus()

    def refresh(self):
        child = self.items.get_first_child()
        while child:
            following = child.get_next_sibling()
            self.items.remove(child)
            child = following
        rows = self.app.store.clipboard_items()
        self.item_ids = [row['id'] for row in rows]
        if not rows:
            empty = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, css_classes=['popup-empty'])
            empty.append(Gtk.Image(icon_name='edit-paste-symbolic', pixel_size=36))
            empty.append(Gtk.Label(label='Your clipboard is empty', css_classes=['popup-title']))
            empty.append(Gtk.Label(label='Copied text and images will appear here.', wrap=True, css_classes=['muted']))
            self.items.append(empty)
        for row in rows:
            tile = Gtk.Button(css_classes=['popup-item'], tooltip_text='Copy to clipboard')
            tile.connect('clicked', lambda _, item_id=row['id']: self.app.copy_item(item_id, from_popup=True))
            if row['kind'] == 'image':
                try:
                    data = decode_formats(self.app.store.get(row['id'])['payload'])['image/png']
                    texture = Gdk.Texture.new_from_bytes(GLib.Bytes.new(data))
                    picture = Gtk.Picture.new_for_paintable(texture)
                    picture.set_can_shrink(True)
                    picture.set_size_request(-1, 130)
                    picture.set_content_fit(Gtk.ContentFit.CONTAIN)
                    tile.set_child(picture)
                except GLib.Error:
                    tile.set_child(Gtk.Label(label='Image preview unavailable'))
            else:
                tile.set_child(Gtk.Label(label=row['preview'][:1800], xalign=0, wrap=True,
                                        wrap_mode=Pango.WrapMode.WORD_CHAR, lines=5,
                                        ellipsize=Pango.EllipsizeMode.END, css_classes=['popup-text']))
            self.items.append(tile)
