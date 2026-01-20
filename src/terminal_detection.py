import importlib
import os
import platform
import shutil
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple


@dataclass
class TerminalDetectionResult:
    available: bool
    provider_name: Optional[str] = None
    widget_cls: Optional[type] = None
    distro: Optional[str] = None
    package_manager: Optional[str] = None
    suggested_packages: List[str] = field(default_factory=list)
    install_hint: Optional[str] = None
    notes: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    import_attempts: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict:
        return {
            "available": self.available,
            "provider": self.provider_name,
            "distro": self.distro,
            "package_manager": self.package_manager,
            "suggested_packages": self.suggested_packages,
            "install_hint": self.install_hint,
            "notes": self.notes,
            "errors": self.errors,
            "import_attempts": self.import_attempts,
        }


def parse_os_release(content: Optional[str] = None) -> Dict[str, str]:
    info: Dict[str, str] = {}
    try:
        if content is None:
            with open("/etc/os-release", "r") as f:
                content = f.read()
        for line in content.splitlines():
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

    pm_templates = {
        "apt": "sudo apt install -y {pkgs}",
        "dnf": "sudo dnf install -y {pkgs}",
        "yum": "sudo yum install -y {pkgs}",
        "zypper": "sudo zypper install -y {pkgs}",
        "pacman": "sudo pacman -S --needed {pkgs}",
        "apk": "sudo apk add {pkgs}",
        "brew": "brew install {pkgs}",
        "emerge": "sudo emerge {pkgs}",
        "nix": "nix profile install nixpkgs#{pkg}",
    }

    install_hint = None

    # Special-case NixOS regardless of detected package manager.
    if distro_id == "nixos":
        primary_pkg = suggested_packages[0]
        install_hint = pm_templates["nix"].format(pkg=primary_pkg)
        notes.append("Alternatively add qtermwidget to environment.systemPackages or home.packages.")
    elif pm and pm in pm_templates:
        install_hint = pm_templates[pm].format(pkgs=" ".join(suggested_packages))
    elif not pm:
        notes.append("No supported package manager detected.")

    return suggested_packages, install_hint, notes


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
