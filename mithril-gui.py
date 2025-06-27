import sys
import os
import json
import subprocess
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QListWidget, QStackedWidget, QMenuBar, QFileDialog, QInputDialog,
    QMessageBox, QDialog, QFormLayout, QLineEdit, QLabel, QDialogButtonBox,
    QComboBox, QListWidgetItem
)
from PyQt6.QtCore import (
    QProcess, QSize, Qt, QPropertyAnimation, QEasingCurve, QRect, QSettings
)
from PyQt6.QtGui import QAction, QIcon

# --- Configuration ---
# Use QSettings for persistent app settings
# On Linux, this usually saves to ~/.config/YourOrg/YourAppName.conf
ORGANIZATION_NAME = "GocryptfsGUI"
APPLICATION_NAME = "GocryptfsManager"
PROFILES_FILE = "gocryptfs_profiles.json"


class SettingsDialog(QDialog):
    """A dialog for application-wide settings."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.settings = QSettings(ORGANIZATION_NAME, APPLICATION_NAME)

        layout = QFormLayout(self)

        # Setting for default mount parent directory
        self.default_mount_location_edit = QLineEdit()
        self.default_mount_location_edit.setText(self.settings.value("default_mount_location", os.path.expanduser("~")))
        layout.addRow("Default Parent Mount Directory:", self.default_mount_location_edit)

        # Add more advanced options toggles here in the future
        self.advanced_toggle_label = QLabel("More settings can be added here.")
        font = self.advanced_toggle_label.font()
        font.setItalic(True)
        self.advanced_toggle_label.setFont(font)
        layout.addRow(self.advanced_toggle_label)


        # Dialog buttons
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def accept(self):
        """Save settings when OK is clicked."""
        self.settings.setValue("default_mount_location", self.default_mount_location_edit.text())
        super().accept()


class SimplifiedView(QWidget):
    """The default simplified GUI."""
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window  # To call methods on the main window

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        # --- Profile Management ---
        profile_layout = QHBoxLayout()
        profile_layout.addWidget(QLabel("Profile:"))
        self.profile_combo = QComboBox()
        self.profile_combo.setToolTip("Select or create a new settings profile")
        self.profile_combo.setEditable(True)
        self.profile_combo.currentIndexChanged.connect(self.main_window.load_selected_profile)
        
        self.save_profile_button = QPushButton(QIcon.fromTheme("document-save"), " Save")
        self.save_profile_button.setToolTip("Save current settings to the selected profile")
        self.save_profile_button.clicked.connect(self.main_window.save_current_profile)

        profile_layout.addWidget(self.profile_combo)
        profile_layout.addWidget(self.save_profile_button)
        layout.addLayout(profile_layout)
        
        # --- Core Actions ---
        button_layout = QHBoxLayout()
        self.create_button = QPushButton(QIcon.fromTheme("folder-new"), " Create Encrypted Folder")
        self.mount_button = QPushButton(QIcon.fromTheme("folder-open"), " Mount Folder")
        self.unmount_button = QPushButton(QIcon.fromTheme("media-removable"), " Unmount Selected")

        button_layout.addWidget(self.create_button)
        button_layout.addWidget(self.mount_button)
        button_layout.addWidget(self.unmount_button)
        layout.addLayout(button_layout)

        # --- Mounted Volumes List ---
        layout.addWidget(QLabel("<b>Currently Mounted Volumes:</b>"))
        self.mounted_list = QListWidget()
        self.mounted_list.setToolTip("Double-click to open in file manager")
        self.mounted_list.itemDoubleClicked.connect(self.open_in_file_manager)
        layout.addWidget(self.mounted_list)

        # --- Connect Signals ---
        self.create_button.clicked.connect(self.create_volume)
        self.mount_button.clicked.connect(self.mount_volume)
        self.unmount_button.clicked.connect(self.unmount_volume)

    def create_volume(self):
        cipher_dir = QFileDialog.getExistingDirectory(self, "Select a Folder to Encrypt")
        if cipher_dir:
            self.main_window.run_gocryptfs_command(
                f"gocryptfs -init '{cipher_dir}'",
                needs_password=False, # -init handles its own password prompts
                success_message=f"Successfully initialized encrypted folder at {cipher_dir}"
            )

    def mount_volume(self):
        cipher_dir = QFileDialog.getExistingDirectory(self, "Select Encrypted Folder to Mount")
        if cipher_dir:
            settings = QSettings(ORGANIZATION_NAME, APPLICATION_NAME)
            default_location = settings.value("default_mount_location", os.path.expanduser("~"))
            mount_point = QFileDialog.getExistingDirectory(self, "Select Mount Point (an empty folder)", default_location)
            if mount_point:
                 self.main_window.run_gocryptfs_command(
                    f"gocryptfs '{cipher_dir}' '{mount_point}'",
                    needs_password=True,
                    success_message=f"Mounted at {mount_point}",
                    on_success=lambda: self.main_window.update_mounted_list()
                )

    def unmount_volume(self):
        selected_item = self.mounted_list.currentItem()
        if not selected_item:
            QMessageBox.warning(self, "Warning", "Please select a mounted volume to unmount.")
            return
        mount_point = selected_item.data(Qt.ItemDataRole.UserRole) # Get path from item data
        self.main_window.run_gocryptfs_command(
            f"gocryptfs -unmount '{mount_point}'",
            needs_password=False,
            success_message=f"Unmounted {mount_point}",
            on_success=lambda: self.main_window.update_mounted_list()
        )

    def open_in_file_manager(self, item):
        mount_point = item.data(Qt.ItemDataRole.UserRole)
        # 'xdg-open' is the standard way to open a file/directory on Linux desktops
        subprocess.Popen(["xdg-open", mount_point])

class AdvancedView(QWidget):
    """Placeholder for the full-featured advanced GUI."""
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        label = QLabel("<h2>Advanced Full-Featured GUI</h2><p>This view could contain detailed file trees, gocryptfs flag toggles, performance stats, etc.</p>")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("gocryptfs Manager")
        self.setWindowIcon(QIcon.fromTheme("breeze")) # Use a standard KDE icon
        self.setMinimumSize(QSize(700, 500))
        self.settings = QSettings(ORGANIZATION_NAME, APPLICATION_NAME)

        self.profiles = {}
        self.current_profile_name = None

        # --- Terminal Setup ---
        self._setup_terminal()

        # --- Main Layout ---
        self.central_widget = QWidget()
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        self.main_layout.addWidget(self.terminal_container) # Add terminal container at the top

        # --- Stacked Widget for different views ---
        self.stacked_widget = QStackedWidget()
        self.simplified_view = SimplifiedView(self)
        self.advanced_view = AdvancedView()
        self.stacked_widget.addWidget(self.simplified_view)
        self.stacked_widget.addWidget(self.advanced_view)
        self.main_layout.addWidget(self.stacked_widget)
        
        self.setCentralWidget(self.central_widget)

        self._create_actions()
        self._create_menus()
        self._create_status_bar()

        self.load_profiles()
        self.update_mounted_list()

    def _setup_terminal(self):
        self.terminal_container = QWidget()
        self.terminal_container.setFixedHeight(0) # Start hidden
        self.terminal_layout = QVBoxLayout(self.terminal_container)
        self.terminal_layout.setContentsMargins(0, 0, 0, 0)
        
        self.terminal_process = QProcess(self)
        self.terminal_process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        
        # This is the key for embedding konsole
        # We find konsole and tell it to run fish and embed itself into our widget's window ID
        # Note: This is specific to KDE/konsole
        self.terminal_process.start("konsole", [
            "--nomenubar", "--notabbar", "--noframe",
            "-e", "fish",
            "--embed", str(int(self.terminal_container.winId()))
        ])
        
    def _create_actions(self):
        self.quit_action = QAction("&Quit", self)
        self.quit_action.triggered.connect(self.close)

        self.toggle_terminal_action = QAction("Toggle &Terminal", self)
        self.toggle_terminal_action.setShortcut("F12")
        self.toggle_terminal_action.triggered.connect(self.toggle_terminal)

        self.switch_view_action = QAction("Switch to &Advanced View", self)
        self.switch_view_action.setCheckable(True)
        self.switch_view_action.triggered.connect(self.switch_view)
        
        self.settings_action = QAction("&Settings...", self)
        self.settings_action.triggered.connect(self.show_settings_dialog)

    def _create_menus(self):
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("&File")
        file_menu.addAction(self.settings_action)
        file_menu.addSeparator()
        file_menu.addAction(self.quit_action)

        view_menu = menu_bar.addMenu("&View")
        view_menu.addAction(self.toggle_terminal_action)
        view_menu.addAction(self.switch_view_action)

    def _create_status_bar(self):
        self.statusBar().showMessage("Ready", 3000)

    def toggle_terminal(self):
        end_height = 200 if self.terminal_container.height() == 0 else 0
        self.animation = QPropertyAnimation(self.terminal_container, b"maximumHeight")
        self.animation.setDuration(300)
        self.animation.setStartValue(self.terminal_container.height())
        self.animation.setEndValue(end_height)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutQuart)
        self.animation.start()

    def switch_view(self):
        is_checked = self.switch_view_action.isChecked()
        if is_checked:
            self.stacked_widget.setCurrentWidget(self.advanced_view)
            self.switch_view_action.setText("Switch to &Simplified View")
        else:
            self.stacked_widget.setCurrentWidget(self.simplified_view)
            self.switch_view_action.setText("Switch to &Advanced View")

    def show_settings_dialog(self):
        dialog = SettingsDialog(self)
        if dialog.exec():
            self.statusBar().showMessage("Settings saved.", 3000)
            # Re-apply settings from profile in case they were changed
            self.load_selected_profile()

    def write_to_terminal(self, text):
        """Writes a command to the embedded terminal for visibility."""
        # The `\n` is important to execute the line in the shell
        full_command = f"{text}\n"
        self.terminal_process.write(full_command.encode('utf-8'))

    def run_gocryptfs_command(self, command, needs_password=False, success_message="", on_success=None):
        self.write_to_terminal(f"# Running from GUI: {command.split()[0]} ...")
        
        password = ""
        if needs_password:
            password, ok = QInputDialog.getText(self, "Password Required", "Enter password:", QLineEdit.EchoMode.Password)
            if not ok:
                self.statusBar().showMessage("Operation cancelled.", 3000)
                return
        
        # Use a separate process for the actual command execution
        process = QProcess(self)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        
        # Handle password input via stdin
        full_command_with_pass = f"echo '{password}' | {command}" if needs_password else command
        
        process.start("/bin/sh", ["-c", full_command_with_pass])
        process.waitForFinished(-1) # Block until command completes

        output = process.readAll().data().decode().strip()
        exit_code = process.exitCode()
        
        if exit_code == 0:
            self.statusBar().showMessage(success_message, 5000)
            if on_success:
                on_success()
        else:
            error_msg = f"Error executing command. Exit code: {exit_code}"
            self.statusBar().showMessage(error_msg, 8000)
            QMessageBox.critical(self, "Execution Error", f"{error_msg}\n\nOutput:\n{output}")
            
    def update_mounted_list(self):
        self.simplified_view.mounted_list.clear()
        try:
            # 'mount' command output is a reliable way to find gocryptfs mounts
            result = subprocess.run(['mount'], capture_output=True, text=True, check=True)
            for line in result.stdout.splitlines():
                if 'fuse.gocryptfs' in line:
                    parts = line.split()
                    mount_point = parts[2]
                    item = QListWidgetItem(QIcon.fromTheme("drive-harddisk"), f" {mount_point}")
                    item.setData(Qt.ItemDataRole.UserRole, mount_point) # Store full path
                    self.simplified_view.mounted_list.addItem(item)
        except Exception as e:
            self.statusBar().showMessage(f"Could not check mounts: {e}", 5000)

    def load_profiles(self):
        try:
            with open(PROFILES_FILE, 'r') as f:
                self.profiles = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.profiles = {
                "Default": {"default_mount_location": os.path.expanduser("~")}
            }
        
        combo = self.simplified_view.profile_combo
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(self.profiles.keys())
        combo.blockSignals(False)
        
        last_profile = self.settings.value("last_profile", "Default")
        if last_profile in self.profiles:
            combo.setCurrentText(last_profile)
        self.load_selected_profile()

    def save_current_profile(self):
        combo = self.simplified_view.profile_combo
        profile_name = combo.currentText()
        if not profile_name:
            QMessageBox.warning(self, "Warning", "Please enter a profile name.")
            return

        current_settings = {
            "default_mount_location": self.settings.value("default_mount_location")
        }
        self.profiles[profile_name] = current_settings
        
        try:
            with open(PROFILES_FILE, 'w') as f:
                json.dump(self.profiles, f, indent=4)
            self.statusBar().showMessage(f"Profile '{profile_name}' saved.", 3000)
            # If this is a new profile, make sure it's in the combobox
            if combo.findText(profile_name) == -1:
                combo.addItem(profile_name)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not save profiles: {e}")

    def load_selected_profile(self):
        profile_name = self.simplified_view.profile_combo.currentText()
        if profile_name in self.profiles:
            self.current_profile_name = profile_name
            profile_data = self.profiles[profile_name]
            
            # Apply settings from the profile
            self.settings.setValue("default_mount_location", profile_data.get("default_mount_location", os.path.expanduser("~")))
            self.settings.setValue("last_profile", profile_name)
            
            # Update any relevant UI elements here
            # (e.g., if there were toggles in the simplified view)
            self.statusBar().showMessage(f"Loaded profile '{profile_name}'.", 3000)


def main():
    # Check for dependencies
    for app in ['gocryptfs', 'konsole', 'fish']:
        if subprocess.run(['which', app], capture_output=True).returncode != 0:
            QMessageBox.critical(None, "Dependency Error", 
                f"The required application '{app}' was not found in your PATH.\n"
                f"Please install it. On Arch-based systems: sudo pacman -S {app}")
            sys.exit(1)

    app = QApplication(sys.argv)
    # Forcing the theme is not usually necessary on Plasma, as it's applied automatically.
    # But if needed, you can uncomment below. Breeze is the default on Plasma.
    # app.setStyle("Breeze") 
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
