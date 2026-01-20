# Security Notes

- **Embedded terminal is optional**: QTermWidget is detected at runtime and may be disabled. The setup dialog defaults to showing guidance rather than enabling anything automatically.
- **No auto-installation**: Install hints are shown for common distros/package managers; any install action is manual and opt-in.
- **Command execution boundaries**:
  - gocryptfs operations run via explicit argument arrays (no shell concatenation).
  - Secure delete now uses Python filesystem calls with guardrails against dangerous paths (e.g., `/` or `~`).
  - Mount/unmount paths are validated for existence and emptiness before execution.
- **Plugin/provider loading**: Only built-in providers are used (`QTermWidgetProvider` or `NullTerminalProvider`), avoiding arbitrary plugin paths.
- **Logging/privacy**: Commands echoed into the embedded terminal omit secrets; password prompts remain in dialogs and are not logged.
- **Tray/system helpers**: External calls (`umount`, `xdg-open`, `mount`) use argument arrays to avoid injection via user-controlled paths.
