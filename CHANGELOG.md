# Changelog

All notable changes to this project will be documented in this file.

The format is inspired by Keep a Changelog and follows simple dated entries while the project is pre-release.

## 2025-08-19 – Bug fixes and UX polish

- Fix Add Volume action to call `add_volume_to_profile` (was calling a missing method and would crash).
- Volume dialog: allow using existing encrypted folders; warn only when mount point is non-empty; enable OK when fields are filled.
- gocryptfs auth: add `-passfile -` and send correct stdin input (single newline for mount, double for init) for reliable non-interactive operation.
- Unmount reliability: prefer `fusermount3 -u`/`fusermount -u`, falling back to `umount`.
- Security Guide: remove stray Python code embedded in the HTML content.
- Cross-platform polish: move Linux Qt env vars before importing PyQt; use `shutil.which` for tool detection; make folder opening platform-aware (Linux/macOS/Windows).

