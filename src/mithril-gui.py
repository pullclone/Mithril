import sys
import os
import json
import subprocess
import shlex
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QListWidget, QStackedWidget, QMenuBar, QFileDialog, QInputDialog, QMessageBox,
    QDialog, QFormLayout, QLineEdit, QLabel, QDialogButtonBox, QComboBox,
    QListWidgetItem, QCheckBox, QSystemTrayIcon, QMenu, QTextEdit, QToolButton, QGroupBox,
    QWizard, QWizardPage, QTextBrowser, QGridLayout, QFrame, QRadioButton)
from PyQt6.QtCore import QSize, Qt, QPropertyAnimation, QEasingCurve, QSettings, QTimer
from PyQt6.QtGui import QAction, QIcon, QPixmap
from terminal_support import TerminalManager
# Only set Linux-specific Qt platform on Linux if not already specified by the environment.
if sys.platform.startswith("linux"):
    os.environ.setdefault("QT_QPA_PLATFORMTHEME", "gtk3")
    # Respect explicit overrides (Wayland/NixOS may set WAYLAND_DISPLAY/Qt platform).
    if "QT_QPA_PLATFORM" not in os.environ:
        os.environ["QT_QPA_PLATFORM"] = "xcb"

# Directory for bundled icons
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__)) if "__file__" in locals() else os.getcwd()
ICONS_DIR = os.path.normpath(os.path.join(SCRIPT_DIR, os.pardir, "icons"))

# --- Configuration ---
ORGANIZATION_NAME = "GocryptfsGUI"
APPLICATION_NAME = "GocryptfsManager"
PROFILES_FILE = os.path.join(os.path.expanduser("~"), ".config", APPLICATION_NAME, "profiles.json")
SENSITIVE_FLAGS = {
    "-passfile", "--passfile",
    "-extpass", "--extpass",
    "-config"
}

# --- Path safety helpers ---
def _is_under(base: Path, target: Path) -> bool:
    try:
        return os.path.commonpath([str(base), str(target)]) == str(base)
    except Exception:
        return False

def _resolve_path(p: str) -> Path:
    return Path(p).expanduser().resolve(strict=False)

def _is_path_allowed(target: Path, allowed_roots) -> bool:
    for root in allowed_roots:
        try:
            root_resolved = _resolve_path(str(root))
        except Exception:
            continue
        if _is_under(root_resolved, target):
            return True
    return False

def _count_entries(path: Path, limit: int = 500) -> int:
    """Return a bounded count of direct children to inform deletion prompts."""
    try:
        with os.scandir(path) as entries:
            count = 0
            for _ in entries:
                count += 1
                if count > limit:
                    return count
            return count
    except Exception:
        return 0


def _append_delete_audit(entries):
    try:
        log_dir = Path(PROFILES_FILE).parent
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "secure_delete.log"
        timestamp = datetime.utcnow().isoformat() + "Z"
        with log_file.open("a", encoding="utf-8") as f:
            for entry in entries:
                f.write(f"{timestamp} | {entry}\n")
    except Exception:
        # Audit log is best-effort
        pass

def format_cmd_for_echo(argv):
    redacted = []
    skip_next = False
    for arg in argv:
        if skip_next:
            redacted.append("<redacted>")
            skip_next = False
            continue
        if arg in SENSITIVE_FLAGS:
            redacted.append(arg)
            skip_next = True
            continue
        redacted.append(arg)
    return " ".join(redacted)

def can_exec(binary: str) -> bool:
    return shutil.which(binary) is not None or (os.path.isabs(binary) and os.access(binary, os.X_OK))

class ErrorDialog(QDialog):
    """A custom dialog for showing detailed, scrollable error messages."""
    def __init__(self, message, stderr_text, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Execution Error")
        self.setMinimumWidth(500)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(message))

        error_output = QTextEdit(stderr_text)
        error_output.setReadOnly(True)
        error_output.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        error_output.setFontFamily("monospace")
        layout.addWidget(error_output)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

