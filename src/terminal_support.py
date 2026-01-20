import os
import shutil
from dataclasses import dataclass
from typing import Optional

from PyQt6.QtWidgets import QLabel, QTextBrowser, QVBoxLayout, QWidget

from terminal_detection import (
    TerminalDetectionResult,
    detect_terminal_support,
)


@dataclass
class TerminalSession:
    session_id: str
    working_directory: str
    shell: Optional[str] = None
    volume_context: Optional[str] = None


class TerminalProviderBase:
    def is_available(self) -> bool:
        return False

    def create_widget(self, session: TerminalSession, parent: Optional[QWidget] = None) -> QWidget:
        placeholder = QWidget(parent)
        layout = QVBoxLayout(placeholder)
        layout.addWidget(QLabel("Terminal unavailable."))
        return placeholder

    def write(self, text: str) -> None:
        # Base provider ignores writes.
        return


class QTermWidgetProvider(TerminalProviderBase):
    def __init__(self, widget_cls: type):
        super().__init__()
        self.widget_cls = widget_cls
        self._widget = None

    def is_available(self) -> bool:
        return self.widget_cls is not None

    def create_widget(self, session: TerminalSession, parent: Optional[QWidget] = None) -> QWidget:
        self._widget = self.widget_cls(parent)

        # Apply basic session properties if the widget exposes setters.
        if hasattr(self._widget, "setWorkingDirectory"):
            self._widget.setWorkingDirectory(session.working_directory)
        if session.shell and hasattr(self._widget, "setShellProgram"):
            self._widget.setShellProgram(session.shell)

        return self._widget

    def write(self, text: str) -> None:
        if not self._widget:
            return
        if hasattr(self._widget, "sendText"):
            self._widget.sendText(text + "\n")
        elif hasattr(self._widget, "write"):  # Fallback for API variants
            try:
                self._widget.write((text + "\n").encode())
            except Exception:
                pass


class NullTerminalProvider(TerminalProviderBase):
    def __init__(self, detection: TerminalDetectionResult):
        super().__init__()
        self.detection = detection

    def create_widget(self, session: TerminalSession, parent: Optional[QWidget] = None) -> QWidget:
        placeholder = QWidget(parent)
        layout = QVBoxLayout(placeholder)
        layout.setContentsMargins(8, 8, 8, 8)
        label = QLabel("Embedded terminal is disabled or unavailable.")
        label.setWordWrap(True)
        layout.addWidget(label)

        info = QTextBrowser()
        info.setReadOnly(True)
        info.setOpenExternalLinks(True)

        lines = []
        if self.detection.install_hint:
            lines.append(f"<b>Install hint:</b> {self.detection.install_hint}")
        if self.detection.suggested_packages:
            lines.append(
                f"<b>Suggested packages:</b> {', '.join(self.detection.suggested_packages)}"
            )
        if self.detection.notes:
            lines.append("<b>Notes:</b>")
            for note in self.detection.notes:
                lines.append(f"- {note}")
        if self.detection.errors:
            lines.append("<b>Errors:</b>")
            for err in self.detection.errors:
                lines.append(f"- {err}")

        info.setHtml("<br/>".join(lines) if lines else "No terminal provider detected.")
        layout.addWidget(info)
        return placeholder


class TerminalManager:
    """Creates terminal sessions and chooses the appropriate provider."""

    def __init__(self, settings, default_workdir: Optional[str] = None):
        self.settings = settings
        self.default_workdir = default_workdir or os.path.expanduser("~")

        # Settings flags
        self.enabled_setting = settings.value("terminal/enabled", None)
        self.enabled = bool(self.enabled_setting) if self.enabled_setting is not None else False
        self.setup_seen = settings.value("terminal/setup_done", False, type=bool)
        self.visible = settings.value("terminal/visible", False, type=bool)

        # Detection + provider selection
        self.detection = detect_terminal_support()
        self.provider = self._select_provider()

        # Session management
        self.session: Optional[TerminalSession] = None
        self._widget: Optional[QWidget] = None

    def _select_provider(self) -> TerminalProviderBase:
        if self.enabled and self.detection.available and self.detection.widget_cls:
            return QTermWidgetProvider(self.detection.widget_cls)
        return NullTerminalProvider(self.detection)

    def refresh_detection(self):
        previous_provider = getattr(self, "provider", None)
        previous_provider_type = type(previous_provider) if previous_provider else None
        self.detection = detect_terminal_support()
        self.provider = self._select_provider()
        if previous_provider_type is not type(self.provider):
            self._widget = None

    def ensure_session(self) -> TerminalSession:
        if self.session:
            return self.session
        workdir = self.default_workdir if os.path.isdir(self.default_workdir) else os.path.expanduser("~")
        self.session = TerminalSession(
            session_id="default",
            working_directory=workdir,
            shell=os.environ.get("SHELL"),
        )
        return self.session

    def create_or_get_widget(self, parent: Optional[QWidget] = None) -> QWidget:
        if self._widget is None:
            session = self.ensure_session()
            self._widget = self.provider.create_widget(session, parent)
        return self._widget

    def write(self, text: str) -> None:
        try:
            self.provider.write(text)
        except Exception:
            # Writing to the terminal is best-effort; ignore provider-specific failures.
            pass

    def set_enabled(self, enabled: bool):
        self.enabled = enabled
        self.enabled_setting = enabled
        self.settings.setValue("terminal/enabled", enabled)
        self.provider = self._select_provider()
        self._widget = None

    def set_visible(self, visible: bool):
        self.visible = visible
        self.settings.setValue("terminal/visible", visible)

    def mark_setup_seen(self):
        self.setup_seen = True
        self.settings.setValue("terminal/setup_done", True)

    def should_prompt_setup(self) -> bool:
        return not self.setup_seen and self.enabled_setting is None

    def has_working_provider(self) -> bool:
        return self.enabled and self.provider.is_available()


