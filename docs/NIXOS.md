# Mithril on NixOS (and Wayland/Niri)

This is a lightweight guide to run Mithril on NixOS without a full flake. Adjust paths and package names as needed for your channel.

## Packages

You will need at minimum:

- `python3`
- `python3Packages.pyqt6`
- `gocryptfs`
- `fuse3`
- (optional) `qtermwidget` (Qt6) for the embedded terminal
- (optional) `pytest` for running the test suite

Example one-off shell (flakes not required):

```bash
nix-shell -p python3 python3Packages.pyqt6 gocryptfs fuse3 qtermwidget pytest --run "python -m compileall src && python -m pytest tests"
```

If you prefer flakes/devshells, a minimal shell.nix/flake can expose these packages and a wrapper to run the app.

## Running

```bash
python src/mithril-gui.py
```

The app uses PyQt6; no build step is required.

## Wayland / Qt platform notes

- Mithril defaults `QT_QPA_PLATFORM` to `xcb` on Linux **only if** you have not set it; on Wayland, export `QT_QPA_PLATFORM=wayland` before launching if you want native Wayland behavior.
- On Niri/other Wayland compositors, file dialogs may rely on xdg-desktop-portal; ensure a portal backend is running (e.g., `xdg-desktop-portal-wlr`/`xdg-desktop-portal-gtk`).

## Troubleshooting

- Missing QTermWidget: the terminal panel will show guidance; install `qtermwidget` (Qt6) to enable the embedded terminal.
- Fuse permissions: ensure your user can mount FUSE filesystems (`user_allow_other` in `/etc/fuse.conf` may be needed for `-allow_other`).
- Display/backends: if you see platform plugin errors, try `QT_QPA_PLATFORM=wayland` or `QT_QPA_PLATFORM=xcb` explicitly.
