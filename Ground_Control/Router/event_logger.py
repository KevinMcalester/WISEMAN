"""
event_logger.py

Event logging module for the Subnet Guardian system.

Purpose:
- Record system activity for monitoring and analysis
- Provide standardized event logging across all modules
- Produce clean logs that can later be used for AI training

Design Principles:
- Logging must be lightweight and reliable
- router_monitor decides WHAT to log
- this module decides HOW it is logged
"""

from __future__ import annotations

import datetime
from pathlib import Path
from ground_control.Router import router_config


def _get_timestamp() -> str:
    """
    Generate a timestamp formatted according to system configuration.
    """
    return datetime.datetime.now().strftime(router_config.LOG_TIMESTAMP_FORMAT)


def _write_to_file(log_line: str) -> None:
    """
    Append the log entry to the configured log file.
    """
    try:
        log_path = Path(router_config.LOG_FILE)

        with open(log_path, "a", encoding=router_config.LOG_ENCODING) as log_file:
            log_file.write(log_line)

    except Exception as exc:
        # Fail-safe: logging should never crash the system
        print(f"[LOGGER_ERROR] Failed to write log file: {exc}")


def _write_to_console(log_line: str) -> None:
    """
    Output log entry to console if enabled.
    """
    print(log_line.strip())


def log_event(event: str) -> None:
    """
    Primary logging interface used across the router system.

    Example usage:
        log_event(config.EVENT_SYSTEM_START)

    Parameters:
        event (str): event label describing the action/state.
    """

    timestamp = _get_timestamp()
    log_line = f"[{timestamp}] {event}\n"

    if router_config.ENABLE_FILE_LOGGING:
        _write_to_file(log_line)

    if router_config.ENABLE_CONSOLE_LOGGING:
        _write_to_console(log_line)


# ============================================================
# Notes on what changed
# ============================================================
# 1. Added a module header so the logger reads like a production system component.
# 2. Separated responsibilities into smaller functions:
#       _get_timestamp()
#       _write_to_file()
#       _write_to_console()
# 3. Replaced hardcoded timestamp formatting with config.LOG_TIMESTAMP_FORMAT.
# 4. Added encoding support using config.LOG_ENCODING.
# 5. Introduced feature flags:
#       ENABLE_FILE_LOGGING
#       ENABLE_CONSOLE_LOGGING
# 6. Added fail-safe behavior so logging errors cannot crash the system.
# 7. Ensured router modules interact through one clean function: log_event().
# 8. Maintained simple log format so it remains easy for AI training and analysis.