def detect_terminal_support() -> TerminalDetectionResult:
    import_paths: List[Tuple[str, Callable]] = [
        ("qtermwidget", lambda module: getattr(module, "QTermWidget", None)),
        ("PyQt6.QTermWidget", lambda module: getattr(module, "QTermWidget", None)),
        ("PyQt5.QTermWidget", lambda module: getattr(module, "QTermWidget", None)),
        ("pyqterm", lambda module: getattr(module, "QTermWidget", None)),
    ]

    widget_cls = None
    provider_name = None
    attempts = []
    errors = []

    for module_path, extractor in import_paths:
        attempts.append(module_path)
        try:
            module = importlib.import_module(module_path)
            widget_cls = extractor(module)
            if widget_cls:
                provider_name = module_path
                break
            errors.append(f"{module_path}: QTermWidget not found")
        except Exception as exc:  # pragma: no cover - defensive
            errors.append(f"{module_path}: {exc}")

    distro_info = parse_os_release()
    distro_id = distro_info.get("id")
    package_manager = detect_package_manager()
    suggested_packages, install_hint, notes = build_install_guidance(distro_id, package_manager)

    return TerminalDetectionResult(
        available=widget_cls is not None,
        provider_name=provider_name,
        widget_cls=widget_cls,
        distro=distro_id,
        package_manager=package_manager,
        suggested_packages=suggested_packages,
        install_hint=install_hint,
        notes=notes,
        errors=errors,
        import_attempts=attempts,
    )


def parse_os_release() -> Dict[str, str]:
    info: Dict[str, str] = {}
    try:
        with open("/etc/os-release", "r") as f:
            for line in f:
                if "=" not in line:
                    continue
                key, value = line.strip().split("=", 1)
                info[key.lower()] = value.strip().strip('"')
    except FileNotFoundError:
        pass
    info.setdefault("id", platform.system().lower())
    return info


def detect_package_manager() -> Optional[str]:
    for candidate in ["apt", "dnf", "yum", "zypper", "pacman", "apk", "brew", "emerge"]:
        if shutil.which(candidate):
            return candidate
    return None


def build_install_guidance(
    distro_id: Optional[str], package_manager: Optional[str]
) -> Tuple[List[str], Optional[str], List[str]]:
    distro_id = (distro_id or "").lower()
    pm = package_manager

    distro_packages = {
        "ubuntu": ["qtermwidget-qt6", "qtermwidget-qt5"],
        "debian": ["qtermwidget-qt6", "qtermwidget-qt5"],
        "linuxmint": ["qtermwidget-qt6", "qtermwidget-qt5"],
        "fedora": ["qtermwidget-qt6", "qtermwidget-qt5"],
        "rhel": ["qtermwidget-qt6", "qtermwidget-qt5"],
        "centos": ["qtermwidget-qt6", "qtermwidget-qt5"],
        "opensuse": ["qtermwidget-qt6", "qtermwidget-qt5"],
        "sles": ["qtermwidget-qt6", "qtermwidget-qt5"],
        "arch": ["qtermwidget", "qtermwidget6"],
        "manjaro": ["qtermwidget", "qtermwidget6"],
        "endeavouros": ["qtermwidget", "qtermwidget6"],
        "alpine": ["qtermwidget-qt6"],
    }

    suggested_packages = distro_packages.get(distro_id, ["qtermwidget-qt6", "qtermwidget-qt5"])
    notes = []

    if pm:
        install_hint = f"sudo {pm} install {' '.join(suggested_packages)}"
    else:
        install_hint = None
        notes.append("No supported package manager detected.")

    return suggested_packages, install_hint, notes
