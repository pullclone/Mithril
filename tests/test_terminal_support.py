import io
import os
import sys
import types
import importlib
from unittest import mock, TestCase


def _ensure_qt_stubs():
    try:
        import PyQt6.QtWidgets  # noqa: F401
        return
    except Exception:
        pass

    pyqt6 = types.ModuleType("PyQt6")
    qtwidgets = types.ModuleType("PyQt6.QtWidgets")

    class _Dummy:
        def __init__(self, *args, **kwargs):
            pass

        def __call__(self, *args, **kwargs):
            return self

    class _Layout(_Dummy):
        def addWidget(self, *args, **kwargs):
            return None

        def setContentsMargins(self, *args, **kwargs):
            return None

    qtwidgets.QWidget = _Dummy
    qtwidgets.QLabel = _Dummy
    qtwidgets.QTextBrowser = _Dummy
    qtwidgets.QVBoxLayout = _Layout

    sys.modules["PyQt6"] = pyqt6
    sys.modules["PyQt6.QtWidgets"] = qtwidgets


_ensure_qt_stubs()

ROOT = os.path.join(os.path.dirname(__file__), "..", "src")
sys.path.insert(0, ROOT)
import terminal_support as ts  # noqa: E402


class ParseOsReleaseTests(TestCase):
    def test_parse_os_release_reads_id(self):
        fake_os_release = 'ID=arch\nNAME="Arch Linux"\n'
        with mock.patch("builtins.open", mock.mock_open(read_data=fake_os_release)):
            info = ts.parse_os_release()
        self.assertEqual(info.get("id"), "arch")


class PackageManagerTests(TestCase):
    def test_detect_package_manager_prefers_first_available(self):
        with mock.patch("terminal_support.shutil.which", side_effect=lambda name: "/bin/"+name if name == "apt" else None):
            self.assertEqual(ts.detect_package_manager(), "apt")

    def test_build_install_guidance_for_ubuntu(self):
        pkgs, hint, notes = ts.build_install_guidance("ubuntu", "apt")
        self.assertIn("qtermwidget-qt6", pkgs)
        self.assertIn("apt install", hint)
        self.assertEqual(notes, [])


class DetectionTests(TestCase):
    def test_detect_terminal_support_handles_missing_imports(self):
        def fake_import(name):
            raise ImportError("missing")

        with mock.patch("terminal_support.importlib.import_module", side_effect=fake_import):
            result = ts.detect_terminal_support()

        self.assertFalse(result.available)
        self.assertGreater(len(result.errors), 0)
        self.assertGreater(len(result.import_attempts), 0)


if __name__ == "__main__":
    import unittest

    unittest.main()
