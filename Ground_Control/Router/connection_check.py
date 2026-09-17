"""
connection_check.py

Connectivity validation module for the Subnet Guardian system.

Purpose:
- Verify upstream network reachability
- Provide a clean health-check function for router_monitor
- Keep connectivity logic isolated from orchestration logic

Notes:
- This module should only answer connection status questions
- router_monitor decides what to do with the result
"""

from __future__ import annotations

import platform
import subprocess
from dataclasses import dataclass

from ground_control.Router import router_config


@dataclass(frozen=True)
class ConnectionStatus:
    """
    Structured result returned by the connectivity checker.
    """
    is_connected: bool
    host: str
    return_code: int
    command: tuple[str, ...]
    error_message: str | None = None


def _build_ping_command() -> tuple[str, ...]:
    """
    Build a platform-aware ping command.

    Linux/macOS:
        ping -c 1 -W <timeout> <host>

    Windows:
        ping -n 1 -w <timeout_ms> <host>
    """
    system_name = platform.system().lower()
    host = router_config.UPSTREAM_HOST
    timeout_seconds = router_config.CONNECTIVITY_TIMEOUT_SECONDS

    if system_name == "windows":
        timeout_milliseconds = int(timeout_seconds * 1000)
        return ("ping", "-n", "1", "-w", str(timeout_milliseconds), host)

    return ("ping", "-c", "1", "-W", str(timeout_seconds), host)


def check_connection() -> bool:
    """
    Simple boolean connectivity check for quick use in router_monitor.

    Returns:
        bool: True if upstream connectivity is available, else False.
    """
    status = get_connection_status()
    return status.is_connected


def get_connection_status() -> ConnectionStatus:
    """
    Perform the upstream connectivity check and return structured details.

    Returns:
        ConnectionStatus: full result object for logging / monitoring use.
    """
    command = _build_ping_command()

    try:
        result = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )

        return ConnectionStatus(
            is_connected=(result.returncode == 0),
            host=router_config.UPSTREAM_HOST,
            return_code=result.returncode,
            command=command,
            error_message=None,
        )

    except FileNotFoundError as exc:
        return ConnectionStatus(
            is_connected=False,
            host=router_config.UPSTREAM_HOST,
            return_code=-1,
            command=command,
            error_message=f"Ping command not found: {exc}",
        )

    except Exception as exc:
        return ConnectionStatus(
            is_connected=False,
            host=router_config.UPSTREAM_HOST,
            return_code=-1,
            command=command,
            error_message=f"Unexpected connection check failure: {exc}",
        )


# ============================================================
# Notes on what changed
# ============================================================
# 1. Added a real module header so the file reads like a production system component.
# 2. Split logic into:
#       _build_ping_command()
#       check_connection()
#       get_connection_status()
#    which makes the file easier to maintain and expand.
# 3. Kept check_connection() returning only bool so router_monitor can use it simply.
# 4. Added get_connection_status() for deeper monitoring, logging, and debugging later.
# 5. Added platform-aware ping handling so the module is not hard-locked to Linux syntax.
# 6. Replaced hardcoded timeout values with config-driven values.
# 7. Added structured ConnectionStatus output using a dataclass for cleaner system integration.
# 8. Added basic error handling for:
#       missing ping command
#       unexpected runtime failures
# 9. Kept this file focused only on connection validation, which is more industry-standard.