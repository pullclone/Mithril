# ADR: Optional Embedded Terminal Integration

## Status
Accepted – first iteration of optional QTermWidget integration.

## Context
- Mithril is a PyQt6 widgets app that currently embeds an external terminal process.
- QTermWidget may not be installed across distributions; the app must run without it.
- Users need a guided, first-run experience plus distro-aware install hints.
- The terminal should be treated as a risky interface; keep boundaries clear and avoid implicit shell execution.

## Decision
- Introduced a small terminal layer (`TerminalManager` + providers) in `terminal_support.py`.
- The manager detects QTermWidget at runtime (multiple import paths) and reports structured availability data, including distro/package-manager hints from `/etc/os-release`.
- Two providers exist:
  - `QTermWidgetProvider` (used when QTermWidget is detected).
  - `NullTerminalProvider` (always available; renders guidance instead of a widget).
- Added `TerminalPanel` and `TerminalSetupDialog` in the UI:
  - Persisted toggle via `QSettings` (`terminal/enabled`, `terminal/visible`, `terminal/setup_done`).
  - First-run prompt appears when the user first toggles the terminal.
  - Panel shows install instructions when QTermWidget is missing.
- Command execution was hardened to prefer explicit argument arrays; unsafe string shells were removed from key paths.

## Consequences
- Mithril runs without QTermWidget installed; the terminal UI gracefully degrades to guidance.
- Adding new providers (e.g., scoped/sandboxed terminals) requires implementing `TerminalProviderBase`.
- The UI now has an explicit “Terminal Setup” entry and respects persisted visibility.
- Future work: tabbed sessions per volume, scoped command policies, and deeper sandboxing can plug into the manager without touching the core UI.
