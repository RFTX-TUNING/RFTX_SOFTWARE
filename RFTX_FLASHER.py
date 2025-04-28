import os
import sys
import time
import threading
import logging
import struct
import binascii
import re
import datetime
import hashlib
from typing import List, Dict, Optional, Tuple, Union, Callable
import json
from typing import List, Dict, Optional, Callable, Any
# For K+DCAN communication
import serial
import serial.tools.list_ports

# GUI imports
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                            QHBoxLayout, QPushButton, QLabel, QProgressBar, 
                            QComboBox, QMessageBox, QFileDialog, QFrame,
                            QSplashScreen, QListWidget, QListWidgetItem, 
                            QTextEdit, QGroupBox, QGridLayout, QSpacerItem,
                            QSizePolicy, QTabWidget, QCheckBox, QDialog)
from PyQt5.QtGui import QFont, QPixmap, QIcon, QColor, QPalette, QTextCursor
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QThread, QSize

# Import our tune matcher
from tune_matcher import TuneMatcher
# Safe path for log file
log_file_path = os.path.join(
    os.path.dirname(sys.executable if getattr(sys, 'frozen', False) else __file__),
    'rftx_flasher.log'
)

# Set up logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    filename=log_file_path)

logger = logging.getLogger('RFTX')

# Add console handler for debugging
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# BMW ECU communication constants
# CAN IDs
CAN_ID_REQUEST = 0x6F1  # Diagnostic request ID
CAN_ID_RESPONSE = 0x6F9  # Diagnostic response ID

# Protocol service IDs
# KWP2000 service IDs
KWP_START_DIAGNOSTIC_SESSION = 0x10
KWP_ECU_RESET = 0x11
KWP_CLEAR_DIAGNOSTIC_INFORMATION = 0x14
KWP_READ_DTC_BY_STATUS = 0x18
KWP_READ_ECU_IDENTIFICATION = 0x1A
KWP_READ_DATA_BY_LOCAL_ID = 0x21
KWP_READ_DATA_BY_COMMON_ID = 0x22
KWP_READ_MEMORY_BY_ADDRESS = 0x23
KWP_SECURITY_ACCESS = 0x27
KWP_WRITE_DATA_BY_LOCAL_ID = 0x3B
KWP_WRITE_MEMORY_BY_ADDRESS = 0x3D
KWP_TESTER_PRESENT = 0x3E
KWP_CONTROL_DTC_SETTING = 0x85
KWP_RESPONSE_ON_EVENT = 0x86

# UDS service IDs
UDS_DIAGNOSTIC_SESSION_CONTROL = 0x10
UDS_ECU_RESET = 0x11
UDS_CLEAR_DTC = 0x14
UDS_READ_DTC = 0x19
UDS_READ_DATA_BY_IDENTIFIER = 0x22
UDS_READ_MEMORY_BY_ADDRESS = 0x23
UDS_SECURITY_ACCESS = 0x27
UDS_COMMUNICATION_CONTROL = 0x28
UDS_WRITE_DATA_BY_IDENTIFIER = 0x2E
UDS_ROUTINE_CONTROL = 0x31
UDS_REQUEST_DOWNLOAD = 0x34
UDS_REQUEST_UPLOAD = 0x35
UDS_TRANSFER_DATA = 0x36
UDS_REQUEST_TRANSFER_EXIT = 0x37
UDS_WRITE_MEMORY_BY_ADDRESS = 0x3D
UDS_TESTER_PRESENT = 0x3E

# Response codes
POSITIVE_RESPONSE = 0x40
NEGATIVE_RESPONSE = 0x7F

# Negative response codes
NRC_GENERAL_REJECT = 0x10
NRC_SERVICE_NOT_SUPPORTED = 0x11
NRC_SUB_FUNCTION_NOT_SUPPORTED = 0x12
NRC_INCORRECT_MESSAGE_LENGTH = 0x13
NRC_CONDITIONS_NOT_CORRECT = 0x22
NRC_REQUEST_SEQUENCE_ERROR = 0x24
NRC_REQUEST_OUT_OF_RANGE = 0x31
NRC_SECURITY_ACCESS_DENIED = 0x33
NRC_INVALID_KEY = 0x35
NRC_EXCEEDED_NUMBER_OF_ATTEMPTS = 0x36
NRC_REQUIRED_TIME_DELAY_NOT_EXPIRED = 0x37
NRC_UPLOAD_DOWNLOAD_NOT_ACCEPTED = 0x70
NRC_TRANSFER_DATA_SUSPENDED = 0x71
NRC_GENERAL_PROGRAMMING_FAILURE = 0x72
NRC_WRONG_BLOCK_SEQUENCE_COUNTER = 0x73
NRC_RESPONSE_PENDING = 0x78

# Diagnostic session types
SESSION_DEFAULT = 0x01
SESSION_PROGRAMMING = 0x02
SESSION_EXTENDED = 0x03
SESSION_SAFETY_SYSTEM = 0x04

# Security access levels
SECURITY_LEVEL_PROGRAMMING = 0x01
SECURITY_LEVEL_EXTENDED = 0x05
SECURITY_LEVEL_SUPPLIER = 0x11

# BMW-specific routine IDs
ROUTINE_ERASE_MEMORY = 0xFF00
ROUTINE_CHECK_PROGRAMMING_DEPENDENCIES = 0xFF01
ROUTINE_ERASE_MEMORY_SECTOR = 0xFF02
ROUTINE_CHECK_PROGRAMMING_INTEGRITY = 0xFF03

# BMW ECU types and their memory maps
ECU_MEMORY_MAPS = {
    "MSD80": {
        "flash_start": 0x800000,
        "flash_size": 0x100000,  # 1MB
        "block_size": 0x1000,    # 4KB
        "sectors": [
            {"name": "Bootloader", "start": 0x800000, "size": 0x10000, "protected": True},
            {"name": "Calibration", "start": 0x810000, "size": 0x40000, "protected": False},
            {"name": "Program", "start": 0x850000, "size": 0xB0000, "protected": True}
        ],
        "protocol": "KWP2000",
        "security_algorithm": "xor",
        "seed_key_length": 2,
        "transfer_size": 0x200,  # 512 bytes
        "erase_required": True
    },
    "MSD81": {
        "flash_start": 0x800000,
        "flash_size": 0x100000,  # 1MB
        "block_size": 0x1000,    # 4KB
        "sectors": [
            {"name": "Bootloader", "start": 0x800000, "size": 0x10000, "protected": True},
            {"name": "Calibration", "start": 0x810000, "size": 0x40000, "protected": False},
            {"name": "Program", "start": 0x850000, "size": 0xB0000, "protected": True}
        ],
        "protocol": "KWP2000",
        "security_algorithm": "xor",
        "seed_key_length": 2,
        "transfer_size": 0x200,  # 512 bytes
        "erase_required": True
    },
    "MEVD17.2": {
        "flash_start": 0x800000,
        "flash_size": 0x200000,  # 2MB
        "block_size": 0x1000,    # 4KB
        "sectors": [
            {"name": "Bootloader", "start": 0x800000, "size": 0x10000, "protected": True},
            {"name": "Calibration", "start": 0x810000, "size": 0x80000, "protected": False},
            {"name": "Program", "start": 0x890000, "size": 0x170000, "protected": True}
        ],
        "protocol": "UDS",
        "security_algorithm": "crc",
        "seed_key_length": 4,
        "transfer_size": 0x800,  # 2KB
        "erase_required": True
    },
    "MG1": {
        "flash_start": 0x800000,
        "flash_size": 0x100000,  # 1MB
        "block_size": 0x1000,    # 4KB
        "sectors": [
            {"name": "Bootloader", "start": 0x800000, "size": 0x10000, "protected": True},
            {"name": "Calibration", "start": 0x810000, "size": 0x30000, "protected": False},
            {"name": "Program", "start": 0x840000, "size": 0xC0000, "protected": True}
        ],
        "protocol": "UDS",
        "security_algorithm": "crc",
        "seed_key_length": 4,
        "transfer_size": 0x400,  # 1KB
        "erase_required": True
    },
    "MD1": {
        "flash_start": 0x800000,
        "flash_size": 0x100000,  # 1MB
        "block_size": 0x1000,    # 4KB
        "sectors": [
            {"name": "Bootloader", "start": 0x800000, "size": 0x10000, "protected": True},
            {"name": "Calibration", "start": 0x810000, "size": 0x30000, "protected": False},
            {"name": "Program", "start": 0x840000, "size": 0xC0000, "protected": True}
        ],
        "protocol": "UDS",
        "security_algorithm": "crc",
        "seed_key_length": 4,
        "transfer_size": 0x400,  # 1KB
        "erase_required": True
    }
}

