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
import terminal_detection as td  # noqa: E402


class DetectionTests(TestCase):
    def test_detect_terminal_support_handles_missing_imports(self):
        def fake_import(name):
            raise ImportError("missing")

        with mock.patch("terminal_detection.importlib.import_module", side_effect=fake_import):
            result = td.detect_terminal_support()

        self.assertFalse(result.available)
        self.assertGreater(len(result.errors), 0)
        self.assertGreater(len(result.import_attempts), 0)


if __name__ == "__main__":
    import unittest

    unittest.main()
