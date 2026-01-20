import os
import sys
from unittest import mock

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..", "src")
sys.path.insert(0, ROOT)

import terminal_detection as td  # noqa: E402


@pytest.mark.parametrize(
    "content,expected",
    [
        ("ID=fedora\nVERSION_ID=41\n", "fedora"),
        ("ID=ubuntu\nNAME=\"Ubuntu\"\n", "ubuntu"),
        ("ID=arch\nNAME=\"Arch Linux\"\n", "arch"),
        ("ID=\"opensuse-leap\"\n", "opensuse-leap"),
        ("ID=alpine\n", "alpine"),
    ],
)
def test_parse_os_release_variants(content, expected):
    info = td.parse_os_release(content)
    assert info.get("id") == expected


@pytest.mark.parametrize(
    "available,expected",
    [
        (["/usr/bin/apt"], "apt"),
        (["/usr/bin/dnf"], "dnf"),
        (["/usr/bin/pacman"], "pacman"),
        (["/usr/bin/zypper"], "zypper"),
        (["/usr/bin/apk"], "apk"),
    ],
)
def test_detect_package_manager(available, expected):
    def fake_which(name):
        return available[0] if os.path.basename(available[0]) == name else None

    with mock.patch("terminal_detection.shutil.which", side_effect=fake_which):
        assert td.detect_package_manager() == expected


@pytest.mark.parametrize(
    "distro,pm,expected_pkg",
    [
        ("ubuntu", "apt", "qtermwidget-qt6"),
        ("fedora", "dnf", "qtermwidget-qt6"),
        ("arch", "pacman", "qtermwidget"),
        ("alpine", "apk", "qtermwidget-qt6"),
    ],
)
def test_build_install_guidance(distro, pm, expected_pkg):
    pkgs, hint, notes = td.build_install_guidance(distro, pm)
    assert expected_pkg in pkgs
    if hint:
        assert "sudo" in hint
        assert pm in hint
    else:
        assert "No supported package manager" in " ".join(notes)
