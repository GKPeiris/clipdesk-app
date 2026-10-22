import json
import os
from pathlib import Path
import sys
import time
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gdk, Gio, GLib, Gtk, Pango
from . import __version__
from .clipboard import ClipboardMonitor
from .popup import ClipboardPopup
from .store import Store, decode_formats, plain_html, MAX_ITEM

APP_ID = 'io.github.clipdeck.ClipDeck'
ROOT = Path(__file__).resolve().parent.parent
BRIDGE_XML = '''<node><interface name="io.github.clipdeck.Bridge">
<method name="Capture"><arg type="s" direction="in"/></method>
<method name="Show"/><method name="ShowPopup"/><method name="TogglePause"/><method name="Heartbeat"/>
<method name="Status"><arg type="s" direction="out"/></method>
</interface></node>'''
EMOJI = [('😀','grinning smile happy'),('😊','smile happy'),('😂','laugh tears joy'),('🥰','love hearts'),('😍','heart eyes'),('😎','cool sunglasses'),('🤔','thinking'),('😅','sweat smile'),('😢','sad cry'),('😭','cry tears'),('😮','surprise'),('🥳','party celebrate'),('👍','thumbs up yes'),('👎','thumbs down no'),('👏','clap applause'),('🙌','celebrate hands'),('🙏','thanks please pray'),('👋','wave hello'),('🤝','handshake'),('💪','strong muscle'),('❤️','red heart love'),('💜','purple heart'),('💙','blue heart'),('✨','sparkles'),('🔥','fire'),('⭐','star'),('✅','check done yes'),('❌','cross no error'),('⚠️','warning'),('💡','idea bulb'),('📌','pin'),('📋','clipboard'),('📝','note pencil'),('🚀','rocket launch'),('🎉','party celebration'),('🎯','target goal'),('☕','coffee'),('🌱','plant'),('🌍','earth world'),('🐧','penguin linux'),('©','copyright'),('®','registered'),('™','trademark'),('°','degree'),('→','arrow right'),('←','arrow left'),('✓','check'),('•','bullet'),('—','em dash'),('…','ellipsis'),('±','plus minus'),('×','multiply'),('÷','divide'),('∞','infinity'),('€','euro'),('£','pound')]


def label(text, css=None, **kwargs):
    w = Gtk.Label(label=text, **kwargs)
    if css: w.add_css_class(css)
    return w


def box(orientation=Gtk.Orientation.VERTICAL, spacing=0, css=None):
    w = Gtk.Box(orientation=orientation, spacing=spacing)
    if css: w.add_css_class(css)
    return w


def button(icon, tooltip, callback, css='flat'):
    w = Gtk.Button(icon_name=icon, tooltip_text=tooltip)
    w.add_css_class(css)
    w.connect('clicked', lambda *_: callback())
    return w


def age(stamp):
    seconds = max(0, time.time() - stamp)
    if seconds < 60: return 'Just now'
    if seconds < 3600: return f'{int(seconds // 60)}m ago'
    if seconds < 86400: return f'{int(seconds // 3600)}h ago'
    return f'{int(seconds // 86400)}d ago'