# Default memory map for unknown ECUs
DEFAULT_MEMORY_MAP = {
    "flash_start": 0x800000,
    "flash_size": 0x100000,  # 1MB
    "block_size": 0x1000,    # 4KB
    "sectors": [
        {"name": "Bootloader", "start": 0x800000, "size": 0x10000, "protected": True},
        {"name": "Calibration", "start": 0x810000, "size": 0x40000, "protected": False},
        {"name": "Program", "start": 0x850000, "size": 0xB0000, "protected": True}
    ],
    "protocol": "KWP2000",
    "security_algorithm": "xor",
    "seed_key_length": 2,
    "transfer_size": 0x200,  # 512 bytes
    "erase_required": True
}

class ISOTPHandler:
    """Handles ISO-TP (ISO 15765-2) protocol for CAN communication."""
    
    def __init__(self, port: serial.Serial, tx_id: int = CAN_ID_REQUEST, rx_id: int = CAN_ID_RESPONSE):
        self.port = port
        self.tx_id = tx_id
        self.rx_id = rx_id
        self.timeout = 5.0  # Default timeout in seconds
        self.fc_timeout = 1.0  # Flow control timeout
        self.st_min = 0  # Minimum separation time between consecutive frames
        self.block_size = 0  # Number of frames before flow control
        
    def send(self, data: bytes) -> Optional[bytes]:
        """Send data using ISO-TP protocol and return the response."""
        if len(data) <= 7:
            # Single frame
            return self._send_single_frame(data)
        else:
            # Multi-frame
            return self._send_multi_frame(data)
    
    def _send_single_frame(self, data: bytes) -> Optional[bytes]:
        """Send a single frame ISO-TP message."""
        # Single frame format: [0x0X, data] where X is the length
        frame = bytes([0x00 | len(data)]) + data
        
        # Pad to 8 bytes
        if len(frame) < 8:
            frame += b'\x00' * (8 - len(frame))
            
        # Send CAN frame
        self._send_can_frame(self.tx_id, frame)
        
        # Receive response
        return self._receive_isotp()
    
    def _send_multi_frame(self, data: bytes) -> Optional[bytes]:
        """Send a multi-frame ISO-TP message."""
        # First frame format: [0x1X, YY, data] where X is the high nibble of length, YY is the low byte
        data_length = len(data)
        first_frame = bytes([0x10 | ((data_length >> 8) & 0x0F), data_length & 0xFF]) + data[:6]
        
        # Send first frame
        self._send_can_frame(self.tx_id, first_frame)
        
        # Wait for flow control
        fc_frame = self._receive_can_frame(self.rx_id, timeout=self.fc_timeout)
        if not fc_frame or len(fc_frame) < 3 or fc_frame[0] != 0x30:
            logger.error("No valid flow control received")
            return None
            
        # Extract flow control parameters
        self.block_size = fc_frame[1]
        self.st_min = fc_frame[2]
        
        # Send consecutive frames
        sequence_number = 1
        data_index = 6
        
        while data_index < data_length:
            # Wait for minimum separation time
            if self.st_min <= 127:
                # milliseconds
                time.sleep(self.st_min / 1000.0)
            elif self.st_min >= 0xF1 and self.st_min <= 0xF9:
                # 100-900 microseconds (0xF1 = 100us, 0xF9 = 900us)
                time.sleep((self.st_min - 0xF0) * 100 / 1000000.0)
            
            # Prepare consecutive frame
            remaining = data[data_index:data_index+7]
            consecutive_frame = bytes([0x20 | (sequence_number & 0x0F)]) + remaining
            
            # Pad to 8 bytes
            if len(consecutive_frame) < 8:
                consecutive_frame += b'\x00' * (8 - len(consecutive_frame))
            
            # Send frame
            self._send_can_frame(self.tx_id, consecutive_frame)
            
            # Update counters
            sequence_number = (sequence_number + 1) & 0x0F
            data_index += 7
            
            # Check if we need to wait for another flow control frame
            if self.block_size != 0 and sequence_number % self.block_size == 0 and data_index < data_length:
                fc_frame = self._receive_can_frame(self.rx_id, timeout=self.fc_timeout)
                if not fc_frame or len(fc_frame) < 3 or fc_frame[0] != 0x30:
                    logger.error("No valid flow control received during consecutive frames")
                    return None
                    
                self.block_size = fc_frame[1]
                self.st_min = fc_frame[2]
        
        # Receive response
        return self._receive_isotp()
    
    def _receive_isotp(self) -> Optional[bytes]:
        """Receive an ISO-TP message."""
        # Receive first frame
        frame = self._receive_can_frame(self.rx_id, timeout=self.timeout)
        if not frame:
            logger.error("No response received")
            return None
            
        frame_type = frame[0] & 0xF0
        
        # Single frame
        if frame_type == 0x00:
            length = frame[0] & 0x0F
            return frame[1:1+length]
            
        # First frame of multi-frame response
        elif frame_type == 0x10:
            length = ((frame[0] & 0x0F) << 8) | frame[1]
            response_data = bytearray(frame[2:8])
            
            # Send flow control
            fc_frame = bytes([0x30, 0, 0])  # Flow control, block size 0, no delay
            fc_frame += b'\x00' * (8 - len(fc_frame))  # Pad to 8 bytes
            self._send_can_frame(self.tx_id, fc_frame)
            
            # Receive consecutive frames
            expected_sequence = 1
            
            while len(response_data) < length:
                cf_frame = self._receive_can_frame(self.rx_id, timeout=self.timeout)
                if not cf_frame:
                    logger.error("No consecutive frame received")
                    return None
                    
                if (cf_frame[0] & 0xF0) != 0x20:
                    logger.error(f"Invalid consecutive frame: {cf_frame.hex()}")
                    return None
                    
                sequence = cf_frame[0] & 0x0F
                if sequence != expected_sequence:
                    logger.error(f"Wrong sequence number: expected {expected_sequence}, got {sequence}")
                    return None
                    
                response_data.extend(cf_frame[1:8])
                expected_sequence = (expected_sequence + 1) & 0x0F
            
            return bytes(response_data[:length])
        
        # Unexpected frame type
        else:
            logger.error(f"Unexpected frame type: {frame_type:02X}")
            return None
    
    def _send_can_frame(self, can_id: int, data: bytes) -> None:
        """Send a CAN frame through the serial port."""
        # Format: [CAN ID (4 bytes), DLC (1 byte), data (up to 8 bytes)]
        can_frame = struct.pack(">I", can_id) + bytes([len(data)]) + data
        self.port.write(can_frame)
        self.port.flush()
        
    def _receive_can_frame(self, expected_id: int = None, timeout: float = None) -> Optional[bytes]:
        """Receive a CAN frame from the serial port."""
        if timeout is None:
            timeout = self.timeout
            
        # Save original timeout
        original_timeout = self.port.timeout
        self.port.timeout = timeout
        
        try:
            # Read CAN ID and DLC
            header = self.port.read(5)
            if len(header) != 5:
                logger.error("Timeout waiting for CAN frame header")
                return None
                
            # Extract CAN ID and DLC
            can_id = struct.unpack(">I", header[:4])[0]
            dlc = header[4]
            
            # Check if this is the expected ID
            if expected_id is not None and can_id != expected_id:
                logger.warning(f"Received unexpected CAN ID: 0x{can_id:X}, expected: 0x{expected_id:X}")
                return None
                
            # Read data
            data = self.port.read(dlc)
            if len(data) != dlc:
                logger.error(f"Timeout waiting for CAN data, expected {dlc} bytes")
                return None
                
            return data
            
        finally:
            # Restore original timeout
            self.port.timeout = original_timeout


