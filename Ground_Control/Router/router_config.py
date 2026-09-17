"""
router_config.py

Central configuration module for the Subnet Guardian prototype.

Purpose:
- Hold system-wide constants
- Define operational defaults
- Provide one reliable place for shared settings

Notes:
- Keep runtime logic out of this file
- Only place configuration, limits, labels, and command mappings here
"""

from pathlib import Path


# ============================================================
# Project Identity
# ============================================================

PROJECT_NAME = "Subnet Guardian"
PROJECT_VERSION = "0.1.0"
PROJECT_STAGE = "prototype"


# ============================================================
# Base Paths
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

LOG_FILE = LOG_DIR / "router_events.log"


# ============================================================
# Serial / Arduino Settings
# ============================================================

SERIAL_BAUDRATE = 9600
SERIAL_TIMEOUT_SECONDS = 1
SERIAL_RETRY_LIMIT = 3
SERIAL_RETRY_DELAY_SECONDS = 2


# ============================================================
# Connectivity / Monitor Settings
# ============================================================

CHECK_INTERVAL_SECONDS = 5
UPSTREAM_HOST = "8.8.8.8"
UPSTREAM_PORT = 53
CONNECTIVITY_TIMEOUT_SECONDS = 3


# ============================================================
# Logging Settings
# ============================================================

LOG_LEVEL = "INFO"
LOG_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
LOG_ENCODING = "utf-8"

NORMAL_LABEL = "normal"
ABNORMAL_LABEL = "abnormal"

SLOW_RECONNECT_SECONDS = 15.0
HIGH_COMMAND_FAILURE_COUNT = 2
HIGH_CONNECTION_LOST_COUNT = 2

# ============================================================
# System States
# ============================================================

STATE_BOOTING = "BOOTING"
STATE_CONNECTED = "CONNECTED"
STATE_DISCONNECTED = "DISCONNECTED"
STATE_ERROR = "ERROR"
STATE_SHUTDOWN = "SHUTDOWN"

VALID_SYSTEM_STATES = {
    STATE_BOOTING,
    STATE_CONNECTED,
    STATE_DISCONNECTED,
    STATE_ERROR,
    STATE_SHUTDOWN,
}


# ============================================================
# Event Types
# ============================================================

EVENT_SYSTEM_START = "SYSTEM_START"
EVENT_SYSTEM_STOP = "SYSTEM_STOP"
EVENT_CONNECTION_ESTABLISHED = "CONNECTION_ESTABLISHED"
EVENT_CONNECTION_LOST = "CONNECTION_LOST"
EVENT_CONNECTION_CHECK_FAILED = "CONNECTION_CHECK_FAILED"
EVENT_SERIAL_CONNECTED = "SERIAL_CONNECTED"
EVENT_SERIAL_DISCONNECTED = "SERIAL_DISCONNECTED"
EVENT_SERIAL_ERROR = "SERIAL_ERROR"
EVENT_SECURITY_UPDATE = "SECURITY_UPDATE"
EVENT_LED_COMMAND_SENT = "LED_COMMAND_SENT"


# ============================================================
# LED Commands (sent to Arduino)
# ============================================================

LED_BOOTING_CMD = "BOOT"
LED_CONNECTED_CMD = "CONNECTED"
LED_DISCONNECTED_CMD = "DISCONNECTED"
LED_ERROR_CMD = "ERROR"
LED_OFF_CMD = "OFF"

LED_COMMANDS = {
    STATE_BOOTING: LED_BOOTING_CMD,
    STATE_CONNECTED: LED_CONNECTED_CMD,
    STATE_DISCONNECTED: LED_DISCONNECTED_CMD,
    STATE_ERROR: LED_ERROR_CMD,
}


# ============================================================
# Connection / Health Status Labels
# ============================================================

HEALTH_OK = "OK"
HEALTH_DEGRADED = "DEGRADED"
HEALTH_FAILED = "FAILED"


# ============================================================
# Safety / Runtime Limits
# ============================================================

MAX_CONSECUTIVE_CONNECTION_FAILURES = 3
MAX_CONSECUTIVE_SERIAL_FAILURES = 3


# ============================================================
# Feature Flags
# ============================================================

ENABLE_FILE_LOGGING = True
ENABLE_CONSOLE_LOGGING = True
ENABLE_LED_CONTROL = True
ENABLE_SERIAL_AUTODETECT = True


# ============================================================
# Development / Debug
# ============================================================

DEBUG_MODE = False
VERBOSE_LOGGING = False


# ============================================================
# Notes on what changed
# ============================================================
# 1. Added a proper module header so router_config.py reads like a real production config file.
# 2. Replaced loose naming with more explicit names such as:
#       SERIAL_TIMEOUT -> SERIAL_TIMEOUT_SECONDS
#       CHECK_INTERVAL -> CHECK_INTERVAL_SECONDS
# 3. Introduced project identity fields:
#       PROJECT_NAME, PROJECT_VERSION, PROJECT_STAGE
# 4. Added a logs directory using pathlib for cleaner file handling.
# 5. Expanded system states to support future production behavior:
#       ERROR, SHUTDOWN
# 6. Added VALID_SYSTEM_STATES so the rest of the system can validate state transitions.
# 7. Added event type constants so logging stays standardized across modules.
# 8. Added LED command mapping dictionary so router_monitor can translate state -> command cleanly.
# 9. Added health labels for connection/system health reporting.
# 10. Added retry and failure-limit settings to prepare for more stable production behavior.
# 11. Added feature flags to make future toggling easier without rewriting logic.
# 12. Kept the file configuration-only, which is closer to industry-standard structure.