class ClipDeck(Gtk.Application):
    def __init__(self, directory=None, app_id=APP_ID):
        super().__init__(application_id=app_id, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.directory = directory or os.environ.get('CLIPDECK_DATA_DIR') or str(Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')) / 'clipdeck')
        self.window = None
        self.popup = None
        self.bridge_seen = 0
        self.tab = 'History'
        self.toast_timer = self.render_timer = 0
        self.filter_kind = 'all'
        self.add_main_option('full', 0, GLib.OptionFlags.NONE, GLib.OptionArg.NONE, 'Open the full application', None)
        self.add_main_option('popup', 0, GLib.OptionFlags.NONE, GLib.OptionArg.NONE, 'Open the compact clipboard', None)
        self.add_main_option('background', 0, GLib.OptionFlags.NONE, GLib.OptionArg.NONE, 'Start in the background', None)

    def do_startup(self):
        Gtk.Application.do_startup(self)
        os.umask(0o077)
        self.store = Store(self.directory)
        self.monitor = ClipboardMonitor(self.capture, self.store.settings, self.toast)
        self.hold()
        self.node_info = Gio.DBusNodeInfo.new_for_xml(BRIDGE_XML)
        self.connection = self.get_dbus_connection()
        self.bridge_registration = self.connection.register_object('/io/github/clipdeck/Bridge', self.node_info.interfaces[0], self.bridge_method, None, None)
        for name, callback in [('quit', self.quit), ('settings', self.settings_window), ('pause', self.toggle_pause), ('new', self.new_snippet), ('clear', self.confirm_clear), ('hide', self.hide_window), ('search', self.focus_search)]:
            action = Gio.SimpleAction.new(name, None)
            action.connect('activate', lambda a, p, cb=callback: cb())
            self.add_action(action)
        for name, keys in [('quit',['<Control>q']),('search',['<Control>f']),('new',['<Control>n']),('hide',['Escape']),('settings',['<Control>comma']),('pause',['<Control><Shift>p'])]:
            self.set_accels_for_action('app.' + name, keys)
        css = Gtk.CssProvider()
        css.load_from_path(str(ROOT / 'data/style.css'))
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.apply_theme()
        if self.get_application_id() == APP_ID and not os.environ.get('CLIPDECK_NO_SETUP'):
            from .desktop import configure_shortcut
            try:
                configure_shortcut(self.directory)
            except (GLib.Error, OSError, ValueError) as error:
                print(f'Could not configure Super+V: {error}', file=sys.stderr)
        self.monitor.capture()
        GLib.timeout_add_seconds(15, self.tick)

    def do_command_line(self, command_line):
        options = command_line.get_options_dict()
        if options.contains('full'): self.activate()
        elif options.contains('popup'): self.show_popup()
        return 0

    def do_activate(self):
        if self.popup: self.popup.set_visible(False)
        if self.window is None: self.build_window()
        self.window.present()
        self.monitor.capture()
        self.refresh()

    def do_shutdown(self):
        if hasattr(self, 'store'): self.store.close()
        Gtk.Application.do_shutdown(self)

    def apply_theme(self):
        Gtk.Settings.get_default().set_property('gtk-application-prefer-dark-theme', self.store.settings['theme'] == 'dark')

    def bridge_method(self, conn, sender, path, interface, method, parameters, invocation):
        try:
            if method == 'Capture':
                payload = parameters.unpack()[0]
                if len(payload) > MAX_ITEM * 1.5: raise ValueError('Payload too large')
                self.bridge_seen = time.monotonic()
                self.capture(decode_formats(payload))
            elif method == 'Heartbeat':
                self.bridge_seen = time.monotonic()
                self.update_status()
            elif method == 'Show': self.activate()
            elif method == 'ShowPopup': self.show_popup(remember=False)
            elif method == 'TogglePause': self.toggle_pause()
            elif method == 'Status':
                invocation.return_value(GLib.Variant('(s)', (json.dumps(dict(paused=self.store.settings['paused'], items=len(self.store.list()), version=__version__, full_visible=bool(self.window and self.window.get_visible()), popup_visible=bool(self.popup and self.popup.get_visible()))),)))
                return
            invocation.return_value(None)
        except (ValueError, TypeError, KeyError, UnicodeError) as error:
            invocation.return_dbus_error('io.github.clipdeck.Error.InvalidData', str(error))

    def show_popup(self, remember=True):
        if self.popup and self.popup.get_visible():
            self.popup.set_visible(False)
            return
        if remember and self.bridge_active():
            self.connection.call('org.gnome.Shell', '/io/github/clipdeck/Shell', 'io.github.clipdeck.Shell', 'PreparePopup', None, None, Gio.DBusCallFlags.NONE, 800, None, self.popup_prepared)
        else:
            self.present_popup()

    def popup_prepared(self, connection, result):
        try: connection.call_finish(result)
        except GLib.Error: pass
        self.present_popup()

    def present_popup(self):
        if self.popup is None: self.popup = ClipboardPopup(self)
        self.popup.show_history()
        self.monitor.capture()

    def bridge_active(self):
        return time.monotonic() - self.bridge_seen < 45

    def capture(self, formats):
        if self.store.settings['paused']: return
        if not self.store.settings['images']: formats = {k:v for k,v in formats.items() if k != 'image/png'}
        if not formats: return
        try:
            self.store.add(formats)
            self.schedule_refresh()
        except (ValueError, UnicodeError) as error: self.toast(str(error))

    def tick(self):
        self.store.prune()
        self.update_status()
        return True

    def build_window(self):
        self.window = Gtk.ApplicationWindow(application=self, title='ClipDeck')
        self.window.set_default_size(500, 760)
        self.window.set_size_request(420, 500)
        self.window.add_css_class('clipdeck')
        self.window.connect('close-request', self.close_request)
        header = Gtk.HeaderBar()
        brand = box(Gtk.Orientation.HORIZONTAL, 9)
        brand.append(label('▣', 'brand-icon'))
        brand.append(label('ClipDeck', 'brand'))
        header.set_title_widget(brand)
        header.pack_start(button('list-add-symbolic', 'Create a snippet · Ctrl+N', self.new_snippet))
        menu = Gio.Menu()
        for name, action in [('Preferences', 'app.settings'), ('Pause / resume capture', 'app.pause'), ('Clear history…', 'app.clear'), ('Quit ClipDeck', 'app.quit')]: menu.append(name, action)
        header.pack_end(Gtk.MenuButton(icon_name='open-menu-symbolic', menu_model=menu))
        self.window.set_titlebar(header)
        root = box()
        self.window.set_child(root)
        heading = box(spacing=7, css='heading')
        title_row = box(Gtk.Orientation.HORIZONTAL)
        title_row.append(label('Your clipboard,\nall together.', 'hero', xalign=0, hexpand=True))
        self.pause_button = button('media-playback-pause-symbolic', 'Pause recording', self.toggle_pause, 'pause-button')
        self.pause_button.set_valign(Gtk.Align.CENTER)
        title_row.append(self.pause_button)
        heading.append(title_row)
        heading.append(label('A little space for everything you copy.', 'muted', xalign=0))
        root.append(heading)
        tabs = box(Gtk.Orientation.HORIZONTAL, 4, 'tabs')
        self.tab_buttons = {}
        for name in ['History', 'Pinned', 'Emoji & symbols']:
            tab = Gtk.ToggleButton(label=name, hexpand=True)
            tab.connect('clicked', lambda b, n=name: self.change_tab(n))
            tabs.append(tab)
            self.tab_buttons[name] = tab
        self.tab_buttons['History'].set_active(True)
        root.append(tabs)
        search_row = box(Gtk.Orientation.HORIZONTAL, 8, 'search-row')
        self.search = Gtk.SearchEntry(hexpand=True, placeholder_text='Search your clipboard')
        self.search.connect('search-changed', lambda *_: self.schedule_refresh())
        self.search.connect('activate', lambda *_: self.copy_first())
        search_row.append(self.search)
        self.kind = Gtk.DropDown.new_from_strings(['All types', 'Text', 'Links', 'Images', 'Files'])
        self.kind.connect('notify::selected', self.change_kind)
        search_row.append(self.kind)
        root.append(search_row)
        summary = box(Gtk.Orientation.HORIZONTAL, css='summary-row')
        self.count_label = label('', 'eyebrow', xalign=0, hexpand=True)
        summary.append(self.count_label)
        clear = Gtk.Button(label='Clear history', css_classes=['flat', 'small-button'])
        clear.connect('clicked', lambda *_: self.confirm_clear())
        summary.append(clear)
        root.append(summary)
        scroll = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.content = box(spacing=10, css='history-list')
        scroll.set_child(self.content)
        root.append(scroll)
        self.toast_label = label('', 'toast', wrap=True)
        self.toast_label.set_visible(False)
        root.append(self.toast_label)
        footer = box(spacing=5, css='footer')
        foot_top = box(Gtk.Orientation.HORIZONTAL)
        self.status_label = label('', 'status', xalign=0, hexpand=True)
        foot_top.append(self.status_label)
        foot_top.append(button('emblem-system-symbolic', 'Preferences', self.settings_window))
        footer.append(foot_top)
        self.hint_label = label('', 'muted', xalign=0, wrap=True)
        footer.append(self.hint_label)
        root.append(footer)
        self.update_status()

    def change_tab(self, name):
        self.tab = name
        for title, widget in self.tab_buttons.items(): widget.set_active(title == name)
        self.kind.set_visible(name != 'Emoji & symbols')
        self.search.set_property('placeholder-text', 'Search emoji or symbols' if name == 'Emoji & symbols' else 'Search your clipboard')
        self.refresh()

    def change_kind(self, *_):
        self.filter_kind = ['all','text','link','image','files'][self.kind.get_selected()]
        self.refresh()

    def schedule_refresh(self):
        if (self.window or self.popup) and not self.render_timer: self.render_timer = GLib.timeout_add(100, self.refresh)

    def refresh(self):
        self.render_timer = 0
        if self.popup and self.popup.get_visible(): self.popup.refresh()
        if not self.window: return False
        child = self.content.get_first_child()
        while child:
            following = child.get_next_sibling()
            self.content.remove(child)
            child = following
        query = self.search.get_text().strip()
        if self.tab == 'Emoji & symbols':
            flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True, max_children_per_line=7, min_children_per_line=5, row_spacing=7, column_spacing=7)
            matches = [(e,n) for e,n in EMOJI if not query or query.lower() in n or query == e]
            for emoji, name in matches:
                tile = Gtk.Button(label=emoji, tooltip_text=name, css_classes=['emoji'])
                tile.connect('clicked', lambda b, e=emoji: self.copy_formats({'text/plain': e.encode()}))
                flow.append(tile)
            self.content.append(flow)
            self.count_label.set_text(f'{len(matches)} EMOJI & SYMBOLS')
            return False
        items = self.store.list(query, self.filter_kind, self.tab == 'Pinned')
        self.visible_ids = [r['id'] for r in items]
        self.count_label.set_text(f'{len(items)} {"PINNED" if self.tab == "Pinned" else "SAVED"} ITEM{"S" if len(items) != 1 else ""}')
        if not items:
            empty = box(spacing=14, css='empty-state')
            empty.append(label('⌘', 'empty-icon'))
            empty.append(label('Ready when you copy' if not query else 'No matches yet', 'empty-title'))
            empty.append(label('Copy text, links, images or files.\nThey’ll be here when you need them.' if not query else 'Try another search or change the type filter.', 'muted', justify=Gtk.Justification.CENTER, wrap=True))
            create = Gtk.Button(label='Create a snippet', halign=Gtk.Align.CENTER, css_classes=['suggested-action'])
            create.connect('clicked', lambda *_: self.new_snippet())
            empty.append(create)
            self.content.append(empty)
        for row in items: self.content.append(self.card(row))
        self.update_status()
        return False

    def card(self, row):
        card = box(spacing=8, css='clip-card')
        top = box(Gtk.Orientation.HORIZONTAL, 6)
        icons = {'text':'text-x-generic-symbolic','link':'insert-link-symbolic','image':'image-x-generic-symbolic','files':'folder-symbolic'}
        top.append(Gtk.Image.new_from_icon_name(icons[row['kind']]))
        title = row['title'] or {'text':'Text','link':'Link','image':'Image','files':'Files'}[row['kind']]
        top.append(label(title, 'card-type', xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END))
        top.append(label(age(row['used']), 'muted'))
        pin = button('starred-symbolic' if row['pinned'] else 'non-starred-symbolic', 'Unpin item' if row['pinned'] else 'Pin item', lambda: self.pin(row['id']))
        if row['pinned']: pin.add_css_class('pinned')
        top.append(pin)
        top.append(button('user-trash-symbolic', 'Delete item', lambda: self.delete(row['id'])))
        card.append(top)
        copy = Gtk.Button(css_classes=['preview-button'])
        copy.set_tooltip_text('Copy this item')
        copy.connect('clicked', lambda *_: self.copy_item(row['id']))
        if row['kind'] == 'image':
            try:
                formats = decode_formats(self.store.get(row['id'])['payload'])
                texture = Gdk.Texture.new_from_bytes(GLib.Bytes.new(formats['image/png']))
                picture = Gtk.Picture.new_for_paintable(texture)
                picture.set_can_shrink(True)
                picture.set_size_request(-1, 130)
                picture.set_content_fit(Gtk.ContentFit.CONTAIN)
                copy.set_child(picture)
            except GLib.Error: copy.set_child(label('Image preview unavailable', 'muted'))
        else:
            copy.set_child(label(row['preview'][:1600], 'preview', xalign=0, wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR, lines=4, ellipsize=Pango.EllipsizeMode.END))
        card.append(copy)
        bottom = box(Gtk.Orientation.HORIZONTAL, 5)
        bottom.append(label('Pinned · kept until removed' if row['pinned'] else f'{row["size"] / 1024:.1f} KB' if row['size'] >= 1024 else f'{row["size"]} bytes', 'muted', xalign=0, hexpand=True))
        if row['kind'] in ('text','link'):
            bottom.append(button('document-edit-symbolic', 'Edit as a new snippet', lambda: self.new_snippet(row['id'])))
            plain = Gtk.Button(label='Plain text', css_classes=['flat','small-button'])
            plain.connect('clicked', lambda *_: self.copy_item(row['id'], plain=True))
            bottom.append(plain)
        copy_btn = Gtk.Button(label='Copy', css_classes=['copy-button'])
        copy_btn.connect('clicked', lambda *_: self.copy_item(row['id']))
        bottom.append(copy_btn)
        card.append(bottom)
        return card

    def copy_first(self):
        if getattr(self, 'visible_ids', []) and self.tab != 'Emoji & symbols': self.copy_item(self.visible_ids[0])

    def copy_item(self, item_id, plain=False, from_popup=False):
        item = self.store.get(item_id)
        if not item: return
        formats = decode_formats(item['payload'])
        if plain:
            value = formats.get('text/plain') or plain_html(formats.get('text/html', b'').decode()).encode()
            formats = {'text/plain':value}
        self.copy_formats(formats, from_popup=from_popup)

    def copy_formats(self, formats, from_popup=False):
        self.monitor.copy(formats)
        try: self.store.add(formats)
        except ValueError as error: self.toast(str(error))
        self.schedule_refresh()
        self.toast('Copied — ready to paste')
        auto = self.store.settings['auto_paste'] and self.bridge_active()
        if from_popup:
            if self.popup: self.popup.set_visible(False)
        elif self.store.settings['hide_after_copy'] or auto:
            if self.window: self.window.set_visible(False)
        if auto:
            self.connection.call('org.gnome.Shell', '/io/github/clipdeck/Shell', 'io.github.clipdeck.Shell', 'Paste', None, None, Gio.DBusCallFlags.NONE, 2000, None, self.paste_done)

    def paste_done(self, connection, result):
        try: connection.call_finish(result)
        except GLib.Error:
            self.activate()
            self.toast('Copied. Switch to your app and press Ctrl+V.')

    def pin(self, item_id):
        self.store.pin(item_id)
        self.refresh()

    def delete(self, item_id):
        self.store.delete(item_id)
        self.refresh()
        self.toast('Item deleted')

    def toggle_pause(self):
        self.store.settings['paused'] = not self.store.settings['paused']
        self.store.save_settings()
        self.update_status()
        if not self.store.settings['paused']: self.monitor.capture()

    def update_status(self):
        if not self.window: return
        paused = self.store.settings['paused']
        self.pause_button.set_icon_name('media-playback-start-symbolic' if paused else 'media-playback-pause-symbolic')
        self.pause_button.set_tooltip_text('Resume recording' if paused else 'Pause recording')
        wayland = 'Wayland' in Gdk.Display.get_default().__class__.__name__
        self.status_label.set_text('Ⅱ  Capture paused' if paused else '●  Background capture connected' if self.bridge_active() else '●  Capture while focused' if wayland else '●  Clipboard ready · X11')
        self.hint_label.set_text('Super + V to open  ·  Esc to hide' if self.bridge_active() else 'GNOME Wayland: enable the bundled extension for background capture.' if wayland else 'Ctrl + F to search  ·  Enter to copy  ·  Esc to hide')

    def toast(self, message):
        if not self.window: return
        if self.toast_timer: GLib.source_remove(self.toast_timer)
        self.toast_label.set_text(message)
        self.toast_label.set_visible(True)
        def hide():
            self.toast_label.set_visible(False)
            self.toast_timer = 0
            return False
        self.toast_timer = GLib.timeout_add_seconds(5, hide)

    def focus_search(self):
        self.activate()
        self.search.grab_focus()

    def hide_window(self):
        if self.popup and self.popup.get_visible():
            self.popup.set_visible(False)
            return
        if self.window: self.window.set_visible(False)

    def close_request(self, *_):
        self.window.set_visible(False)
        return True

    def dialog(self, title, width=440):
        if not self.window: self.activate()
        dialog = Gtk.Window(title=title, transient_for=self.window, modal=True, default_width=width, resizable=False)
        content = box(spacing=16, css='dialog-content')
        dialog.set_child(content)
        return dialog, content

    def confirm_clear(self):
        dialog, content = self.dialog('Clear clipboard history')
        content.append(label('Make a fresh start?', 'empty-title', xalign=0))
        content.append(label('This permanently removes saved items. Pinned items stay unless you include them below.', wrap=True, xalign=0))
        include = Gtk.CheckButton(label='Also remove pinned items')
        system = Gtk.CheckButton(label='Also empty the current clipboard')
        content.append(include); content.append(system)
        actions = box(Gtk.Orientation.HORIZONTAL, 8)
        cancel = Gtk.Button(label='Cancel', hexpand=True)
        cancel.connect('clicked', lambda *_: dialog.close())
        confirm = Gtk.Button(label='Clear history', hexpand=True, css_classes=['destructive-action'])
        def clear(*_):
            self.store.clear(include.get_active())
            if system.get_active(): self.monitor.clear()
            dialog.close(); self.refresh(); self.toast('History cleared')
        confirm.connect('clicked', clear)
        actions.append(cancel); actions.append(confirm); content.append(actions)
        dialog.present()

    def new_snippet(self, item_id=None):
        dialog, content = self.dialog('New snippet', 480)
        content.append(label('Keep something useful.', 'empty-title', xalign=0))
        title = Gtk.Entry(placeholder_text='Name (optional)')
        content.append(title)
        text = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=12, bottom_margin=12, left_margin=12, right_margin=12)
        scroll = Gtk.ScrolledWindow(min_content_height=210)
        scroll.set_child(text); content.append(scroll)
        if item_id:
            row = self.store.get(item_id)
            title.set_text(row['title']); text.get_buffer().set_text(row['preview'])
        pin = Gtk.CheckButton(label='Pin this snippet', active=True)
        content.append(pin)
        error_label = label('', 'error', wrap=True); content.append(error_label)
        save = Gtk.Button(label='Save snippet', css_classes=['suggested-action'])
        def save_snippet(*_):
            buffer = text.get_buffer()
            value = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)
            if not value.strip(): error_label.set_text('Add some text first.'); return
            try: self.store.add({'text/plain':value.encode()}, pin.get_active(), title.get_text(), copied=False)
            except ValueError as error: error_label.set_text(str(error)); return
            dialog.close(); self.refresh()
        save.connect('clicked', save_snippet); content.append(save)
        dialog.present()

    def settings_window(self):
        dialog, content = self.dialog('ClipDeck preferences', 490)
        content.append(label('Make it yours.', 'empty-title', xalign=0))
        content.append(label('Local history. No account. No cloud connection.', 'muted', xalign=0))
        for key, title in [('images','Save copied images'),('hide_after_copy','Hide the panel after copying an item'),('auto_paste','Paste automatically via the GNOME shortcut')]:
            check = Gtk.CheckButton(label=title, active=self.store.settings[key])
            check.connect('toggled', lambda w, k=key: self.set_preference(k, w.get_active()))
            content.append(check)
        content.append(label('Automatic paste requires the extension and opening with Super+V.', 'muted', wrap=True, xalign=0))
        for key, title, low, high in [('limit','Unpinned history limit',10,500),('retention','Keep for days (0 = forever)',0,365)]:
            row = box(Gtk.Orientation.HORIZONTAL,12)
            row.append(label(title, xalign=0, hexpand=True))
            spin = Gtk.SpinButton.new_with_range(low,high,1); spin.set_value(self.store.settings[key])
            spin.connect('value-changed', lambda w, k=key: self.set_preference(k, w.get_value_as_int()))
            row.append(spin); content.append(row)
        dark = Gtk.CheckButton(label='Dark appearance', active=self.store.settings['theme']=='dark')
        dark.connect('toggled', lambda w: self.set_preference('theme','dark' if w.get_active() else 'light'))
        content.append(dark)
        auto = Gtk.CheckButton(label='Start ClipDeck when I sign in', active=self.store.settings['autostart'])
        auto.connect('toggled', self.change_autostart); content.append(auto)
        actions = box(Gtk.Orientation.HORIZONTAL,8)
        for name, export in [('Export history…',True),('Import history…',False)]:
            action = Gtk.Button(label=name,hexpand=True)
            action.connect('clicked', lambda b,e=export: self.choose_file(dialog,e)); actions.append(action)
        content.append(actions)
        content.append(label('Exports contain clipboard contents in readable form. History is local and unencrypted. Sensitive password-manager markers are respected when provided.', 'muted', wrap=True, xalign=0))
        content.append(label(f'ClipDeck {__version__}  ·  8 MB per item  ·  64 MB history\nGlobal shortcut: Super+V (GNOME extension)', 'muted', xalign=0, wrap=True))
        dialog.present()

    def set_preference(self, key, value):
        self.store.settings[key] = value
        self.store.save_settings()
        if key == 'theme': self.apply_theme()
        self.store.prune(); self.refresh()

    def change_autostart(self, widget):
        destination = Path(os.environ.get('XDG_CONFIG_HOME', Path.home()/'.config'))/'autostart/clipdeck.desktop'
        try:
            if widget.get_active():
                destination.parent.mkdir(parents=True, exist_ok=True)
                launcher = str(ROOT/'launcher.py').replace('\\','\\\\').replace('"','\\"').replace('`','\\`').replace('$','\\$').replace('%','%%')
                destination.write_text(f'[Desktop Entry]\nType=Application\nName=ClipDeck\nExec=/usr/bin/python3 "{launcher}" --background\nIcon={APP_ID}\nTerminal=false\nX-GNOME-Autostart-enabled=true\n')
            else: destination.unlink(missing_ok=True)
            self.set_preference('autostart',widget.get_active())
        except OSError as error: self.toast(f'Could not change startup: {error}')

    def choose_file(self, parent, export):
        chooser = Gtk.FileChooserNative(title='Export clipboard history' if export else 'Import clipboard history', transient_for=parent, action=Gtk.FileChooserAction.SAVE if export else Gtk.FileChooserAction.OPEN, accept_label='Export' if export else 'Import', cancel_label='Cancel')
        file_filter = Gtk.FileFilter(); file_filter.set_name('ClipDeck JSON exports'); file_filter.add_pattern('*.json'); chooser.add_filter(file_filter)
        if export: chooser.set_current_name('clipdeck-history.json')
        def respond(dialog,response):
            if response == Gtk.ResponseType.ACCEPT:
                try:
                    path = dialog.get_file().get_path()
                    if not path: raise ValueError('Choose a local file')
                    count = self.store.export_file(path) if export else self.store.import_file(path)
                    self.toast(f'{"Exported" if export else "Imported"} {count} items'); self.refresh()
                except (OSError,ValueError,TypeError,KeyError) as error: self.toast(f'Could not {"export" if export else "import"}: {error}')
            dialog.destroy()
        chooser.connect('response',respond); chooser.show()


def main():
    return ClipDeck().run(sys.argv)