class BMWFlasher:
    """Main class for BMW ECU flashing operations."""
    
    def __init__(self, port_name: str = None):
        self.port_name = port_name
        self.port = None
        self.isotp = None
        self.connected = False
        self.protocol = None
        self.security_level = 0
        self.session_type = SESSION_DEFAULT
        self.vin = None
        self.ecu_id = None
        self.sw_version = None
        self.hw_version = None
        self.ecu_type = None
        self.ecu_memory_map = None
        self.in_bootloader = False
        self.watchdog_timer = None
        self.last_activity = 0
        self.battery_voltage = 0.0
        
    def find_available_ports(self) -> List[str]:
        """Find available COM ports that might be K+DCAN adapters."""
        ports = []
        for port in serial.tools.list_ports.comports():
            # Common USB-to-Serial adapters used for K+DCAN
            if "USB" in port.description or "CH340" in port.description or "FTDI" in port.description:
                ports.append(port.device)
        return ports
    
    def connect(self, port_name: str = None) -> bool:
        """Connect to the ECU via the specified port."""
        if port_name:
            self.port_name = port_name
            
        if not self.port_name:
            available_ports = self.find_available_ports()
            if not available_ports:
                logger.error("No suitable COM ports found")
                return False
            self.port_name = available_ports[0]
            
        try:
            # Open serial port
            self.port = serial.Serial(
                port=self.port_name,
                baudrate=500000,  # 500kbps for CAN
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=1.0
            )
            
            # Initialize ISO-TP handler
            self.isotp = ISOTPHandler(self.port)
            
            # Try to establish communication
            if not self._initialize_communication():
                self.port.close()
                self.port = None
                self.isotp = None
                return False
                
            # Start watchdog timer
            self._start_watchdog()
            
            self.connected = True
            logger.info(f"Connected to ECU via {self.port_name}")
            return True
            
        except Exception as e:
            logger.error(f"Error connecting to ECU: {str(e)}")
            if self.port and self.port.is_open:
                self.port.close()
            self.port = None
            self.isotp = None
            return False
    
    def _initialize_communication(self) -> bool:
        """Initialize communication with the ECU and determine protocol."""
        # Try UDS first
        logger.info("Trying UDS protocol...")
        if self._try_uds_communication():
            self.protocol = "UDS"
            logger.info("UDS protocol detected")
            return True
            
        # Try KWP2000
        logger.info("Trying KWP2000 protocol...")
        if self._try_kwp_communication():
            self.protocol = "KWP2000"
            logger.info("KWP2000 protocol detected")
            return True
            
        logger.error("Failed to establish communication with ECU")
        return False
    
    def _try_uds_communication(self) -> bool:
        """Try to communicate using UDS protocol."""
        # Send tester present
        response = self._send_uds_command(UDS_TESTER_PRESENT, [0x00])
        if response and response[0] == UDS_TESTER_PRESENT + POSITIVE_RESPONSE:
            return True
            
        # Try diagnostic session control
        response = self._send_uds_command(UDS_DIAGNOSTIC_SESSION_CONTROL, [SESSION_DEFAULT])
        if response and response[0] == UDS_DIAGNOSTIC_SESSION_CONTROL + POSITIVE_RESPONSE:
            return True
            
        return False
    
    def _try_kwp_communication(self) -> bool:
        """Try to communicate using KWP2000 protocol."""
        # Send tester present
        response = self._send_kwp_command(KWP_TESTER_PRESENT, [0x00])
        if response and response[0] == KWP_TESTER_PRESENT + POSITIVE_RESPONSE:
            return True
            
        # Try start diagnostic session
        response = self._send_kwp_command(KWP_START_DIAGNOSTIC_SESSION, [0x81])  # BMW-specific session type
        if response and response[0] == KWP_START_DIAGNOSTIC_SESSION + POSITIVE_RESPONSE:
            return True
            
        return False
    
    def _send_uds_command(self, service_id: int, data: List[int]) -> Optional[bytes]:
        """Send a UDS command to the ECU and return the response."""
        if not self.port or not self.isotp:
            logger.error("Not connected to ECU")
            return None
            
        # Update last activity time
        self.last_activity = time.time()
        
        # Format UDS message
        message = bytes([service_id]) + bytes(data)
        
        try:
            # Send via ISO-TP
            response = self.isotp.send(message)
            
            # Handle negative response
            if response and len(response) >= 3 and response[0] == NEGATIVE_RESPONSE and response[1] == service_id:
                nrc = response[2]
                
                # Handle response pending
                if nrc == NRC_RESPONSE_PENDING:
                    # Wait for the actual response
                    pending_count = 0
                    while pending_count < 10:  # Limit to 10 retries
                        time.sleep(0.1)
                        response = self.isotp._receive_isotp()
                        if not response:
                            break
                        if response[0] != NEGATIVE_RESPONSE or response[2] != NRC_RESPONSE_PENDING:
                            break
                        pending_count += 1
                else:
                    logger.warning(f"Negative response for service 0x{service_id:02X}: NRC=0x{nrc:02X}")
            
            return response
            
        except Exception as e:
            logger.error(f"Error sending UDS command: {str(e)}")
            return None
    
    def _send_kwp_command(self, service_id: int, data: List[int]) -> Optional[bytes]:
        """Send a KWP2000 command to the ECU and return the response."""
        if not self.port or not self.isotp:
            logger.error("Not connected to ECU")
            return None
            
        # Update last activity time
        self.last_activity = time.time()
        
        # Format KWP2000 message
        message = bytes([service_id]) + bytes(data)
        
        try:
            # Send via ISO-TP
            response = self.isotp.send(message)
            
            # Handle negative response
            if response and len(response) >= 3 and response[0] == NEGATIVE_RESPONSE and response[1] == service_id:
                nrc = response[2]
                logger.warning(f"Negative response for service 0x{service_id:02X}: NRC=0x{nrc:02X}")
            
            return response
            
        except Exception as e:
            logger.error(f"Error sending KWP command: {str(e)}")
            return None
    
    def _start_watchdog(self):
        """Start the watchdog timer to keep the ECU awake."""
        if self.watchdog_timer:
            self.watchdog_timer.cancel()
            
        def watchdog_function():
            # Check if we need to send tester present
            current_time = time.time()
            if current_time - self.last_activity >= 2.0:  # Send every 2 seconds of inactivity
                if self.protocol == "UDS":
                    self._send_uds_command(UDS_TESTER_PRESENT, [0x00])
                else:
                    self._send_kwp_command(KWP_TESTER_PRESENT, [0x00])
                    
            # Check battery voltage periodically
            if current_time - self.last_activity >= 5.0:  # Check every 5 seconds
                self._check_battery_voltage()
                
            # Restart timer
            self.watchdog_timer = threading.Timer(1.0, watchdog_function)
            self.watchdog_timer.daemon = True
            self.watchdog_timer.start()
            
        # Start the timer
        self.watchdog_timer = threading.Timer(1.0, watchdog_function)
        self.watchdog_timer.daemon = True
        self.watchdog_timer.start()
    
    def _check_battery_voltage(self):
        """Check the battery voltage."""
        try:
            if self.protocol == "UDS":
                # UDS typically uses DID 0xF405 for battery voltage
                response = self._send_uds_command(UDS_READ_DATA_BY_IDENTIFIER, [0xF4, 0x05])
                if response and response[0] == UDS_READ_DATA_BY_IDENTIFIER + POSITIVE_RESPONSE:
                    # Extract voltage (usually 2 bytes representing voltage in 0.1V)
                    voltage_raw = (response[3] << 8) | response[4]
                    self.battery_voltage = voltage_raw / 10.0
            else:
                # KWP2000 typically uses local ID 0x10 for battery voltage
                response = self._send_kwp_command(KWP_READ_DATA_BY_LOCAL_ID, [0x10])
                if response and response[0] == KWP_READ_DATA_BY_LOCAL_ID + POSITIVE_RESPONSE:
                    # Extract voltage (usually 1 byte representing voltage in 0.1V)
                    voltage_raw = response[2]
                    self.battery_voltage = voltage_raw / 10.0
                    
            if self.battery_voltage < 12.0:
                logger.warning(f"Low battery voltage: {self.battery_voltage:.1f}V")
                
        except Exception as e:
            logger.error(f"Error checking battery voltage: {str(e)}")
    
    def disconnect(self):
        """Disconnect from the ECU."""
        if self.watchdog_timer:
            self.watchdog_timer.cancel()
            self.watchdog_timer = None
            
        if self.port and self.port.is_open:
            # Return to default session if needed
            if self.session_type != SESSION_DEFAULT:
                try:
                    if self.protocol == "UDS":
                        self._send_uds_command(UDS_DIAGNOSTIC_SESSION_CONTROL, [SESSION_DEFAULT])
                    else:
                        self._send_kwp_command(KWP_START_DIAGNOSTIC_SESSION, [0x81])  # Default for BMW
                except:
                    pass
                    
            self.port.close()
            
        self.port = None
        self.isotp = None
        self.connected = False
        self.security_level = 0
        self.session_type = SESSION_DEFAULT
        logger.info("Disconnected from ECU")
    
    def read_ecu_info(self) -> Dict:
        """Read ECU information (VIN, ECU ID, Software Version)."""
        if not self.connected and not self.connect():
            raise ConnectionError("Could not connect to ECU")
        
        ecu_info = {}
        
        # Read VIN
        if self.protocol == "KWP2000":
            # KWP2000 ECU identification
            response = self._send_kwp_command(KWP_READ_ECU_IDENTIFICATION, [0x90])  # VIN
            if response and response[0] == KWP_READ_ECU_IDENTIFICATION + POSITIVE_RESPONSE:
                self.vin = response[2:].decode('ascii', errors='ignore').strip('\x00')
                ecu_info['vin'] = self.vin
                
            # Read ECU ID
            response = self._send_kwp_command(KWP_READ_ECU_IDENTIFICATION, [0x92])  # ECU ID
            if response and response[0] == KWP_READ_ECU_IDENTIFICATION + POSITIVE_RESPONSE:
                self.ecu_id = response[2:].decode('ascii', errors='ignore').strip('\x00')
                ecu_info['ecu_id'] = self.ecu_id
                
            # Read Software Version
            response = self._send_kwp_command(KWP_READ_ECU_IDENTIFICATION, [0x94])  # SW Version
            if response and response[0] == KWP_READ_ECU_IDENTIFICATION + POSITIVE_RESPONSE:
                self.sw_version = response[2:].decode('ascii', errors='ignore').strip('\x00')
                ecu_info['sw_version'] = self.sw_version
                
            # Read Hardware Version
            response = self._send_kwp_command(KWP_READ_ECU_IDENTIFICATION, [0x93])  # HW Version
            if response and response[0] == KWP_READ_ECU_IDENTIFICATION + POSITIVE_RESPONSE:
                self.hw_version = response[2:].decode('ascii', errors='ignore').strip('\x00')
                ecu_info['hw_version'] = self.hw_version
                
        else:  # UDS
            # UDS Read Data By Identifier
            # VIN is typically DID 0xF190
            response = self._send_uds_command(UDS_READ_DATA_BY_IDENTIFIER, [0xF1, 0x90])
            if response and response[0] == UDS_READ_DATA_BY_IDENTIFIER + POSITIVE_RESPONSE:
                self.vin = response[3:].decode('ascii', errors='ignore').strip('\x00')
                ecu_info['vin'] = self.vin
                
            # ECU ID is typically DID 0xF18A
            response = self._send_uds_command(UDS_READ_DATA_BY_IDENTIFIER, [0xF1, 0x8A])
            if response and response[0] == UDS_READ_DATA_BY_IDENTIFIER + POSITIVE_RESPONSE:
                self.ecu_id = response[3:].decode('ascii', errors='ignore').strip('\x00')
                ecu_info['ecu_id'] = self.ecu_id
                
            # Software Version is typically DID 0xF189
            response = self._send_uds_command(UDS_READ_DATA_BY_IDENTIFIER, [0xF1, 0x89])
            if response and response[0] == UDS_READ_DATA_BY_IDENTIFIER + POSITIVE_RESPONSE:
                self.sw_version = response[3:].decode('ascii', errors='ignore').strip('\x00')
                ecu_info['sw_version'] = self.sw_version
                
            # Hardware Version is typically DID 0xF191
            response = self._send_uds_command(UDS_READ_DATA_BY_IDENTIFIER, [0xF1, 0x91])
            if response and response[0] == UDS_READ_DATA_BY_IDENTIFIER + POSITIVE_RESPONSE:
                self.hw_version = response[3:].decode('ascii', errors='ignore').strip('\x00')
                ecu_info['hw_version'] = self.hw_version
        
        # Determine ECU type from ECU ID
        if self.ecu_id:
            self.ecu_type = self._determine_ecu_type(self.ecu_id)
            ecu_info['ecu_type'] = self.ecu_type
            
            # Get memory map for this ECU type
            self.ecu_memory_map = self._get_memory_map(self.ecu_type)
            
        # Check if we're in bootloader mode
        self.in_bootloader = self._check_bootloader_mode()
        ecu_info['in_bootloader'] = self.in_bootloader
        
        logger.info(f"ECU Info: VIN={self.vin}, ECU ID={self.ecu_id}, SW={self.sw_version}, HW={self.hw_version}")
        logger.info(f"ECU Type: {self.ecu_type}, Bootloader Mode: {self.in_bootloader}")
        
        return ecu_info
    
    def _determine_ecu_type(self, ecu_id: str) -> str:
        """Determine the ECU type from the ECU ID."""
        ecu_id = ecu_id.upper()
        
        # Common BMW ECU types
        if "MSD80" in ecu_id:
            return "MSD80"
        elif "MSD81" in ecu_id:
            return "MSD81"
        elif "MEVD17.2" in ecu_id:
            return "MEVD17.2"
        elif "MG1" in ecu_id:
            return "MG1"
        elif "MD1" in ecu_id:
            return "MD1"
        
        # If we can't determine the exact type, try to match partially
        for ecu_type in ECU_MEMORY_MAPS.keys():
            if ecu_type in ecu_id:
                return ecu_type
                
        # Default to MSD80 if we can't determine the type
        logger.warning(f"Could not determine ECU type from ID: {ecu_id}, defaulting to MSD80")
        return "MSD80"
    
    def _get_memory_map(self, ecu_type: str) -> Dict:
        """Get the memory map for the specified ECU type."""
        return ECU_MEMORY_MAPS.get(ecu_type, DEFAULT_MEMORY_MAP)
    
    def _check_bootloader_mode(self) -> bool:
        """Check if the ECU is in bootloader mode."""
        # Different ECUs have different ways to check bootloader mode
        # This is a simplified implementation
        
        if self.protocol == "KWP2000":
            # In KWP2000, we can check by reading a specific local ID
            response = self._send_kwp_command(KWP_READ_DATA_BY_LOCAL_ID, [0x01])  # Status
            if response and response[0] == KWP_READ_DATA_BY_LOCAL_ID + POSITIVE_RESPONSE:
                # Check status byte (this is ECU-specific)
                if len(response) > 2 and (response[2] & 0x80):  # Bit 7 set = bootloader
                    return True
        else:  # UDS
            # In UDS, we can check by reading a specific DID
            response = self._send_uds_command(UDS_READ_DATA_BY_IDENTIFIER, [0xF1, 0x80])  # Boot Software ID
            if response and response[0] == UDS_READ_DATA_BY_IDENTIFIER + POSITIVE_RESPONSE:
                # If we can read the boot software ID, we're likely in bootloader mode
                return True
                
        # If we can't determine, assume we're not in bootloader mode
        return False
    
    def enter_programming_session(self) -> bool:
        """Enter programming session for flashing."""
        if not self.connected and not self.connect():
            logger.error("Could not connect to ECU")
            return False
            
        logger.info("Entering programming session...")
        
        if self.protocol == "KWP2000":
            # KWP2000 programming session
            response = self._send_kwp_command(KWP_START_DIAGNOSTIC_SESSION, [0x85])  # Programming session
            if not response or response[0] != KWP_START_DIAGNOSTIC_SESSION + POSITIVE_RESPONSE:
                logger.error("Failed to enter programming session")
                return False
                
            self.session_type = SESSION_PROGRAMMING
            logger.info("Entered KWP2000 programming session")
            return True
            
        else:  # UDS
            # UDS programming session
            response = self._send_uds_command(UDS_DIAGNOSTIC_SESSION_CONTROL, [SESSION_PROGRAMMING])
            if not response or response[0] != UDS_DIAGNOSTIC_SESSION_CONTROL + POSITIVE_RESPONSE:
                logger.error("Failed to enter programming session")
                return False
                
            self.session_type = SESSION_PROGRAMMING
            logger.info("Entered UDS programming session")
            return True
    
    def security_access(self) -> bool:
        """Gain security access to the ECU for flashing."""
        if self.security_level >= SECURITY_LEVEL_PROGRAMMING:
            return True  # Already have access
            
        if not self.connected and not self.connect():
            logger.error("Could not connect to ECU")
            return False
            
        # Make sure we're in programming session
        if self.session_type != SESSION_PROGRAMMING and not self.enter_programming_session():
            logger.error("Could not enter programming session for security access")
            return False
            
        logger.info("Requesting security access...")
        
        # Get the security algorithm and seed key length from the memory map
        security_algorithm = self.ecu_memory_map.get("security_algorithm", "xor")
        seed_key_length = self.ecu_memory_map.get("seed_key_length", 2)
        
        if self.protocol == "KWP2000":
            # KWP2000 security access
            # Request seed
            response = self._send_kwp_command(KWP_SECURITY_ACCESS, [0x01])  # Request seed
            if not response or response[0] != KWP_SECURITY_ACCESS + POSITIVE_RESPONSE:
                logger.error("Failed to request seed")
                return False
                
            # Extract seed
            seed_bytes = response[2:2+seed_key_length]
            seed = int.from_bytes(seed_bytes, byteorder='big')
            logger.info(f"Received seed: 0x{seed:X}")
            
            # Calculate key from seed
            key = self._calculate_key(seed, security_algorithm)
            logger.info(f"Calculated key: 0x{key:X}")
            
            # Send key
            key_bytes = key.to_bytes(seed_key_length, byteorder='big')
            response = self._send_kwp_command(KWP_SECURITY_ACCESS, [0x02] + list(key_bytes))
            if not response or response[0] != KWP_SECURITY_ACCESS + POSITIVE_RESPONSE:
                logger.error("Security access denied")
                return False
                
            self.security_level = SECURITY_LEVEL_PROGRAMMING
            logger.info("Security access granted")
            return True
            
        else:  # UDS
            # UDS security access
            # Request seed
            response = self._send_uds_command(UDS_SECURITY_ACCESS, [0x01])  # Request seed
            if not response or response[0] != UDS_SECURITY_ACCESS + POSITIVE_RESPONSE:
                logger.error("Failed to request seed")
                return False
                
            # Extract seed
            seed_bytes = response[2:2+seed_key_length]
            seed = int.from_bytes(seed_bytes, byteorder='big')
            logger.info(f"Received seed: 0x{seed:X}")
            
            # Calculate key from seed
            key = self._calculate_key(seed, security_algorithm)
            logger.info(f"Calculated key: 0x{key:X}")
            
            # Send key
            key_bytes = key.to_bytes(seed_key_length, byteorder='big')
            response = self._send_uds_command(UDS_SECURITY_ACCESS, [0x02] + list(key_bytes))
            if not response or response[0] != UDS_SECURITY_ACCESS + POSITIVE_RESPONSE:
                logger.error("Security access denied")
                return False
                
            self.security_level = SECURITY_LEVEL_PROGRAMMING
            logger.info("Security access granted")
            return True
    
    def _calculate_key(self, seed: int, algorithm: str) -> int:
        """Calculate the security access key from the seed using the specified algorithm."""
        if algorithm == "xor":
            
            key = ((seed ^ 0x5A3C) + 0x7F1B) & 0xFFFFFFFF
            return key
            
        elif algorithm == "crc":
           
            key = seed
            for i in range(32):  # 32-bit CRC
                if key & 0x80000000:
                    key = ((key << 1) ^ 0x4C11DB7) & 0xFFFFFFFF
                else:
                    key = (key << 1) & 0xFFFFFFFF
            return key
            
        else:
            # Default algorithm
            logger.warning(f"Unknown security algorithm: {algorithm}, using default")
            return ((seed ^ 0xA35C) + 0xF12B) & 0xFFFFFFFF
    
    def backup_ecu(self, backup_path: str = None, progress_callback: Callable = None) -> str:
        """Backup the ECU to a file and return the filename."""
        if not self.connected and not self.connect():
            raise ConnectionError("Could not connect to ECU")
            
        # Get ECU info if we don't have it yet
        if not self.vin or not self.ecu_id:
            self.read_ecu_info()
            
        # Get memory map
        if not self.ecu_memory_map:
            self.ecu_memory_map = self._get_memory_map(self.ecu_type)
            
        # Make sure we're in programming session
        if self.session_type != SESSION_PROGRAMMING and not self.enter_programming_session():
            raise RuntimeError("Could not enter programming session for backup")
            
        # Get security access if needed
        if self.security_level < SECURITY_LEVEL_PROGRAMMING and not self.security_access():
            raise RuntimeError("Could not get security access for backup")
            
        # Create a backup filename based on VIN and date
        if not backup_path:
            date_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_filename = f"BACKUP_{self.vin}_{self.ecu_type}_{date_str}.bin"
        else:
            backup_filename = backup_path
            
        logger.info(f"Starting ECU backup to {backup_filename}")
        
        # Open the backup file
        with open(backup_filename, 'wb') as backup_file:
            # Calculate total size for progress reporting
            total_size = sum(sector["size"] for sector in self.ecu_memory_map["sectors"])
            bytes_read = 0
            
            # Read each sector
            for sector in self.ecu_memory_map["sectors"]:
                sector_start = sector["start"]
                sector_size = sector["size"]
                sector_name = sector["name"]
                
                logger.info(f"Backing up sector: {sector_name} ({sector_size/1024:.1f} KB)")
                
                # Read the sector in blocks
                block_size = min(self.ecu_memory_map["transfer_size"], 0x1000)  # Max 4KB blocks
                for offset in range(0, sector_size, block_size):
                    address = sector_start + offset
                    size = min(block_size, sector_size - offset)
                    
                    # Read memory block
                    block_data = self._read_memory(address, size)
                    if not block_data:
                        raise RuntimeError(f"Failed to read memory at 0x{address:X}")
                        
                    # Write to backup file
                    backup_file.write(block_data)
                    
                    # Update progress
                    bytes_read += size
                    if progress_callback:
                        progress_callback(bytes_read / total_size * 100)
                        
                    # Send tester present to keep the session alive
                    if offset % 0x10000 == 0 and offset > 0:
                        if self.protocol == "UDS":
                            self._send_uds_command(UDS_TESTER_PRESENT, [0x00])
                        else:
                            self._send_kwp_command(KWP_TESTER_PRESENT, [0x00])
        
        logger.info(f"ECU backup completed: {backup_filename}")
        return backup_filename
    
    def _read_memory(self, address: int, size: int) -> Optional[bytes]:
        """Read memory from the ECU."""
        if self.protocol == "KWP2000":
            # KWP2000 read memory by address
            # Format: [address (4 bytes), size (1 byte)]
            addr_bytes = address.to_bytes(4, byteorder='big')
            response = self._send_kwp_command(KWP_READ_MEMORY_BY_ADDRESS, 
                                             list(addr_bytes) + [size])
            
            if not response or response[0] != KWP_READ_MEMORY_BY_ADDRESS + POSITIVE_RESPONSE:
                logger.error(f"Failed to read memory at 0x{address:X}")
                return None
                
            # Extract data (skip service ID and address)
            return response[6:]
            
        else:  # UDS
            # UDS read memory by address
            # Format: [address format (1 byte), address (variable), size format (1 byte), size (variable)]
            addr_format = 0x24  # 4 bytes
            addr_bytes = address.to_bytes(4, byteorder='big')
            size_format = 0x11  # 1 byte
            size_bytes = size.to_bytes(1, byteorder='big')
            
            response = self._send_uds_command(UDS_READ_MEMORY_BY_ADDRESS, 
                                             [addr_format] + list(addr_bytes) + [size_format] + list(size_bytes))
            
            if not response or response[0] != UDS_READ_MEMORY_BY_ADDRESS + POSITIVE_RESPONSE:
                logger.error(f"Failed to read memory at 0x{address:X}")
                return None
                
            # Extract data (skip service ID)
            return response[1:]
    
    def flash_ecu(self, flash_file: str, progress_callback: Callable = None) -> bool:
        """Flash the ECU with the specified file."""
        if not self.connected and not self.connect():
            raise ConnectionError("Could not connect to ECU")
            
        # Get ECU info if we don't have it yet
        if not self.vin or not self.ecu_id:
            self.read_ecu_info()
            
        # Get memory map
        if not self.ecu_memory_map:
            self.ecu_memory_map = self._get_memory_map(self.ecu_type)
            
        # Make sure we're in programming session
        if self.session_type != SESSION_PROGRAMMING and not self.enter_programming_session():
            raise RuntimeError("Could not enter programming session for flashing")
            
        # Get security access if needed
        if self.security_level < SECURITY_LEVEL_PROGRAMMING and not self.security_access():
            raise RuntimeError("Could not get security access for flashing")
            
        logger.info(f"Starting ECU flash with file: {flash_file}")
        
        # Read the flash file
        with open(flash_file, 'rb') as f:
            flash_data = f.read()
            
        # Verify file size
        if len(flash_data) > self.ecu_memory_map["flash_size"]:
            raise ValueError(f"Flash file too large: {len(flash_data)} bytes, max: {self.ecu_memory_map['flash_size']} bytes")
            
        # Calculate total size for progress reporting
        total_size = len(flash_data)
        bytes_written = 0
        
        # Flash each sector
        for sector in self.ecu_memory_map["sectors"]:
            sector_start = sector["start"]
            sector_size = sector["size"]
            sector_name = sector["name"]
            protected = sector.get("protected", False)
            
            # Skip protected sectors
            if protected:
                logger.info(f"Skipping protected sector: {sector_name}")
                continue
                
            # Calculate sector range in flash data
            data_start = sector_start - self.ecu_memory_map["flash_start"]
            data_end = data_start + sector_size
            
            # Skip if this sector is not in the flash data
            if data_start >= len(flash_data):
                logger.info(f"Skipping sector outside flash data: {sector_name}")
                continue
                
            # Get the data for this sector
            sector_data = flash_data[data_start:min(data_end, len(flash_data))]
            
            # If the sector data is smaller than the sector, pad with 0xFF
            if len(sector_data) < sector_size:
                sector_data += b'\xFF' * (sector_size - len(sector_data))
                
            logger.info(f"Flashing sector: {sector_name} ({len(sector_data)/1024:.1f} KB)")
            
            # Erase the sector first if required
            if self.ecu_memory_map.get("erase_required", True):
                if not self._erase_memory_sector(sector_start, sector_size):
                    raise RuntimeError(f"Failed to erase sector: {sector_name}")
                    
            # Flash the sector in blocks
            block_size = self.ecu_memory_map.get("transfer_size", 0x200)  # Default 512 bytes
            for offset in range(0, len(sector_data), block_size):
                address = sector_start + offset
                block = sector_data[offset:offset+block_size]
                
                # Write memory block
                if not self._write_memory(address, block):
                    raise RuntimeError(f"Failed to write memory at 0x{address:X}")
                    
                # Update progress
                bytes_written += len(block)
                if progress_callback:
                    progress_callback(bytes_written / total_size * 100)
                    
                # Send tester present to keep the session alive
                if offset % 0x10000 == 0 and offset > 0:
                    if self.protocol == "UDS":
                        self._send_uds_command(UDS_TESTER_PRESENT, [0x00])
                    else:
                        self._send_kwp_command(KWP_TESTER_PRESENT, [0x00])
        
        # Verify the flash
        logger.info("Verifying flash...")
        if not self._verify_flash(flash_data, progress_callback):
            raise RuntimeError("Flash verification failed")
            
        logger.info("ECU flash completed successfully")
        return True
    
    def _erase_memory_sector(self, address: int, size: int) -> bool:
        """Erase a memory sector in the ECU."""
        logger.info(f"Erasing memory sector at 0x{address:X}, size: 0x{size:X}")
        
        if self.protocol == "KWP2000":
            # KWP2000 typically uses a routine control for erasing
            # Format depends on the ECU, but typically: [routine ID (2 bytes), address (4 bytes), size (4 bytes)]
            routine_id = 0x00  # Erase routine
            addr_bytes = address.to_bytes(4, byteorder='big')
            size_bytes = size.to_bytes(4, byteorder='big')
            
            response = self._send_kwp_command(0x31, [routine_id] + list(addr_bytes) + list(size_bytes))
            if not response or response[0] != 0x31 + POSITIVE_RESPONSE:
                logger.error(f"Failed to erase memory sector at 0x{address:X}")
                return False
                
            return True
            
        else:  # UDS
            # UDS uses routine control for erasing
            # Format: [routine control type (1 byte), routine ID (2 bytes), parameters]
            routine_control_type = 0x01  # Start routine
            routine_id_bytes = ROUTINE_ERASE_MEMORY_SECTOR.to_bytes(2, byteorder='big')
            addr_bytes = address.to_bytes(4, byteorder='big')
            size_bytes = size.to_bytes(4, byteorder='big')
            
            response = self._send_uds_command(UDS_ROUTINE_CONTROL, 
                                             [routine_control_type] + list(routine_id_bytes) + 
                                             list(addr_bytes) + list(size_bytes))
            
            if not response or response[0] != UDS_ROUTINE_CONTROL + POSITIVE_RESPONSE:
                logger.error(f"Failed to erase memory sector at 0x{address:X}")
                return False
                
            return True
    
    def _write_memory(self, address: int, data: bytes) -> bool:
        """Write data to ECU memory."""
        if self.protocol == "KWP2000":
            # KWP2000 write memory by address
            # Format: [address (4 bytes), data]
            addr_bytes = address.to_bytes(4, byteorder='big')
            
            response = self._send_kwp_command(KWP_WRITE_MEMORY_BY_ADDRESS, 
                                             list(addr_bytes) + list(data))
            
            if not response or response[0] != KWP_WRITE_MEMORY_BY_ADDRESS + POSITIVE_RESPONSE:
                logger.error(f"Failed to write memory at 0x{address:X}")
                return False
                
            return True
            
        else:  # UDS
            # UDS has two methods: write memory by address or request download + transfer data
            # We'll use request download + transfer data for larger blocks
            
            # Request download
            # Format: [data format (1 byte), address format (1 byte), address (variable), size format (1 byte), size (variable)]
            data_format = 0x00  # Default format
            addr_format = 0x24  # 4 bytes
            addr_bytes = address.to_bytes(4, byteorder='big')
            size_format = 0x24  # 4 bytes
            size_bytes = len(data).to_bytes(4, byteorder='big')
            
            response = self._send_uds_command(UDS_REQUEST_DOWNLOAD, 
                                             [data_format, addr_format] + list(addr_bytes) + 
                                             [size_format] + list(size_bytes))
            
            if not response or response[0] != UDS_REQUEST_DOWNLOAD + POSITIVE_RESPONSE:
                logger.error(f"Failed to request download at 0x{address:X}")
                return False
                
            # Extract max block size and block sequence counter
            max_block_size = 0
            if len(response) >= 3:
                max_block_size = int.from_bytes(response[2:], byteorder='big')
                
            # Use the smaller of our block size and the ECU's max block size
            block_size = min(len(data), max_block_size if max_block_size > 0 else len(data))
            
            # Transfer data
            # Format: [block sequence counter (1 byte), data]
            block_sequence_counter = 1
            
            for i in range(0, len(data), block_size):
                block = data[i:i+block_size]
                
                response = self._send_uds_command(UDS_TRANSFER_DATA, 
                                                [block_sequence_counter] + list(block))
                
                if not response or response[0] != UDS_TRANSFER_DATA + POSITIVE_RESPONSE:
                    logger.error(f"Failed to transfer data block {block_sequence_counter} at 0x{address+i:X}")
                    return False
                    
                block_sequence_counter = (block_sequence_counter + 1) & 0xFF
                
            # Request transfer exit
            response = self._send_uds_command(UDS_REQUEST_TRANSFER_EXIT, [])
            
            if not response or response[0] != UDS_REQUEST_TRANSFER_EXIT + POSITIVE_RESPONSE:
                logger.error("Failed to exit transfer")
                return False
                
            return True
    
    def _verify_flash(self, flash_data: bytes, progress_callback: Callable = None) -> bool:
        """Verify that the ECU flash matches the provided data."""
        # Calculate total size for progress reporting
        total_size = len(flash_data)
        bytes_verified = 0
        
        # Verify each sector
        for sector in self.ecu_memory_map["sectors"]:
            sector_start = sector["start"]
            sector_size = sector["size"]
            sector_name = sector["name"]
            protected = sector.get("protected", False)
            
            # Skip protected sectors
            if protected:
                logger.info(f"Skipping verification of protected sector: {sector_name}")
                continue
                
            # Calculate sector range in flash data
            data_start = sector_start - self.ecu_memory_map["flash_start"]
            data_end = data_start + sector_size
            
            # Skip if this sector is not in the flash data
            if data_start >= len(flash_data):
                logger.info(f"Skipping verification of sector outside flash data: {sector_name}")
                continue
                
            # Get the data for this sector
            sector_data = flash_data[data_start:min(data_end, len(flash_data))]
            
            # If the sector data is smaller than the sector, pad with 0xFF
            if len(sector_data) < sector_size:
                sector_data += b'\xFF' * (sector_size - len(sector_data))
                
            logger.info(f"Verifying sector: {sector_name} ({len(sector_data)/1024:.1f} KB)")
            
            # Read and verify the sector in blocks
            block_size = min(self.ecu_memory_map.get("transfer_size", 0x200), 0x1000)  # Max 4KB blocks
            for offset in range(0, len(sector_data), block_size):
                address = sector_start + offset
                expected_block = sector_data[offset:offset+block_size]
                
                # Read memory block
                actual_block = self._read_memory(address, len(expected_block))
                if not actual_block:
                    logger.error(f"Failed to read memory at 0x{address:X} during verification")
                    return False
                    
                # Compare blocks
                if actual_block != expected_block:
                    logger.error(f"Verification failed at 0x{address:X}: data mismatch")
                    return False
                    
                # Update progress
                bytes_verified += len(expected_block)
                if progress_callback:
                    progress_callback(bytes_verified / total_size * 100)
                    
                # Send tester present to keep the session alive
                if offset % 0x10000 == 0 and offset > 0:
                    if self.protocol == "UDS":
                        self._send_uds_command(UDS_TESTER_PRESENT, [0x00])
                    else:
                        self._send_kwp_command(KWP_TESTER_PRESENT, [0x00])
        
        logger.info("Flash verification completed successfully")
        return True
    
    def reset_ecu(self) -> bool:
        """Reset the ECU."""
        logger.info("Resetting ECU...")
        
        if self.protocol == "KWP2000":
            # KWP2000 ECU reset
            response = self._send_kwp_command(KWP_ECU_RESET, [0x01])  # Hard reset
            # We don't expect a response since the ECU will reset
            return True
            
        else:  # UDS
            # UDS ECU reset
            response = self._send_uds_command(UDS_ECU_RESET, [0x01])  # Hard reset
            # We don't expect a response since the ECU will reset
            return True
    
    def read_dtcs(self) -> List[Dict]:
        """Read Diagnostic Trouble Codes (DTCs) from the ECU."""
        if not self.connected and not self.connect():
            raise ConnectionError("Could not connect to ECU")
            
        dtcs = []
        
        if self.protocol == "KWP2000":
            # KWP2000 read DTCs by status
            response = self._send_kwp_command(KWP_READ_DTC_BY_STATUS, [0x00])  # All DTCs
            if not response or response[0] != KWP_READ_DTC_BY_STATUS + POSITIVE_RESPONSE:
                logger.error("Failed to read DTCs")
                return dtcs
                
            # Parse DTCs
            # Format: [status byte, DTC high byte, DTC low byte] repeated
            for i in range(2, len(response), 3):
                if i + 2 < len(response):
                    status = response[i]
                    dtc_high = response[i+1]
                    dtc_low = response[i+2]
                    
                    dtc_code = (dtc_high << 8) | dtc_low
                    dtc_text = f"P{dtc_code:04X}"
                    
                    dtcs.append({
                        "code": dtc_code,
                        "text": dtc_text,
                        "status": status
                    })
                    
        else:  # UDS
            # UDS read DTCs
            response = self._send_uds_command(UDS_READ_DTC, [0x02, 0xFF])  # All DTCs
            if not response or response[0] != UDS_READ_DTC + POSITIVE_RESPONSE:
                logger.error("Failed to read DTCs")
                return dtcs
                
            # Parse DTCs
            # Format: [DTC high byte, DTC mid byte, DTC low byte, status byte] repeated
            for i in range(3, len(response), 4):
                if i + 3 < len(response):
                    dtc_high = response[i]
                    dtc_mid = response[i+1]
                    dtc_low = response[i+2]
                    status = response[i+3]
                    
                    dtc_code = (dtc_high << 16) | (dtc_mid << 8) | dtc_low
                    
                    # Convert to standard OBD-II format
                    if dtc_high & 0xC0 == 0x00:
                        dtc_type = "P"  # Powertrain
                    elif dtc_high & 0xC0 == 0x40:
                        dtc_type = "C"  # Chassis
                    elif dtc_high & 0xC0 == 0x80:
                        dtc_type = "B"  # Body
                    else:
                        dtc_type = "U"  # Network
                        
                    dtc_text = f"{dtc_type}{dtc_high & 0x3F:X}{dtc_mid:02X}{dtc_low:02X}"
                    
                    dtcs.append({
                        "code": dtc_code,
                        "text": dtc_text,
                        "status": status
                    })
                    
        logger.info(f"Read {len(dtcs)} DTCs from ECU")
        return dtcs
    
    def clear_dtcs(self) -> bool:
        """Clear Diagnostic Trouble Codes (DTCs) from the ECU."""
        if not self.connected and not self.connect():
            raise ConnectionError("Could not connect to ECU")
            
        logger.info("Clearing DTCs...")
        
        if self.protocol == "KWP2000":
            # KWP2000 clear DTCs
            response = self._send_kwp_command(KWP_CLEAR_DIAGNOSTIC_INFORMATION, [0xFF, 0xFF, 0xFF])  # All DTCs
            if not response or response[0] != KWP_CLEAR_DIAGNOSTIC_INFORMATION + POSITIVE_RESPONSE:
                logger.error("Failed to clear DTCs")
                return False
                
            logger.info("DTCs cleared successfully")
            return True
            
        else:  # UDS
            # UDS clear DTCs
            response = self._send_uds_command(UDS_CLEAR_DTC, [0xFF, 0xFF, 0xFF])  # All DTCs
            if not response or response[0] != UDS_CLEAR_DTC + POSITIVE_RESPONSE:
                logger.error("Failed to clear DTCs")
                return False
                
            logger.info("DTCs cleared successfully")
            return True
    
    def read_live_data(self, pids: List[int] = None) -> Dict:
        """Read live data parameters from the ECU."""
        if not self.connected and not self.connect():
            raise ConnectionError("Could not connect to ECU")
            
        # Default PIDs if none specified
        if not pids:
            pids = [0x0C, 0x0D, 0x0F, 0x10, 0x11, 0x0B]  # RPM, Speed, IAT, MAF, TPS, MAP
            
        data = {}
        
        if self.protocol == "KWP2000":
            # KWP2000 read data by local ID
            for pid in pids:
                response = self._send_kwp_command(KWP_READ_DATA_BY_LOCAL_ID, [pid])
                if response and response[0] == KWP_READ_DATA_BY_LOCAL_ID + POSITIVE_RESPONSE:
                    # Parse data based on PID
                    value = self._parse_live_data(pid, response[2:])
                    data[pid] = value
                    
        else:  # UDS
            # UDS read data by identifier
            for pid in pids:
                # Convert OBD-II PID to UDS DID (typically 0xF400 + PID)
                did = 0xF400 + pid
                did_bytes = did.to_bytes(2, byteorder='big')
                
                response = self._send_uds_command(UDS_READ_DATA_BY_IDENTIFIER, list(did_bytes))
                if response and response[0] == UDS_READ_DATA_BY_IDENTIFIER + POSITIVE_RESPONSE:
                    # Parse data based on PID
                    value = self._parse_live_data(pid, response[3:])
                    data[pid] = value
                    
        return data
    
    def _parse_live_data(self, pid: int, data: bytes) -> Any:
        """Parse live data based on PID."""
        if pid == 0x0C:  # RPM
            if len(data) >= 2:
                rpm = ((data[0] << 8) | data[1]) / 4
                return {"value": rpm, "unit": "RPM"}
                
        elif pid == 0x0D:  # Speed
            if len(data) >= 1:
                speed = data[0]
                return {"value": speed, "unit": "km/h"}
                
        elif pid == 0x0F:  # IAT (Intake Air Temperature)
            if len(data) >= 1:
                temp = data[0] - 40
                return {"value": temp, "unit": "°C"}
                
        elif pid == 0x10:  # MAF (Mass Air Flow)
            if len(data) >= 2:
                maf = ((data[0] << 8) | data[1]) / 100
                return {"value": maf, "unit": "g/s"}
                
        elif pid == 0x11:  # TPS (Throttle Position)
            if len(data) >= 1:
                tps = data[0] * 100 / 255
                return {"value": tps, "unit": "%"}
                
        elif pid == 0x0B:  # MAP (Manifold Absolute Pressure)
            if len(data) >= 1:
                map_value = data[0]
                return {"value": map_value, "unit": "kPa"}
                
        # Default case
        return {"value": data.hex(), "unit": "hex"}
