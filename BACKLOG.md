# Backlog / Next Steps

- Add per-volume terminal tabs bound to volume context (one shell per mount), including tab lifecycle and status badges.
- Implement scoped/allowlisted command execution for future features (no shell interpretation, policy + logging, optional sandbox/bwrap hooks).
- Terminal UX polish: theming aligned with Mithril UI, configurable height, and keyboard shortcuts to focus/blur the panel.
- Add CI gates (lint/format, minimal smoke test for terminal detection, static analysis such as `flake8`/`mypy` if adopted).
- Integrate “open terminal here” entry points from the file tree/project views and from tray actions.
- Harden delete flows further (optional secure wipe/overwrite, dry-run prompts) and extend error logging to structured logs.
