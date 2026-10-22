# ClipDeck 1.0.0 validation

Date: 22 October 2026.
Host: Fedora Linux 44, GNOME Shell 50.6, Python 3.14, GTK 4.22.5.

## Passed

- 14 storage unit tests: duplicate updates, multi-format preservation, literal
  search, kind filters, pinned retention, age/count cleanup, clear/delete,
  export/import, malformed import atomicity, size/format validation, private
  file permissions, settings persistence, HTML text previews, file references,
  and refusal to export through symlinks.
- Real desktop integration through X11/XWayland, using independent GTK producer
  and consumer processes: text and HTML capture/restore, plain-text conversion,
  PNG capture/preview/restore, file URI capture/restore, GNOME copied-file
  references (including non-destructive normalization of cut references), pause,
  and observable password-manager MIME marker exclusion.
- Real GUI actions: pinning, search, emoji tab, snippet editor/save, preferences,
  and clear-history confirmation/cancel.
- Native Wayland: window creation, tab switching, preferences, and reading text
  back from the app's own clipboard ownership.
- GNOME companion logic with mocked Shell APIs: forwarding multiple MIME types,
  sensitive-marker exclusion, size limit, GNOME file references, shortcut
  activation, paste destination checks, virtual key sequence, and cleanup.
- Extension JavaScript syntax, strict GSettings schema compilation, desktop
  entry validation, and Python bytecode compilation.
- DEB metadata recognized by dpkg-deb; extraction succeeds.
- RPM built with rpmbuild; RPM digest validation and extraction succeed.
- Both extracted packages match all staged runtime files byte-for-byte and
  preserve their permissions. No runtime history or personal settings are
  packaged. SHA256SUMS accompanies the release.

## Boundaries

- Ubuntu was not booted in a VM or installed on this machine. The DEB is built
  for Ubuntu 24.04+ dependency names and was structurally validated; Ubuntu
  desktop integration still needs testing on an Ubuntu installation.
- Neither package was installed into the host's system directories. Validation
  used extraction in the workspace and the host's installed GTK/Python runtime.
- The GNOME extension was not enabled inside the live Shell. Its real global
  shortcut, background Wayland capture, panel indicator, and automatic paste
  need an in-session acceptance test after enabling the extension. Mock tests
  do not establish compatibility with every GNOME 45–50 release.
- KDE/Sway native Wayland background capture is not implemented. XWayland
  behavior can vary by compositor. Sensitive markers only protect data when
  the clipboard backend exposes them; clipboard proxies may remove metadata.
- Packages are unsigned local builds, not distribution-repository releases.

Graphics-driver warnings occurred inside the sandbox; the native GTK GUI ran
successfully using software rendering for test sessions.
