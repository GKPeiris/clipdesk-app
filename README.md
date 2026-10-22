# ClipDeck 1.0

A native Linux clipboard manager with a compact Windows-inspired history panel.
Python + GTK 4, with an optional GNOME Shell companion. All history stays local.

## Install

Ubuntu 24.04 or newer (GTK 4.8+, Python 3.10+):

```sh
sudo apt install ./clipdeck_1.0.0-1_all.deb
```

Fedora with GTK 4.8+ (Fedora 40 or newer recommended):

```sh
sudo dnf install ./clipdeck-1.0.0-1.noarch.rpm
```

Open **ClipDeck** from the applications menu or run `clipdeck`.
Packages are architecture independent, unsigned local builds. Package managers
resolve their GTK and Python dependencies from your configured repositories.
No Python packages from pip are required.

## GNOME Wayland background capture and global shortcut

The packages include the companion in
`/usr/share/gnome-shell/extensions/clipdeck@local`. On GNOME 45–50, log out and
back in after installing, then run:

```sh
gnome-extensions enable clipdeck@local
```

Open ClipDeck at least once. The panel footer says **Background capture connected**
when the companion is connected. Press **Super+Shift+V** to open the history,
or use its clipboard icon in the GNOME top panel. Super+V is already used by
GNOME's notification tray, so it is not overridden.

For a source installation you can install the separate extension archive:

```sh
gnome-extensions install --force clipdeck-companion.zip
```

The source app must be running; packaged installations also support DBus
activation from the extension. For source-only use, open the app normally once
before using the shortcut. Logging out may be necessary before enabling a new
extension. GNOME 44 and earlier and GNOME 51+ are not declared compatible.

Change the shortcut (example):

```sh
gsettings --schemadir /usr/share/gnome-shell/extensions/clipdeck@local/schemas set org.gnome.shell.extensions.clipdeck show-clipboard "['<Super><Shift>v']"
```

The companion reads clipboard content only to forward it to the running app.
It does not start the app just because you copy something. Enable **Start ClipDeck
when I sign in** in Preferences for continuous history after login.

## Features

- Searchable, persistent clipboard history with duplicate detection.
- Text, links, rich HTML + plain text, PNG images, and copied file URI references.
- Copy an old item back to the clipboard, or copy rich text as plain text.
- Pinned items, editable reusable snippets, and a searchable emoji/symbol picker.
- Individual deletion; clear history with an option to retain pinned items.
- Capture pause/resume, image capture toggle, history count and age limits.
- JSON import/export, dark/light appearance, background operation, and autostart.
- GNOME panel indicator and global shortcut through the companion.
- Optional automatic Ctrl+V into the previous window when opened with the GNOME
  shortcut. Off by default. Otherwise select an item, return to your app, and paste.

Keyboard: Ctrl+F search, Enter copy first result, Ctrl+N new snippet,
Ctrl+, preferences, Ctrl+Shift+P pause/resume, Esc hide, Ctrl+Q quit.
Closing the window keeps it running by default; choose Quit to stop capture.

## Platform limits and privacy

On X11, the app monitors clipboard changes while in the background. On native
GNOME Wayland, enable the companion for background history; without it, GTK can
only access clipboard data when the compositor permits, usually while focused.
Other Wayland desktops have the same focus limitation in this version; the
GNOME extension does not run on KDE/Sway. XWayland availability depends on the
compositor and is not a substitute for the native GNOME bridge.

This is a local clipboard utility. It does not include Windows cloud sync,
Microsoft account integration, online GIF search, or a proprietary Windows UI.
File history stores references, not file contents; files must still exist when
pasted. File cut operations are restored as copied references, not destructive
moves. PNG is the supported image format. HTML is preserved but never executed
or rendered as a webpage. Primary/middle-click selection is not recorded.

History is unencrypted SQLite, stored in `$XDG_DATA_HOME/clipdeck` (normally
`~/.local/share/clipdeck`) with owner-only directory and database permissions.
Recognized password-manager sensitive MIME markers are skipped. Applications
that do not mark passwords cannot be detected reliably; pause capture when
needed. Imports/exports contain clipboard contents, including any secrets that
were copied without a sensitive marker. Export files use mode 0600.

Defaults: 100 unpinned items, 30-day retention, 8 MB per item, 64 MB total, at
most 1,000 items including pins. Pins survive age/count cleanup but count toward
the total capacity. An import validates all entries and rolls back on failure;
normal retention and capacity rules apply to successfully imported items.

## Run from source

Install dependencies:

```sh
# Fedora
sudo dnf install python3 python3-gobject gtk4
# Ubuntu
sudo apt install python3 python3-gi gir1.2-gtk-4.0
```

Then run:

```sh
python3 run.py
# Optional background start
python3 run.py --background
```

Use `CLIPDECK_DATA_DIR=/some/private/directory` to override the history location.
The source folder must remain in place if you enable autostart from a source run.

## Build and test

```sh
python3 -m unittest discover -s tests -p 'test_*.py' -v
# Actual desktop integration checks; needs Pillow and an X11/XWayland display
PYTHONPATH=. GDK_BACKEND=x11 python3 tests/gui_smoke.py
# Fedora: install rpm-build and glib2 for rebuilding installers
python3 tools/build_packages.py --dist ../release --work ./build
# Ubuntu-only build (glib-compile-schemas required)
python3 tools/build_packages.py --deb-only --dist ../release --work ./build
```

The RPM builder uses the standard `rpmbuild` command. The DEB is a standard
ar archive containing Debian control and data tar archives. No runtime database,
settings, sample history, or test outputs are included in either package.

## Remove

```sh
sudo dnf remove clipdeck
# or
sudo apt remove clipdeck
```

Disable autostart in Preferences first. Removing the package preserves history.
To erase personal history, use Clear history with pinned items included before
uninstalling, or delete your own `~/.local/share/clipdeck` directory afterward.
If you installed the companion separately, remove it with
`gnome-extensions uninstall clipdeck@local`.

MIT licensed. See LICENSE. See the delivered TEST-REPORT.md for the precise
platform and checks completed for this build.
