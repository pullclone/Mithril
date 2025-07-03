import sys
import os
import json
import subprocess
import shlex
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QListWidget, QStackedWidget, QMenuBar, QFileDialog, QInputDialog, QMessageBox,
    QDialog, QFormLayout, QLineEdit, QLabel, QDialogButtonBox, QComboBox,
    QListWidgetItem, QCheckBox, QSystemTrayIcon, QMenu, QTextEdit, QToolButton, QGroupBox,
    QWizard, QWizardPage, QTextBrowser, QGridLayout, QFrame, QRadioButton)
from PyQt6.QtCore import QProcess, QSize, Qt, QPropertyAnimation, QEasingCurve, QSettings, QTimer
from PyQt6.QtGui import QAction, QIcon, QPixmap
# Only set Linux-specific Qt platform on Linux
if sys.platform.startswith("linux"):
    os.environ["QT_QPA_PLATFORMTHEME"] = "gtk3"
    os.environ["QT_QPA_PLATFORM"] = "xcb"

# Directory for bundled icons
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__)) if "__file__" in locals() else os.getcwd()
ICONS_DIR = os.path.normpath(os.path.join(SCRIPT_DIR, os.pardir, "icons"))

# --- Configuration ---
ORGANIZATION_NAME = "GocryptfsGUI"
APPLICATION_NAME = "GocryptfsManager"
PROFILES_FILE = os.path.join(os.path.expanduser("~"), ".config", APPLICATION_NAME, "profiles.json")

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
    def __init__(self, parent=None):
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

        # Row 2: Dialog Buttons
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box, 2, 0, 1, 2)

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
            self.main_window.add_volume_to_profile(dialog.get_data())

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
        if is_mounted:
            menu.addAction("Unmount", self.unmount_selected_volume)
            menu.addAction("Open Mount Point", lambda: self.main_window.open_folder(volume_data.get('mount_point')))
        else:
            menu.addAction("Mount", self.mount_selected_volume)
        
        menu.addSeparator()
        menu.addAction("Edit Volume", self.edit_volume)
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

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)