class PasswordDialog(QDialog):
    """A dialog for setting and confirming a password for a new volume."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Set Volume Password")
        self.setMinimumWidth(400)

        layout = QFormLayout(self)
        self.info_label = QLabel("This is a new volume. Please set a strong password.")
        self.pass_edit1 = QLineEdit()
        self.pass_edit1.setEchoMode(QLineEdit.EchoMode.Password)
        self.pass_edit2 = QLineEdit()
        self.pass_edit2.setEchoMode(QLineEdit.EchoMode.Password)

        layout.addRow(self.info_label)
        layout.addRow("Password:", self.pass_edit1)
        layout.addRow("Confirm Password:", self.pass_edit2)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addRow(button_box)

    def get_password(self):
        p1 = self.pass_edit1.text()
        p2 = self.pass_edit2.text()
        if p1 and p1 == p2:
            return p1
        return None


class MountPasswordDialog(QDialog):
    """A dialog for entering a password to mount a volume."""
    def __init__(self, parent=None, show_error=False):
        super().__init__(parent)
        self.setWindowTitle("Password Required")
        self.setMinimumWidth(400)

        layout = QGridLayout(self)
        layout.setColumnStretch(1, 1)

        # Row 0: Password
        layout.addWidget(QLabel("Password:"), 0, 0)
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.password_edit, 0, 1)

        # Row 1: Remember Checkbox
        self.remember_cb = QCheckBox("Remember password for this session")
        layout.addWidget(self.remember_cb, 1, 0, 1, 2)

        # Row 2: Error Message (optional)
        self.error_label = QLabel("⚠️ Incorrect Password")
        self.error_label.setStyleSheet("color: orange;")
        self.error_label.setVisible(show_error)
        layout.addWidget(self.error_label, 2, 0, 1, 2)

        # Row 3: Dialog Buttons
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box, 3, 0, 1, 2)

        self.password_edit.setFocus()

    def get_password(self):
        return self.password_edit.text()

    def should_remember(self):
        return self.remember_cb.isChecked()


class VolumeDialog(QDialog):
    """A dialog for adding or editing a volume favorite."""
    def __init__(self, volume_data=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Volume Details")
        self.setMinimumWidth(500)

        layout = QGridLayout(self)
        layout.setColumnStretch(1, 1) # Allow the path column to expand

        # Row 0: Label
        layout.addWidget(QLabel("Label:"), 0, 0)
        self.label_edit = QLineEdit()
        layout.addWidget(self.label_edit, 0, 1, 1, 2) # Span 2 columns

        # Row 1: Encrypted Folder
        layout.addWidget(QLabel("Encrypted Folder:"), 1, 0)
        self.cipher_dir_combo = QComboBox()
        self.cipher_dir_combo.setEditable(True)
        self.cipher_dir_combo.addItems([os.path.expanduser(p) for p in ["~/Encrypted", "~/.local/share/gocryptfs/cipher"]])
        self.cipher_dir_combo.setToolTip("Recommended location for the encrypted container. Secure, persistent, and private.")
        layout.addWidget(self.cipher_dir_combo, 1, 1)
        
        browse_cipher = QPushButton("Browse...")
        browse_cipher.clicked.connect(lambda: self.browse_path(self.cipher_dir_combo, "Select Encrypted Folder"))
        layout.addWidget(browse_cipher, 1, 2)

        self.cipher_warning_label = QLabel("⚠️ This folder already exists. Continuing may overwrite or expose existing files.")
        self.cipher_warning_label.setStyleSheet("color: orange;")
        self.cipher_warning_label.setVisible(False)
        layout.addWidget(self.cipher_warning_label, 2, 1, 1, 2)

        # Row 3: Mount Point
        layout.addWidget(QLabel("Mount Point:"), 3, 0)
        self.mount_point_combo = QComboBox()
        self.mount_point_combo.setEditable(True)
        self.mount_point_combo.addItems([os.path.expanduser(p) for p in ["~/Secure", "~/Private"]])
        self.mount_point_combo.setToolTip("Recommended location for the decrypted view.")
        layout.addWidget(self.mount_point_combo, 3, 1)

        browse_mount = QPushButton("Browse...")
        browse_mount.clicked.connect(lambda: self.browse_path(self.mount_point_combo, "Select Mount Point"))
        layout.addWidget(browse_mount, 3, 2)

        self.mount_warning_label = QLabel("⚠️ This folder already exists. Continuing may overwrite or expose existing files.")
        self.mount_warning_label.setStyleSheet("color: orange;")
        self.mount_warning_label.setVisible(False)
        layout.addWidget(self.mount_warning_label, 4, 1, 1, 2)

        # Row 5: Permissions Checkbox
        self.perm_check = QCheckBox("Apply recommended permissions to new paths (chmod 700)")
        self.perm_check.setChecked(True)
        layout.addWidget(self.perm_check, 5, 0, 1, 3) # Span all 3 columns

        # Row 6: Automount Options
        self.automount_cb = QCheckBox("Mount automatically when Mithril starts")
        layout.addWidget(self.automount_cb, 6, 0, 1, 3)

        self.usb_volume_cb = QCheckBox("Treat as removable USB volume (automount when detected)")
        layout.addWidget(self.usb_volume_cb, 7, 0, 1, 3)
        
        self.auto_open_cb = QCheckBox("Open folder after mounting")
        layout.addWidget(self.auto_open_cb, 8, 0, 1, 3)

        self.pin_to_tray_cb = QCheckBox("Pin this volume to system tray")
        layout.addWidget(self.pin_to_tray_cb, 9, 0, 1, 3)

        if volume_data:
            self.label_edit.setText(volume_data.get("label", ""))
            self.cipher_dir_combo.setCurrentText(volume_data.get("cipher_dir", ""))
            self.mount_point_combo.setCurrentText(volume_data.get("mount_point", ""))
            self.perm_check.setVisible(False)
            # Load automount settings
            self.automount_cb.setChecked(volume_data.get("automount_on_startup", False))
            self.usb_volume_cb.setChecked(volume_data.get("volume_type") == "usb")
            self.auto_open_cb.setChecked(volume_data.get("auto_open_mount", False))
            self.pin_to_tray_cb.setChecked(volume_data.get("pin_to_tray", False))

        # Row 10: Dialog Buttons
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box, 10, 0, 1, 3) # Span all 3 columns

        self.cipher_dir_combo.currentTextChanged.connect(self.check_path_existence)
        self.mount_point_combo.currentTextChanged.connect(self.check_path_existence)
        self.check_path_existence()

    def check_path_existence(self):
        cipher_path = self.cipher_dir_combo.currentText()
        mount_path = self.mount_point_combo.currentText()

        self.cipher_warning_label.setVisible(os.path.exists(cipher_path))
        self.mount_warning_label.setVisible(os.path.exists(mount_path))

        self.button_box.button(QDialogButtonBox.StandardButton.Ok).setEnabled(
            not self.cipher_warning_label.isVisible() and not self.mount_warning_label.isVisible()
        )


    def browse_path(self, combo, caption):
        path = QFileDialog.getExistingDirectory(self, caption)
        if path:
            combo.setCurrentText(path)

    def get_data(self):
        return {
            "label": self.label_edit.text(),
            "cipher_dir": self.cipher_dir_combo.currentText(),
            "mount_point": self.mount_point_combo.currentText(),
            "apply_perms": self.perm_check.isChecked() and self.perm_check.isVisible(),
            "automount_on_startup": self.automount_cb.isChecked(),
            "volume_type": "usb" if self.usb_volume_cb.isChecked() else "standard",
            "auto_open_mount": self.auto_open_cb.isChecked(),
            "pin_to_tray": self.pin_to_tray_cb.isChecked(),
        }

class SimplifiedView(QWidget):
    """The GUI for managing favorite volumes."""
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        # --- Profile Management ---
        profile_layout = QHBoxLayout()
        profile_layout.addWidget(QLabel("Profile:"))
        self.profile_combo = QComboBox()
        self.profile_combo.setEditable(True)
        self.profile_combo.currentIndexChanged.connect(self.main_window.switch_profile)
        
        self.manage_profiles_button = QToolButton()
        self.manage_profiles_button.setIcon(QIcon.fromTheme("document-properties"))
        self.manage_profiles_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.manage_profiles_menu = QMenu(self)
        self.manage_profiles_button.setMenu(self.manage_profiles_menu)
        
        self.new_profile_action = self.manage_profiles_menu.addAction("New Profile...")
        self.rename_profile_action = self.manage_profiles_menu.addAction("Rename Current Profile...")
        self.delete_profile_action = self.manage_profiles_menu.addAction("Delete Current Profile")

        self.new_profile_action.triggered.connect(self.main_window.new_profile)
        self.rename_profile_action.triggered.connect(self.main_window.rename_profile)
        self.delete_profile_action.triggered.connect(self.main_window.delete_profile)

        self.save_profile_button = QPushButton(QIcon.fromTheme("document-save"), " Save")
        self.save_profile_button.clicked.connect(self.main_window.save_current_profile)
        
        profile_layout.addWidget(self.profile_combo)
        profile_layout.addWidget(self.manage_profiles_button)
        profile_layout.addWidget(self.save_profile_button)
        layout.addLayout(profile_layout)

        # --- Favorite Volumes List ---
        layout.addWidget(QLabel("<b>Favorite Volumes:</b>"))
        self.volumes_list = QListWidget()
        self.volumes_list.itemSelectionChanged.connect(self.main_window.on_volume_selected)
        self.volumes_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.volumes_list.customContextMenuRequested.connect(self.show_volume_context_menu)
        layout.addWidget(self.volumes_list)

        # --- Advanced Flags Group ---
        self.advanced_group = QGroupBox("Advanced Flags")
        self.advanced_group.setCheckable(True)
        self.advanced_group.setChecked(False)
        self.advanced_group.toggled.connect(lambda checked: self.main_window.settings.setValue("advanced_flags_expanded", checked))
        
        advanced_layout = QFormLayout(self.advanced_group)
        self.allow_other_cb = QCheckBox("Allow other users to access files")
        self.allow_other_cb.setToolTip("-allow_other")
        advanced_layout.addRow("Allow Other:", self.allow_other_cb)

        self.reverse_cb = QCheckBox("Reverse mode (show decrypted view of encrypted dir)")
        self.reverse_cb.setToolTip("-reverse")
        advanced_layout.addRow("Reverse Mode:", self.reverse_cb)

        self.scryptn_edit = QLineEdit()
        self.scryptn_edit.setToolTip("-scryptn N: Set scrypt cost parameter to 2^N")
        advanced_layout.addRow("scryptn (N):", self.scryptn_edit)
        
        self.advanced_group.setEnabled(False)
        layout.addWidget(self.advanced_group)

        # --- Volume Actions ---
        vol_actions_layout = QHBoxLayout()
        self.add_button = QPushButton(QIcon.fromTheme("list-add"), " Add")
        self.edit_button = QPushButton(QIcon.fromTheme("edit-rename"), " Edit")
        self.remove_button = QPushButton(QIcon.fromTheme("list-remove"), " Remove")
        vol_actions_layout.addWidget(self.add_button)
        vol_actions_layout.addWidget(self.edit_button)
        vol_actions_layout.addWidget(self.remove_button)
        vol_actions_layout.addStretch()
        self.mount_button = QPushButton(QIcon.fromTheme("media-playback-start"), " Mount Selected")
        self.unmount_button = QPushButton(QIcon.fromTheme("media-playback-stop"), " Unmount Selected")
        vol_actions_layout.addWidget(self.mount_button)
        vol_actions_layout.addWidget(self.unmount_button)
        layout.addLayout(vol_actions_layout)

        # --- Connect Signals ---
        self.add_button.clicked.connect(self.add_volume)
        self.edit_button.clicked.connect(self.edit_volume)
        self.remove_button.clicked.connect(self.remove_volume)
        self.mount_button.clicked.connect(self.mount_selected_volume)
        self.unmount_button.clicked.connect(self.unmount_selected_volume)
        
        self.allow_other_cb.stateChanged.connect(self.save_flags)
        self.reverse_cb.stateChanged.connect(self.save_flags)
        self.scryptn_edit.textChanged.connect(self.save_flags)

        self._create_shortcuts()

    def _create_shortcuts(self):
        # These are application-wide shortcuts
        QAction("Quit", self, shortcut="Ctrl+Q", triggered=self.main_window.close_app)
        QAction("Add new volume", self, shortcut="Ctrl+N", triggered=self.add_volume)
        QAction("Re-run setup wizard", self, shortcut="Ctrl+R", triggered=self.main_window.rerun_setup_wizard)
        QAction("Open Security Guide", self, shortcut="Ctrl+H", triggered=self.main_window.show_security_guide)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
            if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
                self.edit_volume()
            else:
                self.mount_selected_volume()
        elif event.key() == Qt.Key.Key_Delete:
            if event.modifiers() == Qt.KeyboardModifier.ShiftModifier:
                self.secure_delete_volume()
            else:
                self.remove_volume()
        else:
            super().keyPressEvent(event)

    def get_selected_volume_id(self):
        item = self.volumes_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def add_volume(self):
        dialog = VolumeDialog(parent=self)
        if dialog.exec():
            volume_data = dialog.get_data()
            self.main_window.create_and_initialize_volume(volume_data)

    def edit_volume(self):
        volume_id = self.get_selected_volume_id()
        if volume_id is None: return
        volume_data = self.main_window.profiles[self.main_window.current_profile_name]["volumes"][volume_id]

        dialog = VolumeDialog(volume_data, self)
        if dialog.exec():
            self.main_window.update_volume_in_profile(volume_id, dialog.get_data())

    def remove_volume(self):
        volume_id = self.get_selected_volume_id()
        if volume_id is None: return
        reply = QMessageBox.question(self, "Confirm Remove", f"Are you sure you want to remove this favorite?")
        if reply == QMessageBox.StandardButton.Yes:
            self.main_window.remove_volume_from_profile(volume_id)

    def secure_delete_volume(self):
        volume_id = self.get_selected_volume_id()
        if volume_id is None: return
        
        volume_data = self.main_window.profiles[self.main_window.current_profile_name]["volumes"][volume_id]
        dialog = SecureDeleteDialog(volume_data, self)
        if dialog.exec():
            self.main_window.secure_delete_volume_from_disk(volume_id)

    def show_volume_context_menu(self, pos):
        item = self.volumes_list.itemAt(pos)
        if not item:
            return

        volume_id = item.data(Qt.ItemDataRole.UserRole)
        volume_data = self.main_window.profiles[self.main_window.current_profile_name]["volumes"][volume_id]
        is_mounted = volume_data.get('mount_point') in self.main_window.mounted_paths

        menu = QMenu()
        
        # ─── Primary Actions ───────────────────────────
        if is_mounted:
            menu.addAction("Unmount", self.unmount_selected_volume)
            menu.addAction("Open Files", lambda: self.main_window.open_folder(volume_data.get('mount_point')))
        else:
            menu.addAction("Mount", self.mount_selected_volume)

        menu.addAction("Show Encrypted Storage Folder", lambda: self.main_window.open_folder(volume_data.get('cipher_dir')))

        menu.addSeparator()

        # ─── Management Tools ──────────────────────────
        menu.addAction("Edit Volume", self.edit_volume)

        pin_action = menu.addAction("Pin to Tray")
        pin_action.setCheckable(True)
        pin_action.setChecked(volume_data.get("pin_to_tray", False))
        pin_action.triggered.connect(lambda checked, vol_id=volume_id: self.main_window.toggle_pin_volume(vol_id, checked))

        menu.addSeparator()

        # ─── Destructive Actions ───────────────────────
        menu.addAction("Remove from Favorites", self.remove_volume)
        menu.addAction("Delete Encrypted Volume...", self.secure_delete_volume)

        menu.exec(self.volumes_list.mapToGlobal(pos))

    def mount_selected_volume(self):
        volume_id = self.get_selected_volume_id()
        if volume_id is None: return
        self.main_window.mount_volume(volume_id)

    def unmount_selected_volume(self):
        volume_id = self.get_selected_volume_id()
        if volume_id is None: return
        self.main_window.unmount_volume(volume_id)
        
    def load_flags_for_volume(self, volume_id):
        if volume_id is None:
            self.advanced_group.setEnabled(False)
            self.allow_other_cb.setChecked(False)
            self.reverse_cb.setChecked(False)
            self.scryptn_edit.clear()
            return

        profile_name = self.main_window.current_profile_name
        volumes = self.main_window.profiles[profile_name].get("volumes", [])
        if volume_id >= len(volumes):
            # This can happen if the last item was just deleted.
            self.advanced_group.setEnabled(False)
            self.allow_other_cb.setChecked(False)
            self.reverse_cb.setChecked(False)
            self.scryptn_edit.clear()
            return

        self.advanced_group.setEnabled(True)
        all_flags = volumes[volume_id].get("flags", {})

        self.allow_other_cb.setChecked(all_flags.get("allow_other", False))
        self.reverse_cb.setChecked(all_flags.get("reverse", False))
        self.scryptn_edit.setText(all_flags.get("scryptn", ""))

    def save_flags(self):
        volume_id = self.get_selected_volume_id()
        if volume_id is None: return

        flags = {
            "allow_other": self.allow_other_cb.isChecked(),
            "reverse": self.reverse_cb.isChecked(),
            "scryptn": self.scryptn_edit.text(),
        }
        self.main_window.update_volume_flags(volume_id, flags)


class SecurityGuideDialog(QDialog):
    """A dialog displaying security best practices."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Security Best Practices")
        self.setMinimumSize(600, 400)

        layout = QVBoxLayout(self)
        text_browser = QTextBrowser()
        text_browser.setOpenExternalLinks(True)
        layout.addWidget(text_browser)

        content = """
        <h1>Security Best Practices</h1>
        <p>Mithril is designed with security and simplicity in mind. To help you make the most of your encrypted volumes, we recommend the following:</p>
        
        <h2>Recommended Folder Locations</h2>
        <ul>
            <li><b>Encrypted Folder:</b>
                <ul>
                    <li><code>~/Encrypted</code></li>
                    <li><code>~/.local/share/gocryptfs/cipher</code></li>
                </ul>
                <p>These locations are private, easy to back up securely, and hidden from casual browsing.</p>
            </li>
            <li><b>Mount Point (Decrypted View):</b>
                <ul>
                    <li><code>~/Secure</code></li>
                    <li><code>~/Private</code></li>
                </ul>
                <p>These folders display your decrypted files while the volume is mounted.</p>
            </li>
        </ul>

        <h2>Permissions</h2>
        <p>New folders should be created with owner-only access: <code>chmod 700 /your/folder/path</code>. Mithril will do this for you automatically unless you opt out.</p>

        <h2>Passwords</h2>
        <ul>
            <li>Use strong, unique passphrases.</li>
            <li>Do not reuse volume passphrases for login or websites.</li>
            <li>Avoid storing them in plaintext.</li>
        </ul>

        <h2>Unlocking and Mounting</h2>
        <ul>
            <li>Always unmount when you're done — this re-locks your data.</li>
            <li>Never leave your mount point open on shared systems.</li>
        </ul>

        <h2>Backup</h2>
        <ul>
            <li>Back up your <b>encrypted</b> folder, not the decrypted one.</li>
            <li>Backups remain secure even if stolen, so long as your passphrase is strong.</li>
        </ul>
        
        # Add a styled horizontal line
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line)
        
        <p>For more advanced topics, see the <a href="https://github.com/rfjakob/gocryptfs">gocryptfs documentation</a>. Mithril is a wrapper — the encryption is handled by the trusted gocryptfs tool underneath.</p>
        """
        text_browser.setHtml(content)

