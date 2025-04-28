import sys
import os
import time
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QProgressBar, QComboBox, QMessageBox, QFileDialog, QTabWidget,
    QTextEdit, QSplashScreen, QToolTip, QGridLayout
)
from PyQt5.QtGui import QFont, QPixmap, QIcon, QPalette, QColor, QLinearGradient
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from rftx_flasherr import BMWFlasher
from tune_matcher import TuneMatcher
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("RFTX.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('RFTX.GUI')

class FlasherThread(QThread):
    """Thread for running BMWFlasher operations."""
    progress = pyqtSignal(float)
    log = pyqtSignal(str)
    finished = pyqtSignal(bool, str, dict)
    status = pyqtSignal(str)

    def __init__(self, flasher, operation, **kwargs):
        super().__init__()
        self.flasher = flasher
        self.operation = operation
        self.kwargs = kwargs

    def run(self):
        try:
            if self.operation == "connect":
                self.status.emit("Connecting to ECU...")
                success = self.flasher.connect(self.kwargs.get("port"))
                self.finished.emit(success, "Connected to ECU" if success else "Failed to connect to ECU", {})
            elif self.operation == "read_info":
                self.status.emit("Reading ECU information...")
                info = self.flasher.read_ecu_info()
                self.finished.emit(True, "ECU info read successfully", info)
            elif self.operation == "backup":
                self.status.emit("Backing up ECU...")
                def progress_callback(percent):
                    self.progress.emit(percent)
                backup_file = self.flasher.backup_ecu(self.kwargs.get("backup_path"), progress_callback)
                self.finished.emit(True, f"Backup saved to {backup_file}", {})
            elif self.operation == "flash":
                self.status.emit("Flashing ECU... Monitor the progress bar. Do not disconnect the cable or power during flashing.")
                def progress_callback(percent):
                    self.progress.emit(percent)
                self.flasher.flash_ecu(self.kwargs.get("flash_file"), progress_callback)
                self.finished.emit(True, "Flash completed successfully", {})
            elif self.operation == "read_dtcs":
                self.status.emit("Reading DTCs...")
                dtcs = self.flasher.read_dtcs()
                self.finished.emit(True, "DTCs read successfully", {"dtcs": dtcs})
            elif self.operation == "clear_dtcs":
                self.status.emit("Clearing DTCs...")
                success = self.flasher.clear_dtcs()
                self.finished.emit(success, "DTCs cleared successfully" if success else "Failed to clear DTCs", {})
            elif self.operation == "reset":
                self.status.emit("Resetting ECU...")
                success = self.flasher.reset_ecu()
                self.finished.emit(success, "ECU reset successfully" if success else "Failed to reset ECU", {})
        except Exception as e:
            self.finished.emit(False, f"Error: {str(e)}", {})

class RFTXMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.flasher = BMWFlasher()
        self.tune_matcher = TuneMatcher(tunes_directory="tunes")
        self.init_ui()
        self.setup_logging()
        self.thread = None
        self.ecu_info = {}

    def init_ui(self):
        self.setWindowTitle("RFTX TUNING – BMW ECU Flasher")
        self.setGeometry(100, 100, 1100, 800)
        self.setWindowIcon(QIcon("icon.png"))  # Optional: add an icon.png file

        # Set dark theme
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(28, 28, 28))
        palette.setColor(QPalette.WindowText, Qt.white)
        palette.setColor(QPalette.Base, QColor(38, 38, 38))
        palette.setColor(QPalette.AlternateBase, QColor(48, 48, 48))
        palette.setColor(QPalette.Text, Qt.white)
        palette.setColor(QPalette.Button, QColor(58, 58, 58))
        palette.setColor(QPalette.ButtonText, Qt.white)
        palette.setColor(QPalette.Highlight, QColor(0, 120, 255))
        self.setPalette(palette)

        # Central widget and layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # Header with enhanced banner
        header_widget = QWidget()
        header_widget.setStyleSheet("""
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0078FF, stop:1 #00BFFF);
            border-radius: 8px;
            padding: 10px;
        """)
        header_layout = QHBoxLayout(header_widget)
        header_label = QLabel("RFTX TUNING")
        header_label.setFont(QFont("Segoe UI", 24, QFont.Bold))
        header_label.setStyleSheet("color: white; padding: 5px;")
        header_layout.addWidget(header_label)
        header_layout.addStretch()
        main_layout.addWidget(header_widget)

        # Tabs
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #0078FF; background: #262626; margin: 5px; }
            QTabBar::tab { 
                background: #3A3A3A; 
                color: white; 
                padding: 10px 20px; 
                border-radius: 4px; 
                margin-right: 2px; 
            }
            QTabBar::tab:selected { 
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0078FF, stop:1 #00BFFF); 
                color: white; 
            }
            QTabBar::tab:hover { background: #4A4A4A; }
        """)
        main_layout.addWidget(self.tabs)

        # Button style
        button_style = """
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0078FF, stop:1 #00BFFF);
                color: white;
                border-radius: 5px;
                padding: 8px;
                font: 12pt "Segoe UI";
            }
            QPushButton:hover { background: #00BFFF; }
            QPushButton:disabled { background: #666666; color: #AAAAAA; }
        """

        # Home Tab
        home_widget = QWidget()
        home_layout = QVBoxLayout(home_widget)
        home_layout.setSpacing(10)
        home_label = QLabel("Connect to Your BMW ECU")
        home_label.setFont(QFont("Segoe UI", 16))
        home_label.setAlignment(Qt.AlignCenter)
        home_label.setStyleSheet("color: #FFFFFF; padding: 10px;")
        home_layout.addWidget(home_label)

        port_group = QWidget()
        port_layout = QHBoxLayout(port_group)
        port_label = QLabel("COM Port:")
        port_label.setFont(QFont("Segoe UI", 12))
        self.port_combo = QComboBox()
        self.port_combo.addItems(self.flasher.find_available_ports())
        self.port_combo.setStyleSheet("padding: 5px; background: #3A3A3A; color: white;")
        self.connect_button = QPushButton("Connect")
        self.connect_button.setStyleSheet(button_style)
        self.connect_button.setToolTip("Connect to the ECU using the selected COM port")
        self.connect_button.clicked.connect(self.on_connect_clicked)
        port_layout.addWidget(port_label)
        port_layout.addWidget(self.port_combo)
        port_layout.addWidget(self.connect_button)
        home_layout.addWidget(port_group)

        # ECU Info Display
        ecu_info_widget = QWidget()
        ecu_info_layout = QGridLayout(ecu_info_widget)
        ecu_info_layout.setSpacing(10)
        labels = ["VIN:", "ECU ID:", "Software Version:", "Hardware Version:", "ECU Type:", "Bootloader Mode:"]
        self.ecu_info_labels = {}
        for i, text in enumerate(labels):
            label = QLabel(text)
            label.setFont(QFont("Segoe UI", 12))
            label.setStyleSheet("color: #FFFFFF;")
            value = QLabel("Not connected")
            value.setFont(QFont("Segoe UI", 12))
            value.setStyleSheet("color: #BBBBBB; background: #3A3A3A; padding: 8px; border-radius: 4px;")
            ecu_info_layout.addWidget(label, i, 0)
            ecu_info_layout.addWidget(value, i, 1)
            self.ecu_info_labels[text.strip(":")] = value
        home_layout.addWidget(ecu_info_widget)
        home_layout.addStretch()
        self.tabs.addTab(home_widget, "Home")

        # Flash Tab
        flash_widget = QWidget()
        flash_layout = QVBoxLayout(flash_widget)
        flash_layout.setSpacing(10)
        flash_label = QLabel("Flash Your ECU")
        flash_label.setFont(QFont("Segoe UI", 16))
        flash_label.setAlignment(Qt.AlignCenter)
        flash_label.setStyleSheet("color: #FFFFFF; padding: 10px;")
        flash_layout.addWidget(flash_label)

        flash_button_group = QWidget()
        flash_button_layout = QHBoxLayout(flash_button_group)
        self.select_file_button = QPushButton("Select .bin File")
        self.select_file_button.setStyleSheet(button_style)
        self.select_file_button.setToolTip("Choose a .bin tune file to flash")
        self.select_file_button.clicked.connect(self.on_select_file_clicked)
        self.flash_button = QPushButton("Flash ECU")
        self.flash_button.setStyleSheet(button_style)
        self.flash_button.setToolTip("Start flashing the selected .bin file to the ECU")
        self.flash_button.setEnabled(False)
        self.flash_button.clicked.connect(self.on_flash_clicked)
        flash_button_layout.addWidget(self.select_file_button)
        flash_button_layout.addWidget(self.flash_button)
        flash_layout.addWidget(flash_button_group)

        self.selected_file_label = QLabel("No file selected")
        self.selected_file_label.setFont(QFont("Segoe UI", 12))
        self.selected_file_label.setStyleSheet("color: #BBBBBB; padding: 5px;")
        flash_layout.addWidget(self.selected_file_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setStyleSheet("""
            QProgressBar { 
                background: #3A3A3A; 
                border: 1px solid #0078FF; 
                border-radius: 5px; 
                text-align: center; 
                color: white; 
            }
            QProgressBar::chunk { 
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0078FF, stop:1 #00BFFF); 
            }
        """)
        flash_layout.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        self.status_label.setFont(QFont("Segoe UI", 12))
        self.status_label.setStyleSheet("color: #FF4444; padding: 5px;")
        self.status_label.setAlignment(Qt.AlignCenter)
        flash_layout.addWidget(self.status_label)

        self.tune_list = QTextEdit()
        self.tune_list.setReadOnly(True)
        self.tune_list.setPlaceholderText("Matching tunes will appear here after ECU info is read")
        self.tune_list.setStyleSheet("background: #3A3A3A; color: white; padding: 10px; border: 1px solid #0078FF;")
        flash_layout.addWidget(self.tune_list)
        flash_layout.addStretch()
        self.tabs.addTab(flash_widget, "Flash")

        # DTC Tab
        dtc_widget = QWidget()
        dtc_layout = QVBoxLayout(dtc_widget)
        dtc_layout.setSpacing(10)
        self.read_dtc_button = QPushButton("Read DTCs")
        self.read_dtc_button.setStyleSheet(button_style)
        self.read_dtc_button.setToolTip("Read Diagnostic Trouble Codes from the ECU")
        self.read_dtc_button.clicked.connect(self.on_read_dtc_clicked)
        self.clear_dtc_button = QPushButton("Clear DTCs")
        self.clear_dtc_button.setStyleSheet(button_style)
        self.clear_dtc_button.setToolTip("Clear all Diagnostic Trouble Codes from the ECU")
        self.clear_dtc_button.clicked.connect(self.on_clear_dtc_clicked)
        dtc_layout.addWidget(self.read_dtc_button)
        dtc_layout.addWidget(self.clear_dtc_button)
        self.dtc_list = QTextEdit()
        self.dtc_list.setReadOnly(True)
        self.dtc_list.setPlaceholderText("DTCs will appear here after reading")
        self.dtc_list.setStyleSheet("background: #3A3A3A; color: white; padding: 10px; border: 1px solid #0078FF;")
        dtc_layout.addWidget(self.dtc_list)
        dtc_layout.addStretch()
        self.tabs.addTab(dtc_widget, "DTC")

        # Logs Tab
        logs_widget = QWidget()
        logs_layout = QVBoxLayout(logs_widget)
        logs_layout.setSpacing(10)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setPlaceholderText("Operation logs will appear here")
        self.log_text.setStyleSheet("background: #3A3A3A; color: white; padding: 10px; border: 1px solid #0078FF;")
        logs_layout.addWidget(self.log_text)
        self.tabs.addTab(logs_widget, "Logs")

        # Settings Tab
        settings_widget = QWidget()
        settings_layout = QVBoxLayout(settings_widget)
        settings_layout.setSpacing(10)
        self.backup_button = QPushButton("Backup ECU")
        self.backup_button.setStyleSheet(button_style)
        self.backup_button.setToolTip("Create a backup of the ECU's current firmware")
        self.backup_button.clicked.connect(self.on_backup_clicked)
        self.reset_button = QPushButton("Reset ECU")
        self.reset_button.setStyleSheet(button_style)
        self.reset_button.setToolTip("Reset the ECU to its default state")
        self.reset_button.clicked.connect(self.on_reset_clicked)
        settings_layout.addWidget(self.backup_button)
        settings_layout.addWidget(self.reset_button)
        settings_layout.addStretch()
        self.tabs.addTab(settings_widget, "Settings")

        # Help Tab
        help_widget = QWidget()
        help_layout = QVBoxLayout(help_widget)
        help_layout.setSpacing(10)
        help_title = QLabel("RFTX TUNING – User Guide")
        help_title.setFont(QFont("Segoe UI", 16))
        help_title.setAlignment(Qt.AlignCenter)
        help_title.setStyleSheet("color: #FFFFFF; padding: 10px;")
        help_layout.addWidget(help_title)

        help_text = QTextEdit()
        help_text.setReadOnly(True)
        help_text.setStyleSheet("background: #3A3A3A; color: white; padding: 10px; border: 1px solid #0078FF;")
        help_text.setHtml("""
            <h2 style='color: #0078FF;'>How to Use RFTX TUNING</h2>
            <p>RFTX TUNING is a free tool for flashing BMW ECUs. Follow these steps to use the software safely and effectively.</p>
            <h3 style='color: #00BFFF;'>Requirements</h3>
            <ul>
                <li><b>Hardware</b>: K+DCAN cable, BMW vehicle with supported ECU (e.g., MSD80, MEVD17.2), stable 12V+ power supply.</li>
                <li><b>Files</b>: Valid .bin tune files in a <code>tunes/</code> directory. Optional: <code>tune_info.json</code> for tune matching.</li>
            </ul>
            <h3 style='color: #00BFFF;'>Step-by-Step Guide</h3>
            <ol>
                <li><b>Connect to ECU</b>:
                    <ul>
                        <li>Go to the <b>Home</b> tab.</li>
                        <li>Select your COM port (connected to the K+DCAN cable).</li>
                        <li>Click <b>Connect</b>. Ensure the vehicle’s battery is stable.</li>
                        <li>ECU information (VIN, ECU ID, etc.) will appear.</li>
                    </ul>
                </li>
                <li><b>Flash ECU</b>:
                    <ul>
                        <li>Go to the <b>Flash</b> tab.</li>
                        <li>Matching tunes will be listed based on ECU info.</li>
                        <li>Click <b>Select .bin File</b>, choose a .bin file, then click <b>Flash ECU</b>.</li>
                        <li>Ensure the battery is stable. Monitor the progress bar. Do not disconnect the cable or power during flashing.</li>
                    </ul>
                </li>
                <li><b>Backup ECU</b>:
                    <ul>
                        <li>Go to the <b>Settings</b> tab.</li>
                        <li>Click <b>Backup ECU</b>, choose a save location, and confirm.</li>
                        <li>Save the .bin file as a backup of the current ECU firmware.</li>
                    </ul>
                </li>
                <li><b>Read/Clear DTCs</b>:
                    <ul>
                        <li>Go to the <b>DTC</b> tab.</li>
                        <li>Click <b>Read DTCs</b> to view Diagnostic Trouble Codes.</li>
                        <li>Click <b>Clear DTCs</b> to remove them.</li>
                    </ul>
                </li>
                <li><b>Reset ECU</b>:
                    <ul>
                        <li>Go to the <b>Settings</b> tab.</li>
                        <li>Click <b>Reset ECU</b> to reset the ECU to its default state.</li>
                    </ul>
                </li>
                <li><b>View Logs</b>:
                    <ul>
                        <li>Go to the <b>Logs</b> tab to view operation details.</li>
                        <li>Logs are also saved to <code>RFTX.log</code>.</li>
                    </ul>
                </li>
            </ol>
            <h3 style='color: #00BFFF;'>Safety Warnings</h3>
            <ul>
                <li><b>Stable Power</b>: Ensure a stable 12V+ power supply (e.g., car battery or charger) during flashing to avoid ECU damage.</li>
                <li><b>Valid Tunes</b>: Use .bin files compatible with your ECU type (e.g., MSD80).</li>
                <li><b>Legal</b>: ECU flashing may void warranties or violate local laws. Use responsibly.</li>
            </ul>
            <h3 style='color: #00BFFF;'>Contact Support</h3>
            <p>For help, contact us at: rftxtuning@gmail.com</p>
        """)
        help_layout.addWidget(help_text)
        self.tabs.addTab(help_widget, "Help")

        # About Us Tab
        about_widget = QWidget()
        about_layout = QVBoxLayout(about_widget)
        about_layout.setSpacing(10)
        about_title = QLabel("About RFTX TUNING")
        about_title.setFont(QFont("Segoe UI", 16))
        about_title.setAlignment(Qt.AlignCenter)
        about_title.setStyleSheet("color: #FFFFFF; padding: 10px;")
        about_layout.addWidget(about_title)

        about_text = QTextEdit()
        about_text.setReadOnly(True)
        about_text.setStyleSheet("background: #3A3A3A; color: white; padding: 10px; border: 1px solid #0078FF;")
        about_text.setHtml("""
            <h2 style='color: #0078FF;'>About Us</h2>
            <p>RFTX TUNING is dedicated to making BMW ECU tuning accessible to everyone.</p>
            <p><b>Our Goal</b>: To make tuning free for everyone.</p>
            <p><b>Our Mission</b>: To provide a free tuning solution. Soon we will be adding more support for other engines.</p>
            <p><b>What's Next</b>: A new version will come out soon with enhanced features and broader compatibility.</p>
            <p>Contact: rftxtuning@gmail.com</p>
        """)
        about_layout.addWidget(about_text)
        self.tabs.addTab(about_widget, "About Us")

        # Footer
        footer = QLabel("RFTX TUNING – Free BMW ECU Flasher | v1.0 | Contact: rftxtuning@gmail.com")
        footer.setFont(QFont("Segoe UI", 9))
        footer.setAlignment(Qt.AlignCenter)
        footer.setStyleSheet("color: #666666; padding: 10px;")
        main_layout.addWidget(footer)

    def setup_logging(self):
        """Redirect logging to the GUI log tab."""
        class LogHandler(logging.Handler):
            def __init__(self, text_widget):
                super().__init__()
                self.text_widget = text_widget

            def emit(self, record):
                msg = self.format(record)
                self.text_widget.append(msg)
                self.text_widget.ensureCursorVisible()

        log_handler = LogHandler(self.log_text)
        log_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logger.addHandler(log_handler)

    def show_splash(self):
        """Show loading splash screen."""
        splash = QSplashScreen(QPixmap(400, 200))
        splash.setStyleSheet("background-color: #1C1C1C; color: #0078FF;")
        label = QLabel("RFTX TUNING\nLoading...", splash)
        label.setFont(QFont("Segoe UI", 18, QFont.Bold))
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("color: #0078FF;")
        label.resize(400, 200)
        splash.show()
        QApplication.processEvents()
        time.sleep(2)  # Simulate initialization
        splash.close()

    def on_connect_clicked(self):
        if self.thread and self.thread.isRunning():
            QMessageBox.warning(self, "Error", "Another operation is in progress")
            return
        port = self.port_combo.currentText()
        if not port:
            QMessageBox.warning(self, "Error", "Please select a COM port")
            return
        self.thread = FlasherThread(self.flasher, "connect", port=port)
        self.thread.finished.connect(self.on_connect_finished)
        self.thread.status.connect(self.status_label.setText)
        self.connect_button.setEnabled(False)
        self.thread.start()

    def on_connect_finished(self, success, message, data):
        self.connect_button.setEnabled(True)
        self.status_label.setText("")
        self.thread = None
        if success:
            QMessageBox.information(self, "Success", message)
            self.thread = FlasherThread(self.flasher, "read_info")
            self.thread.finished.connect(self.on_info_read)
            self.thread.status.connect(self.status_label.setText)
            self.thread.start()
        else:
            QMessageBox.critical(self, "Error", message)

    def on_info_read(self, success, message, data):
        self.status_label.setText("")
        self.thread = None
        if success:
            self.ecu_info = data
            self.ecu_info_labels["VIN"].setText(self.ecu_info.get('vin', 'Unknown'))
            self.ecu_info_labels["ECU ID"].setText(self.ecu_info.get('ecu_id', 'Unknown'))
            self.ecu_info_labels["Software Version"].setText(self.ecu_info.get('sw_version', 'Unknown'))
            self.ecu_info_labels["Hardware Version"].setText(self.ecu_info.get('hw_version', 'Unknown'))
            self.ecu_info_labels["ECU Type"].setText(self.ecu_info.get('ecu_type', 'Unknown'))
            self.ecu_info_labels["Bootloader Mode"].setText(str(self.ecu_info.get('in_bootloader', False)))
            tunes = self.tune_matcher.find_matching_tunes(
                self.ecu_info.get('vin', ''),
                self.ecu_info.get('ecu_id', ''),
                self.ecu_info.get('sw_version', '')
            )
            self.tune_list.clear()
            if not tunes:
                self.tune_list.append("No matching tunes found")
            else:
                for tune in tunes:
                    self.tune_list.append(
                        f"{tune['tune_type']} ({tune['match_confidence']}%): {tune['full_path']}"
                    )
        else:
            QMessageBox.critical(self, "Error", message)

    def on_select_file_clicked(self):
        if not self.flasher.connected:
            QMessageBox.warning(self, "Error", "Please connect to the ECU first")
            return
        file_name, _ = QFileDialog.getOpenFileName(self, "Select Tune File", "", "Binary Files (*.bin)")
        if file_name:
            if not os.path.exists(file_name) or os.path.getsize(file_name) == 0:
                QMessageBox.critical(self, "Error", "Invalid or empty .bin file")
                return
            self.selected_file_label.setText(f"Selected: {os.path.basename(file_name)}")
            self.flash_button.setEnabled(True)
            self.selected_file = file_name
        else:
            self.selected_file_label.setText("No file selected")
            self.flash_button.setEnabled(False)
            self.selected_file = None

    def on_flash_clicked(self):
        if self.thread and self.thread.isRunning():
            QMessageBox.warning(self, "Error", "Another operation is in progress")
            return
        if not self.flasher.connected:
            QMessageBox.warning(self, "Error", "Please connect to the ECU first")
            return
        if not hasattr(self, 'selected_file') or not self.selected_file:
            QMessageBox.critical(self, "Error", "Please select a .bin file first")
            return
        reply = QMessageBox.warning(
            self, "Battery Warning",
            "Ensure your vehicle's battery is fully charged or connected to a 12V+ charger. "
            "Power loss during flashing can damage the ECU. Do you want to proceed?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.thread = FlasherThread(self.flasher, "flash", flash_file=self.selected_file)
            self.thread.progress.connect(self.progress_bar.setValue)
            self.thread.finished.connect(self.on_operation_finished)
            self.thread.status.connect(self.status_label.setText)
            self.select_file_button.setEnabled(False)
            self.flash_button.setEnabled(False)
            self.thread.start()

    def on_backup_clicked(self):
        if self.thread and self.thread.isRunning():
            QMessageBox.warning(self, "Error", "Another operation is in progress")
            return
        if not self.flasher.connected:
            QMessageBox.warning(self, "Error", "Please connect to the ECU first")
            return
        file_name, _ = QFileDialog.getSaveFileName(self, "Save Backup File", "", "Binary Files (*.bin)")
        if file_name:
            self.thread = FlasherThread(self.flasher, "backup", backup_path=file_name)
            self.thread.progress.connect(self.progress_bar.setValue)
            self.thread.finished.connect(self.on_operation_finished)
            self.thread.status.connect(self.status_label.setText)
            self.backup_button.setEnabled(False)
            self.thread.start()

    def on_read_dtc_clicked(self):
        if self.thread and self.thread.isRunning():
            QMessageBox.warning(self, "Error", "Another operation is in progress")
            return
        if not self.flasher.connected:
            QMessageBox.warning(self, "Error", "Please connect to the ECU first")
            return
        self.thread = FlasherThread(self.flasher, "read_dtcs")
        self.thread.finished.connect(self.on_dtc_read)
        self.thread.status.connect(self.status_label.setText)
        self.read_dtc_button.setEnabled(False)
        self.thread.start()

    def on_dtc_read(self, success, message, data):
        self.read_dtc_button.setEnabled(True)
        self.status_label.setText("")
        self.thread = None
        if success:
            dtcs = data.get("dtcs", [])
            self.dtc_list.clear()
            if not dtcs:
                self.dtc_list.append("No DTCs found")
            else:
                for dtc in dtcs:
                    self.dtc_list.append(f"{dtc['text']} - Status: {bin(dtc['status'])[2:].zfill(8)}")
        else:
            QMessageBox.critical(self, "Error", message)

    def on_clear_dtc_clicked(self):
        if self.thread and self.thread.isRunning():
            QMessageBox.warning(self, "Error", "Another operation is in progress")
            return
        if not self.flasher.connected:
            QMessageBox.warning(self, "Error", "Please connect to the ECU first")
            return
        self.thread = FlasherThread(self.flasher, "clear_dtcs")
        self.thread.finished.connect(self.on_operation_finished)
        self.thread.status.connect(self.status_label.setText)
        self.clear_dtc_button.setEnabled(False)
        self.thread.start()

    def on_reset_clicked(self):
        if self.thread and self.thread.isRunning():
            QMessageBox.warning(self, "Error", "Another operation is in progress")
            return
        if not self.flasher.connected:
            QMessageBox.warning(self, "Error", "Please connect to the ECU first")
            return
        self.thread = FlasherThread(self.flasher, "reset")
        self.thread.finished.connect(self.on_operation_finished)
        self.thread.status.connect(self.status_label.setText)
        self.reset_button.setEnabled(False)
        self.thread.start()

    def on_operation_finished(self, success, message, data):
        self.select_file_button.setEnabled(True)
        self.flash_button.setEnabled(hasattr(self, 'selected_file') and self.selected_file is not None)
        self.backup_button.setEnabled(True)
        self.read_dtc_button.setEnabled(True)
        self.clear_dtc_button.setEnabled(True)
        self.reset_button.setEnabled(True)
        self.progress_bar.setValue(0)
        self.status_label.setText("")
        self.thread = None
        if success:
            QMessageBox.information(self, "Success", message)
        else:
            QMessageBox.critical(self, "Error", message)

    def closeEvent(self, event):
        self.flasher.disconnect()
        self.tune_matcher.cleanup()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = RFTXMainWindow()
    window.show_splash()
    window.show()
    sys.exit(app.exec_())