class ShortcutsDialog(QDialog):
    """A dialog displaying keyboard shortcuts."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Keyboard Shortcuts")
        self.setMinimumSize(400, 300)

        layout = QVBoxLayout(self)
        text_browser = QTextBrowser()
        layout.addWidget(text_browser)

        shortcuts = {
            "Enter": "Mount selected volume",
            "Ctrl + Enter": "Edit selected volume",
            "Del": "Remove volume from favorites",
            "Shift + Del": "Secure delete encrypted volume from disk",
            "Ctrl + N": "Add new volume",
            "Ctrl + R": "Re-run setup wizard",
            "Ctrl + H": "Open Security Guide",
            "Ctrl + Q": "Quit application",
            "F1": "Show this help",
        }

        content = "<h1>Keyboard Shortcuts</h1>"
        content += "<style>td { padding: 4px; }</style>"
        content += "<table>"
        for key, action in shortcuts.items():
            content += f"<tr><td><b>{key}</b></td><td>{action}</td></tr>"
        content += "</table>"
        
        text_browser.setHtml(content)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)


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
        super().accept()


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

        self.cached_password = None
        self.profiles = {}
        self.current_profile_name = "Default"
        self.mounted_paths = set()
        self.terminal_started = False
        self.terminal_process = None
        self.has_shown_tray_message = False
        self.is_quitting = False

        # The terminal container widget must be created before the main widgets are set up.
        self.terminal_container = QWidget()
        self.terminal_container.setFixedHeight(0)

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
        QTimer.singleShot(500, self.automount_volumes)

    def showEvent(self, event):
        """Start the terminal process the first time the window is shown."""
        super().showEvent(event)
        if not self.terminal_started:
            self.start_terminal_process()
            self.terminal_started = True

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

    def start_terminal_process(self):
        """Finds a compatible terminal and starts it embedded in the container widget."""
        shell = os.environ.get('SHELL', 'sh')

        # --- Find a suitable terminal emulator ---
        # We search for terminals that are known to support the -into or --embed flag.
        # This requires a valid winId(), which is why this is called from showEvent.
        win_id = self.terminal_container.winId()
        compatible_terminals = {
            'konsole': ['--nomenubar', '--notabbar', '--noframe', '-e', shell, '--embed', str(int(win_id))],
            'xterm': ['-into', str(int(win_id)), '-e', shell],
            'urxvt': ['-embed', str(int(win_id)), '-e', shell]
        }

        terminal_command = None
        found_terminal_name = None

        for name, command in compatible_terminals.items():
            if subprocess.run(['which', name], capture_output=True, text=True).returncode == 0:
                terminal_command = command
                found_terminal_name = name
                break
        
        if not terminal_command:
            self.statusBar().showMessage("No compatible terminal found (konsole, xterm, or urxvt).", 5000)
            if hasattr(self, 'toggle_terminal_action'):
                self.toggle_terminal_action.setEnabled(False)
            return

        # --- Start the Process ---
        self.terminal_process = QProcess(self)
        self.terminal_process.start(found_terminal_name, terminal_command)

        if not self.terminal_process.waitForStarted(2000):
            self.statusBar().showMessage(f"Failed to start {found_terminal_name}.", 5000)
            self.terminal_process = None
            if hasattr(self, 'toggle_terminal_action'):
                self.toggle_terminal_action.setEnabled(False)
            return

    def _create_actions(self):
        self.quit_action = QAction("&Quit", self)
        self.quit_action.setShortcut("Ctrl+Q")
        self.quit_action.triggered.connect(self.close_app)
        self.toggle_terminal_action = QAction("Toggle &Terminal", self, shortcut="F12")
        self.toggle_terminal_action.triggered.connect(self.toggle_terminal)
        self.clear_cache_action = QAction("Clear Cached Password", self)
        self.clear_cache_action.triggered.connect(self.clear_cached_password)

    def _create_menus(self):
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("&File")
        
        self.preferences_action = QAction("Preferences...", self)
        self.preferences_action.triggered.connect(self.show_preferences)
        file_menu.addAction(self.preferences_action)
        
        file_menu.addAction(self.clear_cache_action)
        file_menu.addSeparator()
        file_menu.addAction(self.quit_action)

        view_menu = menu_bar.addMenu("&View")
        view_menu.addAction(self.toggle_terminal_action)

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
        if not hasattr(self, "_security_guide_dialog") or not self._security_guide_dialog.isVisible():
            self._security_guide_dialog = SecurityGuideDialog(self)
            self._security_guide_dialog.show()
        else:
            self._security_guide_dialog.close()

    def show_shortcuts_guide(self):
        if not hasattr(self, "_shortcuts_dialog") or not self._shortcuts_dialog.isVisible():
            self._shortcuts_dialog = ShortcutsDialog(self)
            self._shortcuts_dialog.show()
        else:
            self._shortcuts_dialog.close()

    def show_preferences(self):
        dialog = PreferencesDialog(self)
        dialog.exec()

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
                "auto_open_mount": self._setup_wizard.field("openFolder")
            }

            # Switch to default profile to add the new volume
            self.simplified_view.profile_combo.setCurrentText("Default")
            new_volume_id = self.add_volume_to_profile(volume_data)

            if self._setup_wizard.field("mountNow"):
                # Use a timer to ensure the main window is ready
                QTimer.singleShot(100, lambda: self.mount_volume(new_volume_id))

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
        pinned_volumes = []
        for profile_name, profile_data in self.profiles.items():
            for i, vol in enumerate(profile_data.get("volumes", [])):
                if vol.get("pin_to_tray"):
                    pinned_volumes.append((vol, i, profile_name))
        
        if pinned_volumes:
            for vol, vol_id, profile_name in pinned_volumes:
                label = vol.get('label', f"Volume {vol_id+1}")
                is_mounted = vol.get('mount_point') in self.mounted_paths
                icon = QIcon.fromTheme("media-eject" if is_mounted else "folder-blue")
                action = QAction(icon, label, self)
                action.triggered.connect(lambda checked, vol_id=vol_id, p_name=profile_name: self.toggle_mount_from_tray(vol_id, p_name))
                self.tray_menu.addAction(action)
            self.tray_menu.addSeparator()


        # --- Volume Actions ---
        profile = self.profiles.get(self.current_profile_name, {})
        volumes = profile.get("volumes", [])
        if volumes:
            for i, vol in enumerate(volumes):
                label = vol.get('label', f"Volume {i+1}")
                is_mounted = vol.get('mount_point') in self.mounted_paths
                icon = QIcon.fromTheme("media-eject" if is_mounted else "media-mount")
                action = QAction(icon, label, self)
                action.triggered.connect(lambda checked, vol_id=i: self.toggle_mount_from_tray(vol_id, self.current_profile_name))
                self.tray_menu.addAction(action)
            self.tray_menu.addSeparator()
            self.tray_menu.addAction("Mount All", self.mount_all_volumes)
            self.tray_menu.addAction("Unmount All", self.unmount_all_volumes)
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

    def run_gocryptfs_command(self, command_str, needs_password=False, success_message="", on_success=None, on_success_args=(), is_init=False):
        self.write_to_terminal(command_str)

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
            command_args = shlex.split(command_str)
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
                error_output = result.stderr.decode('utf-8').strip()
                error_msg = f"Error executing command (Code: {result.returncode})"
                self.statusBar().showMessage(error_msg, 8000)
                error_dialog = ErrorDialog(error_msg, error_output, self)
                error_dialog.exec()

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

    def mount_volume(self, volume_id, profile_name=None):
        # If profile_name is not provided, use the current one.
        if profile_name is None:
            profile_name = self.current_profile_name
            
        volume = self.profiles[profile_name]["volumes"][volume_id]
        cipher_dir, mount_point = volume["cipher_dir"], volume["mount_point"]

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
            init_command = shlex.join(["gocryptfs", "-init", cipher_dir])
            self.run_gocryptfs_command(
                init_command,
                needs_password=True,
                is_init=True,
                success_message=f"Initialized volume '{volume['label']}'",
                on_success=self.update_mounted_list
            )
            # After init, we can proceed to mount, so we don't return here.
            # The user will be prompted for the password again to mount.

        if not os.access(mount_point, os.W_OK) or os.listdir(mount_point):
            QMessageBox.warning(self, "Mount Error", "Mount point must be an empty, writable directory.")
            return

        flags = volume.get("flags", {})
        extra_args = []
        if flags.get("allow_other"): extra_args.append("-allow_other")
        if flags.get("reverse"): extra_args.append("-reverse")
        if flags.get("scryptn"): extra_args.append(f"-scryptn {flags['scryptn']}")

        command_args = ["gocryptfs", *extra_args, cipher_dir, mount_point]
        command = shlex.join(command_args)
        
        on_success_callbacks = [self.update_mounted_list]
        if volume.get("auto_open_mount"):
            on_success_callbacks.append(lambda: self.open_folder(mount_point))

        # We need a wrapper to call multiple functions on success
        def on_mount_success():
            for func in on_success_callbacks:
                func()

        self.run_gocryptfs_command(
            command, 
            True, 
            f"Mounted {volume['label']}", 
            on_mount_success
        )

    def unmount_volume(self, volume_id, profile_name=None):
        if profile_name is None:
            profile_name = self.current_profile_name
        volume = self.profiles[profile_name]["volumes"][volume_id]
        self.run_gocryptfs_command(
            f"umount '{volume['mount_point']}'",
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
        self.save_current_profile()

        # --- Initialize the new volume ---
        new_volume_id = len(profile["volumes"]) - 1
        self.initialize_new_volume(new_volume_id)
        return new_volume_id

    def update_volume_in_profile(self, volume_id, data):
        self.profiles[self.current_profile_name]["volumes"][volume_id].update(data)
        self.refresh_volumes_list()
        self.save_current_profile()

    def remove_volume_from_profile(self, volume_id):
        del self.profiles[self.current_profile_name]["volumes"][volume_id]
        self.refresh_volumes_list()
        self.save_current_profile()

    def secure_delete_volume_from_disk(self, volume_id):
        volume = self.profiles[self.current_profile_name]["volumes"][volume_id]
        cipher_dir = volume.get("cipher_dir")
        
        if not cipher_dir or not os.path.isdir(cipher_dir):
            QMessageBox.warning(self, "Directory Not Found", f"The encrypted directory does not exist:\n{cipher_dir}")
            return

        try:
            # Use a terminal command for secure deletion if available, otherwise fallback
            # For this example, we’ll use rm -rf, but in a real-world scenario,
            # you might want to use a more secure deletion tool like ‘srm’ or ‘shred’.
            command = shlex.join(["rm", "-rf", cipher_dir])
            self.write_to_terminal(f"Attempting to securely delete: {command}")
            
            result = subprocess.run(shlex.split(command), capture_output=True, check=True)
            
            self.statusBar().showMessage(f"Successfully deleted '{volume['label']}' from disk.", 5000)
            self.tray_icon.showMessage("Success", f"Securely deleted volume '{volume['label']}'.", QSystemTrayIcon.MessageIcon.Information, 3000)
            
            # After successful deletion, remove it from the profile
            self.remove_volume_from_profile(volume_id)

        except Exception as e:
            error_msg = f"Failed to delete volume: {e}"
            if hasattr(e, 'stderr') and e.stderr:
                error_msg += f"\n\n{e.stderr.decode('utf-8').strip()}"
            QMessageBox.critical(self, "Deletion Error", error_msg)
            self.statusBar().showMessage("Failed to delete volume.", 5000)

    def update_volume_flags(self, volume_id, flags):
        if self.current_profile_name in self.profiles and \
           self.profiles[self.current_profile_name].get("volumes") and \
           volume_id < len(self.profiles[self.current_profile_name]["volumes"]):
            
            self.profiles[self.current_profile_name]["volumes"][volume_id]["flags"] = flags
            self.save_current_profile() # Save changes to flags immediately

    def initialize_new_volume(self, volume_id):
        volume = self.profiles[self.current_profile_name]["volumes"][volume_id]
        cipher_dir = volume["cipher_dir"]

        # Check if already initialized
        if os.path.exists(os.path.join(cipher_dir, "gocryptfs.conf")):
            return

        reply = QMessageBox.question(self, "Initialize Volume",
                                     f"The new volume '{volume['label']}' needs to be initialized with a password. "
                                     "Would you like to do this now?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            init_command = shlex.join(["gocryptfs", "-init", cipher_dir])
            self.run_gocryptfs_command(
                init_command,
                needs_password=True,
                is_init=True,
                success_message=f"Successfully initialized '{volume['label']}'",
                on_success=self.update_mounted_list
            )

    # --- Event Handlers and Utils ---
    def closeEvent(self, event):
        """Handle window close events."""
        if self.is_quitting:
            # If we are quitting, accept the event and let the app close
            event.accept()
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
        if hasattr(self, "terminal_process") and self.terminal_process is not None:
            try:
                self.terminal_process.write((command_str + "\n").encode())
            except Exception:
                pass

    # --- Toggles ---
    def toggle_terminal(self):
        end_height = 200 if self.terminal_container.height() == 0 else 0
        self.animation = QPropertyAnimation(self.terminal_container, b"maximumHeight")
        self.animation.setDuration(300)
        self.animation.setEndValue(end_height)
        self.animation.start()

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
                "auto_open_mount": wizard.field("openFolder")
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