class ShortcutsDialog(QDialog):
    """A dialog displaying keyboard shortcuts."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Keyboard Shortcuts")
        
        layout = QVBoxLayout(self)
        self.text_browser = QTextBrowser()
        self.text_browser.setOpenExternalLinks(True)
        layout.addWidget(self.text_browser)

        shortcuts = {
            "Enter": "Mount selected volume",
            "Ctrl + Enter": "Edit selected volume",
            "Del": "Remove volume from favorites",
            "Shift + Del": "Secure delete encrypted volume from disk",
            "Ctrl + N": "Add new volume",
            "Ctrl + ,": "Open Preferences",
            "Ctrl + R": "Re-run setup wizard",
            "Ctrl + H": "Open Security Guide",
            "Ctrl + Q": "Quit application",
            "F1": "Show this help",
        }

        content = """
        <style>
            h1 { text-align: center; }
            table { width: 90%; margin-left: 5%; margin-right: 1%; }
            td { padding: 4px; }
            td:first-child { font-weight: bold; }
        </style>
        <h1>Keyboard Shortcuts</h1>
        <table>
        """
        for key, action in shortcuts.items():
            content += f"<tr><td>{key}</td><td>{action}</td></tr>"
        content += "</table>"
        
        self.text_browser.setHtml(content)
        
        # Defer resizing and centering
        QTimer.singleShot(0, self.resize_and_center)

    def resize_and_center(self):
        # Resize based on content
        self.setFixedWidth(400)
        self.text_browser.setFixedHeight(int(self.text_browser.document().size().height()) + 5)
        self.adjustSize()

        # Center on parent
        if self.parent():
            parent_rect = self.parent().frameGeometry()
            self.move(parent_rect.center() - self.rect().center())


class SecureDeleteDialog(QDialog):
    """A confirmation dialog for securely deleting a volume from disk."""
    def __init__(self, volume_data, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Permanently Delete Encrypted Volume?")
        self.setMinimumWidth(500)

        self.volume_name = volume_data.get("label", "")
        layout = QVBoxLayout(self)

        message = QLabel(f"This action will permanently erase all encrypted data at:<br><b>{volume_data.get('cipher_dir', '')}</b>")
        message.setWordWrap(True)
        layout.addWidget(message)

        form_layout = QFormLayout()
        self.confirm_edit = QLineEdit()
        form_layout.addRow(f"To confirm, please type the name of this volume (<b>{self.volume_name}</b>):", self.confirm_edit)
        layout.addLayout(form_layout)

        self.confirm_edit.textChanged.connect(self.check_match)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.delete_button = button_box.addButton("Delete Encrypted Volume", QDialogButtonBox.ButtonRole.DestructiveRole)
        self.delete_button.setEnabled(False)
        
        self.delete_button.clicked.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def check_match(self, text):
        self.delete_button.setEnabled(text == self.volume_name)


class PreferencesDialog(QDialog):
    """A dialog for setting application preferences."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.setMinimumWidth(400)

        self.settings = QSettings(ORGANIZATION_NAME, APPLICATION_NAME)
        layout = QVBoxLayout(self)

        # --- Close Behavior ---
        close_group = QGroupBox("On window close")
        close_layout = QVBoxLayout(close_group)
        self.minimize_radio = QRadioButton("Minimize to tray")
        self.quit_radio = QRadioButton("Quit application")
        close_layout.addWidget(self.minimize_radio)
        close_layout.addWidget(self.quit_radio)
        
        current_close_behavior = self.settings.value("close_behavior", "minimize", type=str)
        if current_close_behavior == "quit":
            self.quit_radio.setChecked(True)
        else:
            self.minimize_radio.setChecked(True)
            
        layout.addWidget(close_group)

        # --- Volume Creation ---
        creation_group = QGroupBox("Volume Creation")
        creation_layout = QFormLayout(creation_group)
        self.automount_new_cb = QCheckBox("Auto-mount new volumes after creation")
        self.automount_new_cb.setChecked(self.settings.value("automount_on_creation", True, type=bool))
        creation_layout.addRow(self.automount_new_cb)
        layout.addWidget(creation_group)

        # --- Dialog Buttons ---
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def accept(self):
        if self.quit_radio.isChecked():
            self.settings.setValue("close_behavior", "quit")
        else:
            self.settings.setValue("close_behavior", "minimize")
        
        self.settings.setValue("automount_on_creation", self.automount_new_cb.isChecked())
        super().accept()