def main():
    """Main function for command-line usage."""
    import argparse
    parser = argparse.ArgumentParser(description='BMW ECU Flasher Tool')
    parser.add_argument('--port', help='COM port to use')
    parser.add_argument('--info', action='store_true', help='Read ECU information')
    parser.add_argument('--backup', help='Backup ECU to specified file')
    parser.add_argument('--flash', help='Flash ECU with specified file')
    parser.add_argument('--dtcs', action='store_true', help='Read DTCs')
    parser.add_argument('--clear-dtcs', action='store_true', help='Clear DTCs')
    parser.add_argument('--live-data', action='store_true', help='Read live data')
    parser.add_argument('--reset', action='store_true', help='Reset ECU')
    
    args = parser.parse_args()
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler("rftx_flasher.log"),
            logging.StreamHandler()
        ]
    )
    
    flasher = BMWFlasher(args.port)
    
    try:
        # Connect to ECU
        if not flasher.connect():
            logger.error("Failed to connect to ECU")
            return 1
            
        # Process commands
        if args.info:
            ecu_info = flasher.read_ecu_info()
            print("\nECU Information:")
            print(f"VIN: {ecu_info.get('vin', 'Unknown')}")
            print(f"ECU ID: {ecu_info.get('ecu_id', 'Unknown')}")
            print(f"Software Version: {ecu_info.get('sw_version', 'Unknown')}")
            print(f"Hardware Version: {ecu_info.get('hw_version', 'Unknown')}")
            print(f"ECU Type: {ecu_info.get('ecu_type', 'Unknown')}")
            print(f"Bootloader Mode: {ecu_info.get('in_bootloader', False)}")
            
        elif args.backup:
            def progress(percent):
                sys.stdout.write(f"\rBackup progress: {percent:.1f}%")
                sys.stdout.flush()
                
            backup_file = flasher.backup_ecu(args.backup, progress)
            print(f"\nBackup completed: {backup_file}")
            
        elif args.flash:
            def progress(percent):
                sys.stdout.write(f"\rFlash progress: {percent:.1f}%")
                sys.stdout.flush()
                
            flasher.flash_ecu(args.flash, progress)
            print("\nFlash completed successfully")
            
        elif args.dtcs:
            dtcs = flasher.read_dtcs()
            print("\nDiagnostic Trouble Codes:")
            if not dtcs:
                print("No DTCs found")
            else:
                for dtc in dtcs:
                    status_str = bin(dtc['status'])[2:].zfill(8)
                    print(f"{dtc['text']} - Status: {status_str}")
                    
        elif args.clear_dtcs:
            if flasher.clear_dtcs():
                print("DTCs cleared successfully")
            else:
                print("Failed to clear DTCs")
                
        elif args.live_data:
            print("\nLive Data:")
            for _ in range(10):  # Read 10 samples
                data = flasher.read_live_data()
                print("\033[H\033[J")  # Clear screen
                for pid, value in data.items():
                    print(f"PID 0x{pid:02X}: {value['value']} {value['unit']}")
                time.sleep(0.5)
                
        elif args.reset:
            if flasher.reset_ecu():
                print("ECU reset command sent")
            else:
                print("Failed to reset ECU")
                
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        return 1
        
    finally:
        # Disconnect
        flasher.disconnect()
        
    return 0

if __name__ == "__main__":
    sys.exit(main())