class TerminalSetupDialog(QDialog):
    """Guides the user through enabling the optional embedded terminal."""
    def __init__(self, terminal_manager: TerminalManager, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Embedded Terminal Setup")
        self.setMinimumWidth(520)

        # Refresh detection right before showing the dialog to ensure fresh data.
        terminal_manager.refresh_detection()
        self.terminal_manager = terminal_manager
        detection = terminal_manager.detection

        layout = QVBoxLayout(self)
        intro = QLabel("The embedded terminal uses QTermWidget. It is optional and disabled unless you opt in.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        status_text = "QTermWidget detected" if detection.available else "QTermWidget not found"
        status = QLabel(f"Status: {status_text}")
        layout.addWidget(status)

        self.enable_checkbox = QCheckBox("Enable embedded terminal when available")
        self.enable_checkbox.setChecked(terminal_manager.enabled and detection.available)
        if not detection.available:
            self.enable_checkbox.setToolTip("Install QTermWidget first, then enable.")
        layout.addWidget(self.enable_checkbox)

        self.remember_checkbox = QCheckBox("Remember this choice and do not prompt again")
        self.remember_checkbox.setChecked(True)
        layout.addWidget(self.remember_checkbox)

        self.instructions_browser = QTextBrowser()
        self.instructions_browser.setReadOnly(True)
        self.instructions_browser.setOpenExternalLinks(True)
        self.instructions_browser.setHtml(self._build_detection_html(detection))
        layout.addWidget(self.instructions_browser)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _build_detection_html(self, detection):
        pkg_text = ", ".join(detection.suggested_packages) if detection.suggested_packages else "Not available"
        install_hint = detection.install_hint or "Install instructions unavailable for this platform."
        notes = detection.notes or ["Package names can differ by distribution. Verify before installing."]
        attempts = detection.import_attempts or []
        errors = detection.errors or []

        payload = json.dumps(detection.as_dict(), indent=2)
        note_lines = "".join(f"<li>{note}</li>" for note in notes)
        error_lines = "".join(f"<li>{err}</li>" for err in errors)
        attempt_lines = "".join(f"<li>{attempt}</li>" for attempt in attempts)

        html = f"""
        <h3>Detection</h3>
        <ul>
            <li><b>Provider:</b> {detection.provider_name or 'None detected'}</li>
            <li><b>Distro:</b> {detection.distro or 'Unknown'}</li>
            <li><b>Package manager:</b> {detection.package_manager or 'Unknown'}</li>
            <li><b>Suggested packages:</b> {pkg_text}</li>
            <li><b>Install hint:</b> {install_hint}</li>
        </ul>
        <h4>Notes</h4>
        <ul>{note_lines}</ul>
        <h4>Import attempts</h4>
        <ul>{attempt_lines}</ul>
        <h4>Errors</h4>
        <ul>{error_lines}</ul>
        <h4>Structured output</h4>
        <pre>{payload}</pre>
        """
        return html

    def should_enable(self) -> bool:
        return self.enable_checkbox.isChecked()

    def should_remember(self) -> bool:
        return self.remember_checkbox.isChecked()


class TerminalPanel(QFrame):
    """Container for the optional embedded terminal."""

    PREFERRED_HEIGHT = 260

    def __init__(self, terminal_manager: TerminalManager, request_setup_callback, parent=None):
        super().__init__(parent)
        self.terminal_manager = terminal_manager
        self.request_setup_callback = request_setup_callback
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._current_terminal: Optional[QWidget] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        header_layout = QHBoxLayout()
        self.status_label = QLabel("Terminal disabled")
        header_layout.addWidget(self.status_label)
        header_layout.addStretch()

        self.refresh_button = QToolButton()
        self.refresh_button.setText("Re-scan")
        self.refresh_button.clicked.connect(self.rescan_and_refresh)
        header_layout.addWidget(self.refresh_button)

        self.setup_button = QToolButton()
        self.setup_button.setText("Setup")
        self.setup_button.clicked.connect(self.request_setup_callback)
        header_layout.addWidget(self.setup_button)

        layout.addLayout(header_layout)

        self.stack = QStackedWidget()
        self.instructions_browser = QTextBrowser()
        self.instructions_browser.setOpenExternalLinks(True)
        self.instructions_browser.setReadOnly(True)
        self.stack.addWidget(self.instructions_browser)

        self.terminal_holder = QWidget()
        self.terminal_layout = QVBoxLayout(self.terminal_holder)
        self.terminal_layout.setContentsMargins(0, 0, 0, 0)
        self.terminal_layout.setSpacing(0)
        self.stack.addWidget(self.terminal_holder)

        layout.addWidget(self.stack)

        self.refresh()

    def refresh(self):
        detection = self.terminal_manager.detection
        if not self.terminal_manager.enabled:
            self.status_label.setText("Terminal disabled")
            self._show_instructions("Enable the embedded terminal from the setup dialog to use QTermWidget.")
            return

        if not detection.available:
            self.status_label.setText("QTermWidget missing")
            self._show_instructions(self._format_detection_html(detection))
            return

        widget = self.terminal_manager.create_or_get_widget(self)
        self._set_terminal_widget(widget)
        provider_name = detection.provider_name or "QTermWidget"
        self.status_label.setText(f"Embedded terminal active ({provider_name})")
        self.stack.setCurrentWidget(self.terminal_holder)

    def _show_instructions(self, html: str):
        self.instructions_browser.setHtml(html)
        self.stack.setCurrentWidget(self.instructions_browser)

    def _set_terminal_widget(self, widget: QWidget):
        # Clear existing widget to avoid stacking multiple instances.
        while self.terminal_layout.count():
            item = self.terminal_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        self.terminal_layout.addWidget(widget)
        self._current_terminal = widget

    def rescan_and_refresh(self):
        self.terminal_manager.refresh_detection()
        self.refresh()

    def _format_detection_html(self, detection):
        pkg_text = ", ".join(detection.suggested_packages) if detection.suggested_packages else "Unknown"
        install_hint = detection.install_hint or "Install instructions unavailable."
        payload = json.dumps(detection.as_dict(), indent=2)
        notes = detection.notes or ["QTermWidget is optional. The rest of Mithril will continue to function."]
        note_lines = "".join(f"<li>{note}</li>" for note in notes)
        return f"""
        <h3>QTermWidget not available</h3>
        <p>Mithril will run without it. Install to enable the embedded terminal.</p>
        <ul>
            <li><b>Distro:</b> {detection.distro or 'Unknown'}</li>
            <li><b>Package manager:</b> {detection.package_manager or 'Unknown'}</li>
            <li><b>Suggested packages:</b> {pkg_text}</li>
            <li><b>Install hint:</b> {install_hint}</li>
        </ul>
        <h4>Details</h4>
        <pre>{payload}</pre>
        """


class MithrilSetupWizard(QWizard):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Mithril Setup")
        self.addPage(WelcomePage())
        self.addPage(CreateVolumePage())
        self.addPage(SuccessPage())

    def accept(self):
        # This is called when the user clicks "Finish"
        super().accept()


class WelcomePage(QWizardPage):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Welcome to Mithril")
        self.setSubTitle("This wizard will guide you through setting up your first encrypted volume.")

        layout = QVBoxLayout(self)
        
        # --- Icon ---
        icon_label = QLabel()
        # A check for the existence of the icon file
        icon_path = os.path.join(ICONS_DIR, "icon_128.png")
        if os.path.exists(icon_path):
            pixmap = QPixmap(icon_path)
            icon_label.setPixmap(pixmap)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_label)

        prose = QLabel(
            "Mithril is a secure and elegant way to create and manage encrypted folders on your system.\n\n"
            "In just a few steps, you’ll create your first protected volume.\n\n"
            "You’ll be ready to mount, unlock, and use it in less than a minute."
        )
        prose.setWordWrap(True)
        layout.addWidget(prose)

class CreateVolumePage(QWizardPage):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Create Your First Volume")
        self.setSubTitle("The encrypted folder stores your encrypted data. The mount point is where your decrypted files will appear when unlocked.")

        layout = QGridLayout(self)
        layout.setColumnStretch(1, 1)

        self.label_edit = QLineEdit("Secure Folder")
        layout.addWidget(QLabel("Volume Label:"), 0, 0)
        layout.addWidget(self.label_edit, 0, 1, 1, 2)

        self.cipher_dir_combo = QComboBox()
        self.cipher_dir_combo.setEditable(True)
        self.cipher_dir_combo.addItems([os.path.expanduser("~/Encrypted"), os.path.expanduser("~/.local/share/gocryptfs/cipher")])
        self.cipher_dir_combo.setToolTip("Recommended location for the encrypted container. Secure, persistent, and private.")
        layout.addWidget(QLabel("Encrypted Folder:"), 1, 0)
        layout.addWidget(self.cipher_dir_combo, 1, 1)

        browse_cipher = QPushButton("Browse...")
        browse_cipher.clicked.connect(self.browse_cipher)
        layout.addWidget(browse_cipher, 1, 2)

        self.mount_point_combo = QComboBox()
        self.mount_point_combo.setEditable(True)
        self.mount_point_combo.addItems([os.path.expanduser("~/Secure"), os.path.expanduser("~/Private")])
        self.mount_point_combo.setToolTip("Recommended location for the decrypted view.")
        layout.addWidget(QLabel("Mount Point:"), 2, 0)
        layout.addWidget(self.mount_point_combo, 2, 1)

        browse_mount = QPushButton("Browse...")
        browse_mount.clicked.connect(self.browse_mount)
        layout.addWidget(browse_mount, 2, 2)

        self.perm_check = QCheckBox("Create directories and apply recommended permissions (chmod 700)")
        self.perm_check.setChecked(True)
        layout.addWidget(self.perm_check, 3, 0, 1, 3)

        self.registerField("volumeLabel*", self.label_edit)
        self.registerField("cipherDir*", self.cipher_dir_combo, "currentText", self.cipher_dir_combo.currentTextChanged)
        self.registerField("mountPoint*", self.mount_point_combo, "currentText", self.mount_point_combo.currentTextChanged)
        self.registerField("applyPerms", self.perm_check)

        # Manually connect signals to ensure the page's completeness is re-evaluated
        self.label_edit.textChanged.connect(self.completeChanged.emit)
        self.cipher_dir_combo.currentTextChanged.connect(self.completeChanged.emit)
        self.mount_point_combo.currentTextChanged.connect(self.completeChanged.emit)

    def browse_cipher(self):
        path = QFileDialog.getExistingDirectory(self, "Select Encrypted Folder")
        if path:
            self.cipher_dir_combo.setCurrentText(path)

    def browse_mount(self):
        path = QFileDialog.getExistingDirectory(self, "Select Mount Point")
        if path:
            self.mount_point_combo.setCurrentText(path)

    def isComplete(self):
        # Custom validation logic
        return bool(self.label_edit.text() and \
                    self.cipher_dir_combo.currentText() and \
                    self.mount_point_combo.currentText())

class SuccessPage(QWizardPage):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("All Done!")
        self.setSubTitle("Your secure volume has been created.")

        layout = QVBoxLayout(self)
        self.prose_label = QLabel()
        self.prose_label.setWordWrap(True)
        layout.addWidget(self.prose_label)

        # --- Post-Creation Actions ---
        self.mount_now_cb = QCheckBox("Mount this volume now")
        self.mount_now_cb.setChecked(True)
        layout.addWidget(self.mount_now_cb)

        self.open_folder_cb = QCheckBox("Open mount point in file manager after mounting")
        self.open_folder_cb.setChecked(True)
        layout.addWidget(self.open_folder_cb)
        
        self.mount_now_cb.toggled.connect(self.open_folder_cb.setEnabled)

        self.registerField("mountNow", self.mount_now_cb)
        self.registerField("openFolder", self.open_folder_cb)

        # Add a styled horizontal line
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line)

    def initializePage(self):
        volume_name = self.field("volumeLabel")
        self.prose_label.setText(
            f"Your first volume, '{volume_name}', is now ready.\n\n"
            "You can mount it from the main window to begin using it.\n\n"
            "Mithril will now launch the main interface."
        )

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("gocryptfs Manager")
        # Set application icon from bundled icons
        # A check for the existence of the icon file
        if sys.platform.startswith("win"):
            icon_path = os.path.join(ICONS_DIR, "mithril.ico")
        else:
            icon_path = os.path.join(ICONS_DIR, "icon_256.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.setMinimumSize(QSize(700, 500))
        self.settings = QSettings(ORGANIZATION_NAME, APPLICATION_NAME)
        self.terminal_manager = TerminalManager(self.settings, default_workdir=os.path.expanduser("~"))

        self.cached_password = None
        self.profiles = {}
        self.current_profile_name = "Default"
        self.mounted_paths = set()
        self.terminal_visible = self.terminal_manager.visible
        self.has_shown_tray_message = False
        self.is_quitting = False

        # The terminal container widget must be created before the main widgets are set up.
        self.terminal_panel = TerminalPanel(self.terminal_manager, self.show_terminal_setup_dialog, self)
        initial_height = TerminalPanel.PREFERRED_HEIGHT if self.terminal_visible else 0
        self.terminal_panel.setMaximumHeight(initial_height)
        self.terminal_container = self.terminal_panel

        self._setup_main_widgets()
        self._create_actions()
        self._create_menus()
        self._create_status_bar()
        self._create_tray_icon()

        self.load_profiles()
        self.update_mounted_list()

        # Set initial icon based on saved setting
        self.update_tray_icon_color(self.settings.value("use_monochrome_icon", False, type=bool))

        # Automount volumes after a short delay
        QTimer.singleShot(1500, self.automount_volumes)

    def _setup_main_widgets(self):
        self.central_widget = QWidget()
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        self.main_layout.addWidget(self.terminal_container)

        self.simplified_view = SimplifiedView(self)
        self.main_layout.addWidget(self.simplified_view)

        self.setCentralWidget(self.central_widget)
        
        # Restore advanced flags visibility
        expanded = self.settings.value("advanced_flags_expanded", False, type=bool)
        self.simplified_view.advanced_group.setChecked(expanded)

    def _create_actions(self):
        self.quit_action = QAction("&Quit", self)
        self.quit_action.setShortcut("Ctrl+Q")
        self.quit_action.triggered.connect(self.close_app)
        self.toggle_terminal_action = QAction("Toggle &Terminal", self, shortcut="F12", checkable=True)
        self.toggle_terminal_action.setChecked(self.terminal_visible)
        self.toggle_terminal_action.triggered.connect(self.toggle_terminal)
        self.clear_cache_action = QAction("Clear Cached Password", self)
        self.clear_cache_action.triggered.connect(self.clear_cached_password)

    def _create_menus(self):
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("&File")
        
        self.preferences_action = QAction("Preferences...", self)
        self.preferences_action.setShortcut("Ctrl+,")
        self.preferences_action.triggered.connect(self.show_preferences)
        file_menu.addAction(self.preferences_action)
        
        file_menu.addAction(self.clear_cache_action)
        file_menu.addSeparator()
        file_menu.addAction(self.quit_action)

        view_menu = menu_bar.addMenu("&View")
        view_menu.addAction(self.toggle_terminal_action)
        self.terminal_setup_action = QAction("Terminal Setup...", self)
        self.terminal_setup_action.triggered.connect(self.show_terminal_setup_dialog)
        view_menu.addAction(self.terminal_setup_action)

        help_menu = menu_bar.addMenu("&Help")
        self.security_guide_action = QAction("Security Best Practices", self)
        self.security_guide_action.setShortcut("Ctrl+H")
        self.security_guide_action.triggered.connect(self.show_security_guide)
        help_menu.addAction(self.security_guide_action)
        self.shortcuts_action = QAction("Keyboard Shortcuts", self, shortcut="F1")
        self.shortcuts_action.triggered.connect(self.show_shortcuts_guide)
        help_menu.addAction(self.shortcuts_action)
        help_menu.addSeparator()
        self.rerun_wizard_action = QAction("Run First-Time Setup...", self)
        self.rerun_wizard_action.setShortcut("Ctrl+R")
        self.rerun_wizard_action.triggered.connect(self.rerun_setup_wizard)
        help_menu.addAction(self.rerun_wizard_action)

    def show_security_guide(self):
        if not hasattr(self, "_security_guide_dialog") or self._security_guide_dialog is None:
            self._security_guide_dialog = SecurityGuideDialog(self)
            self._security_guide_dialog.finished.connect(lambda: setattr(self, "_security_guide_dialog", None))
        
        if self._security_guide_dialog.isVisible():
            self._security_guide_dialog.hide()
        else:
            self._security_guide_dialog.show()
            self._security_guide_dialog.activateWindow()

    def show_shortcuts_guide(self):
        if not hasattr(self, "_shortcuts_dialog") or self._shortcuts_dialog is None:
            self._shortcuts_dialog = ShortcutsDialog(self)
            self._shortcuts_dialog.finished.connect(lambda: setattr(self, "_shortcuts_dialog", None))

        if self._shortcuts_dialog.isVisible():
            self._shortcuts_dialog.hide()
        else:
            self._shortcuts_dialog.show()
            self._shortcuts_dialog.activateWindow()

    def show_preferences(self):
        if not hasattr(self, "_preferences_dialog") or self._preferences_dialog is None:
            self._preferences_dialog = PreferencesDialog(self)
            self._preferences_dialog.finished.connect(lambda: setattr(self, "_preferences_dialog", None))
        
        if self._preferences_dialog.isVisible():
            self._preferences_dialog.hide()
        else:
            self._preferences_dialog.show()
            self._preferences_dialog.activateWindow()

    def show_terminal_setup_dialog(self):
        dialog = TerminalSetupDialog(self.terminal_manager, self)
        result = dialog.exec()

        if dialog.should_remember():
            self.terminal_manager.mark_setup_seen()

        if result == QDialog.DialogCode.Accepted:
            enable = dialog.should_enable()
            self.terminal_manager.set_enabled(enable)
            self.terminal_panel.refresh()
            self._set_terminal_visibility(enable)
            if enable and not self.terminal_manager.has_working_provider():
                self.statusBar().showMessage("Terminal enabled but QTermWidget is missing. Showing setup instructions.", 6000)
        else:
            self.terminal_panel.refresh()

    def rerun_setup_wizard(self):
        if hasattr(self, "_setup_wizard") and self._setup_wizard.isVisible():
            self._setup_wizard.close()
            return

        reply = QMessageBox.question(self, "Run Setup Wizard",
                                     "This will guide you through creating a new volume in your 'Default' profile. Are you sure you want to continue?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.No:
            return

        self._setup_wizard = MithrilSetupWizard(self)
        if self._setup_wizard.exec() == QDialog.DialogCode.Accepted:
            volume_data = {
                "label": self._setup_wizard.field("volumeLabel"),
                "cipher_dir": self._setup_wizard.field("cipherDir"),
                "mount_point": self._setup_wizard.field("mountPoint"),
                "apply_perms": self._setup_wizard.field("applyPerms"),
                "auto_open_mount": self._setup_wizard.field("openFolder"),
                "automount_on_startup": False, # Default for new volumes
                "volume_type": "standard", # Default for new volumes
                "pin_to_tray": False, # Default for new volumes
            }

            # Switch to default profile to add the new volume
            self.simplified_view.profile_combo.setCurrentText("Default")
            self.add_volume_to_profile(volume_data)

    def _create_status_bar(self):
        self.statusBar().showMessage("Ready", 3000)

    def _create_tray_icon(self):
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_menu = QMenu()
        self.tray_icon.setContextMenu(self.tray_menu)
        self.tray_icon.show()
        self.tray_icon.activated.connect(self.on_tray_activated)

    def update_tray_icon_color(self, use_monochrome):
        if use_monochrome:
            source_pixmap = QPixmap(os.path.join(ICONS_DIR, "mithril.png"))
            mask = source_pixmap.mask()
            monochrome_pixmap = QPixmap(source_pixmap.size())
            monochrome_pixmap.fill(Qt.GlobalColor.white)
            monochrome_pixmap.setMask(mask)
            tray_icon = QIcon(monochrome_pixmap)
        else:
            if sys.platform.startswith("win"):
                icon_path = os.path.join(ICONS_DIR, "mithril.ico")
            else:
                icon_path = os.path.join(ICONS_DIR, "icon_256.png")
            tray_icon = QIcon(icon_path)
        
        self.tray_icon.setIcon(tray_icon)
        self.settings.setValue("use_monochrome_icon", use_monochrome)

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger: # Left-click
            self.toggle_window_visibility()

    def toggle_window_visibility(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.activateWindow()

    def update_tray_menu(self):
        self.tray_menu.clear()

        # --- Pinned Volumes ---
        has_pinned_volumes = False
        for profile_name, profile_data in self.profiles.items():
            for i, vol in enumerate(profile_data.get("volumes", [])):
                if vol.get("pin_to_tray"):
                    has_pinned_volumes = True
                    label = vol.get('label', f"Volume {i+1}")
                    is_mounted = vol.get('mount_point') in self.mounted_paths
                    icon = QIcon.fromTheme("media-eject" if is_mounted else "folder-blue")
                    action = QAction(icon, label, self)
                    action.triggered.connect(lambda checked, vol_id=i, p_name=profile_name: self.toggle_mount_from_tray(vol_id, p_name))
                    self.tray_menu.addAction(action)
        
        if has_pinned_volumes:
            self.tray_menu.addSeparator()

        # --- Application Actions ---
        self.tray_menu.addAction("Clear Cached Password", self.clear_cached_password)
        self.tray_menu.addSeparator()
        
        # --- Settings ---
        monochrome_action = QAction("Use Monochrome Icon", self, checkable=True)
        monochrome_action.setChecked(self.settings.value("use_monochrome_icon", False, type=bool))
        monochrome_action.triggered.connect(self.update_tray_icon_color)
        self.tray_menu.addAction(monochrome_action)
        self.tray_menu.addSeparator()

        show_hide_action = QAction("Show/Hide Window", self)
        show_hide_action.triggered.connect(self.toggle_window_visibility)
        self.tray_menu.addAction(show_hide_action)
        self.tray_menu.addAction(self.quit_action)

    def toggle_mount_from_tray(self, volume_id, profile_name):
        volume = self.profiles[profile_name]["volumes"][volume_id]
        if volume['mount_point'] in self.mounted_paths:
            self.unmount_volume(volume_id, profile_name)
        else:
            self.mount_volume(volume_id, profile_name)

    def run_gocryptfs_command(self, command, needs_password=False, success_message="", on_success=None, on_success_args=(), is_init=False, volume_id=None, profile_name=None):
        # Accept both list and string forms but prefer explicit argument arrays to avoid injection issues.
        command_args = command if isinstance(command, list) else shlex.split(command)
        command_display = command if isinstance(command, str) else shlex.join(command_args)

        if not command_args:
            QMessageBox.warning(self, "Command Error", "No command provided for gocryptfs operation.")
            return

        executable = command_args[0]
        if not can_exec(executable):
            self.statusBar().showMessage(f"Required binary '{executable}' was not found. Please install it and retry.", 6000)
            QMessageBox.warning(self, "Command Not Found", f"The command '{executable}' is required but was not found in PATH.")
            return

        safe_echo = format_cmd_for_echo(command_args)
        self.write_to_terminal(safe_echo)

        password = None
        if needs_password:
            if is_init:
                pwd_dialog = PasswordDialog(self)
                if pwd_dialog.exec() == QDialog.DialogCode.Accepted:
                    password_str = pwd_dialog.get_password()
                    if not password_str:
                        QMessageBox.warning(self, "Password Mismatch", "The passwords do not match.")
                        return
                    password = password_str.encode('utf-8')
                else:
                    self.statusBar().showMessage("Initialization cancelled.", 3000)
                    return
            else:
                if self.cached_password:
                    password = self.cached_password.encode('utf-8')
                else:
                    dialog = MountPasswordDialog(self)
                    if dialog.exec() == QDialog.DialogCode.Accepted:
                        password_str = dialog.get_password()
                        password = password_str.encode('utf-8')
                        if dialog.should_remember():
                            self.cached_password = password_str
                    else:
                        self.statusBar().showMessage("Operation cancelled.", 3000)
                        return

        try:
            result = subprocess.run(
                command_args, input=password, capture_output=True, check=False
            )

            if result.returncode == 0:
                self.statusBar().showMessage(success_message, 5000)
                self.tray_icon.showMessage(
                    "Success",
                    success_message,
                    QSystemTrayIcon.MessageIcon.Information,
                    3000,
                )
                if on_success:
                    on_success(*on_success_args)
            else:
                stderr_bytes = result.stderr or b""
                try:
                    error_output = stderr_bytes.decode('utf-8', errors="ignore").strip()
                except AttributeError:
                    error_output = str(stderr_bytes).strip()
                # --- Better Password Handling ---
                if "password incorrect" in error_output.lower() and volume_id is not None:
                    self.cached_password = None # Clear incorrect cached password
                    dialog = MountPasswordDialog(self, show_error=True)
                    if dialog.exec() == QDialog.DialogCode.Accepted:
                        # Retry mounting with the new password
                        self.mount_volume(volume_id, profile_name)
                    return # Stop further error processing

                error_msg = f"Error executing command (Code: {result.returncode})"
                self.statusBar().showMessage(error_msg, 8000)
                error_dialog = ErrorDialog(error_msg, error_output, self)
                error_dialog.exec()

        except FileNotFoundError as e:
            QMessageBox.critical(self, "Command Not Found", f"Could not execute '{command_args[0]}': {e}")
        except Exception as e:
            QMessageBox.critical(self, "Unexpected Error", f"An unexpected error occurred: {e}")

    def automount_volumes(self):
        """Iterate through all profiles and automount volumes."""
        for profile_name, profile_data in self.profiles.items():
            for i, volume in enumerate(profile_data.get("volumes", [])):
                # Standard automount on startup
                if volume.get("automount_on_startup"):
                    self.mount_volume(i, profile_name=profile_name)
                
                # USB automount (check if path exists)
                elif volume.get("volume_type") == "usb" and os.path.exists(volume.get("cipher_dir", "")):
                    self.mount_volume(i, profile_name=profile_name)

    def open_folder(self, path):
        """Opens the specified path in the default file manager."""
        try:
            subprocess.run(['xdg-open', path], check=True)
        except Exception as e:
            self.statusBar().showMessage(f"Failed to open folder: {e}", 5000)

    # --- Core Logic ---
    def update_mounted_list(self):
        """Checks system mounts and updates the UI accordingly."""
        self.mounted_paths.clear()
        try:
            result = subprocess.run(['mount'], capture_output=True, text=True, check=True)
            for line in result.stdout.splitlines():
                if 'fuse.gocryptfs' in line:
                    mount_point = line.split(' on ')[1].split(' type ')[0]
                    self.mounted_paths.add(mount_point)
        except Exception as e:
            self.statusBar().showMessage(f"Could not check mounts: {e}", 5000)

        self.refresh_volumes_list()
        self.update_tray_menu()

    def refresh_volumes_list(self):
        """Repopulates the favorite volumes list from the current profile."""
        self.simplified_view.volumes_list.clear()
        profile = self.profiles.get(self.current_profile_name, {})
        volumes = profile.get("volumes", [])
        for i, vol in enumerate(volumes):
            is_mounted = vol.get('mount_point') in self.mounted_paths
            icon = QIcon.fromTheme("emblem-ok" if is_mounted else "emblem-symbolic-link")
            item = QListWidgetItem(icon, f" {vol.get('label', 'Unnamed Volume')}")
            item.setToolTip(f"Mount Point: {vol.get('mount_point')}")
            item.setData(Qt.ItemDataRole.UserRole, i) # Store index as ID
            self.simplified_view.volumes_list.addItem(item)

    def on_volume_selected(self):
        volume_id = self.simplified_view.get_selected_volume_id()
        self.simplified_view.load_flags_for_volume(volume_id)

    def mount_volume(self, volume_id, profile_name=None, auto_open=None):
        # If profile_name is not provided, use the current one.
        if profile_name is None:
            profile_name = self.current_profile_name
            
        volume = self.profiles[profile_name]["volumes"][volume_id]
        cipher_dir, mount_point = volume["cipher_dir"], volume["mount_point"]

        # --- Attempt to unmount first to fix automount issues ---
        # This is non-blocking and we ignore the result. It's to clear stale mounts.
        subprocess.run(['umount', mount_point], capture_output=True)

        # --- Intelligent Directory Check ---
        if not os.path.isdir(cipher_dir) or not os.path.isdir(mount_point):
            reply = QMessageBox.question(self, "Directories Not Found",
                                         f"The required directories do not exist:\n\n"
                                         f"Encrypted: {cipher_dir}\n"
                                         f"Mount Point: {mount_point}\n\n"
                                         "Would you like to create them now with recommended permissions (700)?",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                try:
                    os.makedirs(cipher_dir, mode=0o700, exist_ok=True)
                    os.makedirs(mount_point, mode=0o700, exist_ok=True)
                    self.statusBar().showMessage("Created missing directories.", 3000)
                except Exception as e:
                    QMessageBox.critical(self, "Creation Error", f"Could not create directories: {e}")
                    return
            else:
                self.statusBar().showMessage("Mount cancelled.", 3000)
                return

        # --- Initialization Check ---
        is_new_volume = not os.path.exists(os.path.join(cipher_dir, "gocryptfs.conf"))
        if is_new_volume:
            init_command = ["gocryptfs", "-init", cipher_dir]
            # After successful initialization, recursively call mount_volume to mount it
            on_init_success = lambda: self.mount_volume(volume_id, profile_name, auto_open)
            self.run_gocryptfs_command(
                init_command,
                needs_password=True,
                is_init=True,
                success_message=f"Initialized volume '{volume['label']}'",
                on_success=on_init_success,
                volume_id=volume_id,
                profile_name=profile_name
            )
            return # Stop here, the recursive call will handle mounting

        if not os.access(mount_point, os.W_OK) or os.listdir(mount_point):
            QMessageBox.warning(self, "Mount Error", "Mount point must be an empty, writable directory.")
            return

        flags = volume.get("flags", {})
        extra_args = []
        if flags.get("allow_other"): extra_args.append("-allow_other")
        if flags.get("reverse"): extra_args.append("-reverse")
        scryptn_value, scryptn_valid = self._validated_scryptn(flags.get("scryptn"))
        if not scryptn_valid:
            return
        if scryptn_value:
            extra_args.extend(["-scryptn", scryptn_value])

        command_args = ["gocryptfs", *extra_args, cipher_dir, mount_point]
        
        on_success_callbacks = [self.update_mounted_list]
        
        # Determine whether to open the folder. The explicit `auto_open` parameter
        # from the wizard takes precedence over the saved volume setting.
        should_auto_open = auto_open if auto_open is not None else volume.get("auto_open_mount")
        if should_auto_open:
            on_success_callbacks.append(lambda: self.open_folder(mount_point))

        # We need a wrapper to call multiple functions on success
        def on_mount_success():
            for func in on_success_callbacks:
                func()

        self.run_gocryptfs_command(
            command_args, 
            True, 
            f"Mounted {volume['label']}", 
            on_mount_success,
            volume_id=volume_id,
            profile_name=profile_name
        )

    def unmount_volume(self, volume_id, profile_name=None):
        if profile_name is None:
            profile_name = self.current_profile_name
        volume = self.profiles[profile_name]["volumes"][volume_id]
        self.run_gocryptfs_command(
            ["umount", volume["mount_point"]],
            False, f"Unmounted {volume['label']}", self.update_mounted_list
        )

    def mount_all_volumes(self):
        for i, vol in enumerate(self.profiles[self.current_profile_name]["volumes"]):
            if vol['mount_point'] not in self.mounted_paths:
                self.mount_volume(i)

    def unmount_all_volumes(self):
        for i, vol in enumerate(self.profiles[self.current_profile_name]["volumes"]):
            if vol['mount_point'] in self.mounted_paths:
                self.unmount_volume(i)

    # --- Profile Management ---
    def new_profile(self):
        text, ok = QInputDialog.getText(self, 'New Profile', 'Enter new profile name:')
        if ok and text:
            if text in self.profiles:
                QMessageBox.warning(self, "Profile Exists", "A profile with this name already exists.")
                return
            self.profiles[text] = {"volumes": []}
            self.simplified_view.profile_combo.addItem(text)
            self.simplified_view.profile_combo.setCurrentText(text)
            self.save_current_profile()

    def rename_profile(self):
        old_name = self.current_profile_name
        if old_name == "Default":
            QMessageBox.warning(self, "Cannot Rename", "The 'Default' profile cannot be renamed.")
            return
        
        text, ok = QInputDialog.getText(self, 'Rename Profile', 'Enter new name:', text=old_name)
        if ok and text and text != old_name:
            if text in self.profiles:
                QMessageBox.warning(self, "Profile Exists", "A profile with this name already exists.")
                return
            self.profiles[text] = self.profiles.pop(old_name)
            self.current_profile_name = text
            self.simplified_view.profile_combo.blockSignals(True)
            self.simplified_view.profile_combo.removeItem(self.simplified_view.profile_combo.findText(old_name))
            self.simplified_view.profile_combo.addItem(text)
            self.simplified_view.profile_combo.setCurrentText(text)
            self.simplified_view.profile_combo.blockSignals(False)
            self.save_current_profile()

    def delete_profile(self):
        profile_name = self.current_profile_name
        if profile_name == "Default":
            QMessageBox.warning(self, "Cannot Delete", "The 'Default' profile cannot be deleted.")
            return

        reply = QMessageBox.question(self, "Confirm Delete", f"Are you sure you want to delete the profile '{profile_name}'?")
        if reply == QMessageBox.StandardButton.Yes:
            del self.profiles[profile_name]
            self.simplified_view.profile_combo.removeItem(self.simplified_view.profile_combo.findText(profile_name))
            self.simplified_view.profile_combo.setCurrentText("Default")
            self.save_current_profile()

    def load_profiles(self):
        os.makedirs(os.path.dirname(PROFILES_FILE), exist_ok=True)
        try:
            with open(PROFILES_FILE, 'r') as f:
                self.profiles = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.profiles = {"Default": {"volumes": []}}
        
        if "Default" not in self.profiles:
            self.profiles["Default"] = {"volumes": []}

        combo = self.simplified_view.profile_combo
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(self.profiles.keys())
        combo.blockSignals(False)

        self.current_profile_name = self.settings.value("last_profile", "Default")
        if self.current_profile_name not in self.profiles:
            self.current_profile_name = "Default"
        combo.setCurrentText(self.current_profile_name)

    def save_current_profile(self):
        import copy
        profile_name = self.simplified_view.profile_combo.currentText()
        if not profile_name: return

        # Deep copy to prevent accidental modification of the old profile
        current_volumes = self.profiles.get(self.current_profile_name, {}).get("volumes", [])
        self.profiles[profile_name] = {"volumes": copy.deepcopy(current_volumes)}
        self.current_profile_name = profile_name

        try:
            with open(PROFILES_FILE, 'w') as f:
                json.dump(self.profiles, f, indent=4)
            
            # --- Visual Feedback ---
            save_button = self.simplified_view.save_profile_button
            original_text = " Save"
            original_icon = QIcon.fromTheme("document-save")

            save_button.setText(" Saved!")
            save_button.setIcon(QIcon.fromTheme("emblem-ok"))
            save_button.setEnabled(False)

            # Revert the button back after 2 seconds
            QTimer.singleShot(2000, lambda: (
                save_button.setText(original_text),
                save_button.setIcon(original_icon),
                save_button.setEnabled(True)
            ))
            # --- End Visual Feedback ---

            if self.simplified_view.profile_combo.findText(profile_name) == -1:
                self.simplified_view.profile_combo.addItem(profile_name)

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not save profiles: {e}")
            self.statusBar().showMessage("Failed to save profile.", 5000)

    def switch_profile(self):
        new_profile = self.simplified_view.profile_combo.currentText()

        if new_profile in self.profiles:
            self.current_profile_name = new_profile
        else:
            reply = QMessageBox.question(
                self,
                "Confirm Profile Creation",
                f"Create new profile '{new_profile}'?"
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.profiles[new_profile] = {"volumes": []}
                self.current_profile_name = new_profile
                self.save_current_profile()
                self.simplified_view.refresh_volumes_list()
                self.statusBar().showMessage(
                    f"Created and switched to new profile '{new_profile}'.", 3000
                )
            else:
                self.simplified_view.profile_combo.setCurrentText(self.current_profile_name)

        self.settings.setValue("last_profile", new_profile)
        self.update_mounted_list()

    def add_volume_to_profile(self, data):
        try:
            cipher_dir, mount_point = data["cipher_dir"], data["mount_point"]
            
            # The directories must be created for a new volume, regardless of permissions.
            os.makedirs(cipher_dir, exist_ok=True)
            os.makedirs(mount_point, exist_ok=True)
            
            # Apply strict permissions only if the user checked the box.
            if data.get("apply_perms"):
                os.chmod(cipher_dir, 0o700)
                os.chmod(mount_point, 0o700)
                self.statusBar().showMessage("Created directories with recommended permissions.", 3000)
            else:
                self.statusBar().showMessage("Created directories.", 3000)
                
        except Exception as e:
            QMessageBox.critical(self, "Permissions Error", f"Could not create directories or set permissions: {e}")
            return None

        profile = self.profiles.setdefault(self.current_profile_name, {"volumes": []})
        profile["volumes"].append(data)
        self.refresh_volumes_list()
        self.update_tray_menu()
        self.save_current_profile()

        new_volume_id = len(profile["volumes"]) - 1
        
        # --- Post-Creation Actions ---
        # This callback chain ensures initialization happens before mounting.
        def mount_if_needed():
            if self.settings.value("automount_on_creation", True, type=bool):
                # Use a timer to allow the UI to settle before mounting
                QTimer.singleShot(200, lambda: self.mount_volume(new_volume_id, auto_open=data.get("auto_open_mount")))

        self.initialize_new_volume(new_volume_id, on_success=mount_if_needed)
        
        return new_volume_id

    def update_volume_in_profile(self, volume_id, data):
        self.profiles[self.current_profile_name]["volumes"][volume_id].update(data)
        self.refresh_volumes_list()
        self.update_tray_menu()
        self.save_current_profile()

    def remove_volume_from_profile(self, volume_id):
        del self.profiles[self.current_profile_name]["volumes"][volume_id]
        self.refresh_volumes_list()
        self.update_tray_menu()
        self.save_current_profile()

    def secure_delete_volume_from_disk(self, volume_id):
        volume = self.profiles[self.current_profile_name]["volumes"][volume_id]
        cipher_dir = volume.get("cipher_dir")
        mount_point = volume.get("mount_point")

        # Check if the directories exist before attempting deletion
        if not os.path.isdir(cipher_dir):
            QMessageBox.warning(self, "Directory Not Found", f"The encrypted directory does not exist:\n{cipher_dir}")
            return
        
        # Unmount the volume if it's currently mounted
        if mount_point in self.mounted_paths:
            self.unmount_volume(volume_id)
            # Give it a moment to unmount before trying to delete the folder
            QTimer.singleShot(500, lambda: self._proceed_with_secure_delete(volume_id))
        else:
            self._proceed_with_secure_delete(volume_id)

    def _proceed_with_secure_delete(self, volume_id):
        volume = self.profiles[self.current_profile_name]["volumes"][volume_id]
        cipher_dir = volume.get("cipher_dir")
        mount_point = volume.get("mount_point")

        try:
            home_dir = _resolve_path("~")
            allowed_roots = [home_dir]
            extra_roots = self.settings.value("safe_delete_roots", [])
            if isinstance(extra_roots, str):
                extra_roots = [extra_roots]
            for root in extra_roots or []:
                try:
                    allowed_roots.append(_resolve_path(str(root)))
                except Exception:
                    continue

            resolved_targets = []
            for target in [cipher_dir, mount_point]:
                if not target:
                    raise ValueError("Missing path for deletion.")
                path_obj = Path(target).expanduser()
                resolved = path_obj.resolve(strict=False)
                is_symlink = path_obj.is_symlink()
                if resolved == Path("/"):
                    raise ValueError("Refusing to delete the filesystem root.")
                if resolved == home_dir:
                    raise ValueError(f"Refusing to delete the home directory: {resolved}")
                # If not allowed, require typed confirmation of the exact path
                if not _is_path_allowed(resolved, allowed_roots):
                    typed, ok = QInputDialog.getText(
                        self,
                        "Confirm Path Outside Safe Roots",
                        f"The path\n{resolved}\nIs outside allowed roots.\n\nType the full resolved path to confirm deletion:",
                    )
                    if not ok or typed.strip() != str(resolved):
                        self.statusBar().showMessage("Deletion cancelled (path not confirmed).", 4000)
                        return
                resolved_targets.append({"resolved": resolved, "path": path_obj, "is_symlink": is_symlink})

            # Deduplicate while preserving order
            unique_targets = []
            seen = set()
            for entry in resolved_targets:
                key = str(entry["resolved"])
                if key in seen:
                    continue
                seen.add(key)
                unique_targets.append(entry)

            lines = []
            for entry in unique_targets:
                p = entry["path"]
                resolved = entry["resolved"]
                if entry["is_symlink"]:
                    label = f"{p} (symlink -> {resolved}; will remove link only)"
                else:
                    label = str(p if p.is_absolute() else resolved)
                    if resolved != p:
                        label += f" (resolved -> {resolved})"
                entry_count = _count_entries(resolved) if resolved.is_dir() and not entry["is_symlink"] else 0
                if entry_count:
                    lines.append(f"{label} (contains ~{entry_count} items)" if entry_count <= 500 else f"{label} (contains more than 500 items)")
                else:
                    lines.append(label)
            summary = "\n".join(lines)
            confirm = QMessageBox.question(
                self,
                "Confirm Delete",
                f"You are about to recursively delete the following directories:\n\n{summary}\n\nThis cannot be undone.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if confirm != QMessageBox.StandardButton.Yes:
                self.statusBar().showMessage("Deletion cancelled.", 3000)
                return

            for entry in unique_targets:
                resolved = entry["resolved"]
                path_obj = entry["path"]
                if entry["is_symlink"]:
                    self.write_to_terminal(f"Removing symlink: {path_obj} (target: {resolved})")
                    try:
                        path_obj.unlink()
                    except FileNotFoundError:
                        pass
                    continue

                if resolved.is_dir():
                    self.write_to_terminal(f"Deleting directory tree: {resolved}")
                    shutil.rmtree(resolved)

            audit_entries = []
            for entry in unique_targets:
                status = "deleted_symlink" if entry["is_symlink"] else "deleted_dir"
                audit_entries.append(f"{status} | profile={self.current_profile_name} | volume={volume.get('label','')} | path={entry['resolved']}")
            _append_delete_audit(audit_entries)

            self.statusBar().showMessage(f"Successfully deleted '{volume['label']}' and its mount point.", 5000)
            self.tray_icon.showMessage("Success", f"Securely deleted volume '{volume['label']}'.", QSystemTrayIcon.MessageIcon.Information, 3000)

            # After successful deletion, remove it from the profile
            self.remove_volume_from_profile(volume_id)

        except Exception as e:
            error_msg = f"Failed to delete volume: {e}"
            if hasattr(e, 'stderr') and e.stderr:
                error_msg += f"\n\n{e.stderr.decode('utf-8').strip()}"
            QMessageBox.critical(self, "Deletion Error", error_msg)
            self.statusBar().showMessage("Failed to delete volume.", 5000)

    def toggle_pin_volume(self, volume_id, pin_state):
        self.profiles[self.current_profile_name]["volumes"][volume_id]["pin_to_tray"] = pin_state
        self.save_current_profile()
        self.update_tray_menu()

    def update_volume_flags(self, volume_id, flags):
        if self.current_profile_name in self.profiles and \
           self.profiles[self.current_profile_name].get("volumes") and \
           volume_id < len(self.profiles[self.current_profile_name]["volumes"]):
            
            self.profiles[self.current_profile_name]["volumes"][volume_id]["flags"] = flags
            self.save_current_profile() # Save changes to flags immediately

    def _validated_scryptn(self, value: Optional[str]) -> tuple[Optional[str], bool]:
        if value is None or value == "":
            return None, True
        try:
            num = int(str(value), 10)
        except ValueError:
            self.statusBar().showMessage("Invalid scryptn value; it must be an integer.", 5000)
            return None, False
        if num < 10 or num > 28:
            self.statusBar().showMessage("scryptn must be between 10 and 28.", 5000)
            # Reset to default to avoid leaving a bad value lingering
            self.simplified_view.scryptn_edit.setText("16")
            return None, False
        return str(num), True

    def initialize_new_volume(self, volume_id, on_success=None):
        volume = self.profiles[self.current_profile_name]["volumes"][volume_id]
        cipher_dir = volume["cipher_dir"]

        # Check if already initialized
        if os.path.exists(os.path.join(cipher_dir, "gocryptfs.conf")):
            if on_success:
                on_success()
            return

        # This now runs synchronously and will block until the password is set or cancelled.
        init_command = ["gocryptfs", "-init", cipher_dir]
        self.run_gocryptfs_command(
            init_command,
            needs_password=True,
            is_init=True,
            success_message=f"Successfully initialized '{volume['label']}'",
            on_success=on_success
        )

    # --- Event Handlers and Utils ---
    def closeEvent(self, event):
        """Handle window close events."""
        close_behavior = self.settings.value("close_behavior", "minimize", type=str)

        if self.is_quitting:
            event.accept()
            return

        if close_behavior == "quit":
            self.close_app()
        else:
            # Otherwise, hide to tray and show a notification (once)
            event.ignore()
            self.hide()
            if not self.has_shown_tray_message:
                self.tray_icon.showMessage(
                    "Still Running",
                    "Mithril is running in the background. Use the tray icon to quit.",
                    QSystemTrayIcon.MessageIcon.Information,
                    2000
                )
                self.has_shown_tray_message = True

    def close_app(self):
        """Properly closes the application."""
        self.is_quitting = True
        self.save_current_profile() # Save on quit
        QApplication.instance().quit()

    def clear_cached_password(self):
        self.cached_password = None
        self.statusBar().showMessage("Session password cache cleared.", 3000)

    def write_to_terminal(self, command_str):
        """Write a command string to the embedded terminal."""
        self.terminal_manager.write(command_str)

    # --- Toggles ---
    def _animate_terminal_height(self, end_height):
        self.animation = QPropertyAnimation(self.terminal_container, b"maximumHeight")
        self.animation.setDuration(250)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.animation.setEndValue(end_height)
        self.animation.start()

    def _set_terminal_visibility(self, visible: bool, animate: bool = True):
        self.terminal_visible = visible
        self.terminal_manager.set_visible(visible)
        if hasattr(self, "toggle_terminal_action"):
            self.toggle_terminal_action.setChecked(visible)

        target_height = TerminalPanel.PREFERRED_HEIGHT if visible else 0
        if animate:
            self._animate_terminal_height(target_height)
        else:
            self.terminal_container.setMaximumHeight(target_height)

        if visible:
            self.terminal_panel.refresh()

    def toggle_terminal(self):
        if self.terminal_manager.should_prompt_setup():
            self.show_terminal_setup_dialog()
            return

        if not self.terminal_manager.enabled:
            self.show_terminal_setup_dialog()
            return

        new_visible = not self.terminal_visible
        self._set_terminal_visibility(new_visible)

        if new_visible and not self.terminal_manager.has_working_provider():
            self.statusBar().showMessage("Terminal provider missing; showing setup instructions.", 6000)
            self.terminal_panel.refresh()

def main():
    # A check for QApplication instance
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeMenuBar, False)

    if subprocess.run(['which', 'gocryptfs'], capture_output=True).returncode != 0:
        QMessageBox.critical(None, "Dependency Error", "Required app 'gocryptfs' not found.")
        sys.exit(1)

    # --- First Run Wizard ---
    if not os.path.exists(PROFILES_FILE):
        wizard = MithrilSetupWizard()
        if wizard.exec() == QDialog.DialogCode.Accepted:
            volume_data = {
                "label": wizard.field("volumeLabel"),
                "cipher_dir": wizard.field("cipherDir"),
                "mount_point": wizard.field("mountPoint"),
                "apply_perms": wizard.field("applyPerms"),
                "auto_open_mount": wizard.field("openFolder"),
                "automount_on_startup": False, # Default for new volumes
                "volume_type": "standard", # Default for new volumes
                "pin_to_tray": False, # Default for new volumes
            }
            try:
                cipher_dir = volume_data["cipher_dir"]
                mount_point = volume_data["mount_point"]

                # Always create directories, then conditionally apply permissions.
                os.makedirs(cipher_dir, exist_ok=True)
                os.makedirs(mount_point, exist_ok=True)
                
                if wizard.field("applyPerms"):
                    os.chmod(cipher_dir, 0o700)
                    os.chmod(mount_point, 0o700)
                    
            except Exception as e:
                QMessageBox.critical(None, "Permissions Error", f"Could not create directories or set permissions: {e}")

            profiles = {"Default": {"volumes": [volume_data]}}
            os.makedirs(os.path.dirname(PROFILES_FILE), exist_ok=True)
            with open(PROFILES_FILE, 'w') as f:
                json.dump(profiles, f, indent=4)

            # We need a main window instance to run the initialization and mounting
            window = MainWindow()
            new_volume_id = 0 # It's the first and only one
            window.initialize_new_volume(new_volume_id)
            
            if wizard.field("mountNow"):
                # Use a timer to ensure the main window is ready
                QTimer.singleShot(100, lambda: window.mount_volume(new_volume_id))

            window.show()
            sys.exit(app.exec())
        else:
            sys.exit(0)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
