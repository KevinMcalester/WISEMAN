"""
led_controller.py

LED command and hardware signaling module for the Subnet Guardian system.

Purpose:
- Provide a clean interface for sending LED/state commands to the Arduino
- Centralize outbound hardware control behavior
- Prepare for future AI-driven control decisions without mixing AI logic here

Design Principles:
- This module sends commands, it does not decide security policy
- router_monitor or future AI modules decide WHICH state to send
- this module standardizes HOW commands are delivered
"""

from __future__ import annotations

from dataclasses import dataclass

from ground_control.Router import  router_config
from ground_control.Router import  proto_reader


@dataclass(frozen=True)
class LEDCommandResult:
    """
    Structured result for outbound LED command attempts.
    """
    success: bool
    command: str
    error_message: str | None = None


def _validate_serial_connection(ser) -> None:
    """
    Ensure the serial object is available before attempting transmission.
    """
    if ser is None:
        raise ValueError("Serial connection is not initialized.")


def _send_command(ser, command: str) -> LEDCommandResult:
    """
    Core command sender used by all LED/state functions.

    Parameters:
        ser: Active serial connection object
        command (str): Outbound command to send to the Arduino

    Returns:
        LEDCommandResult: structured transmission result
    """
    try:
        _validate_serial_connection(ser)
        proto_reader.send_message(ser, command)

        return LEDCommandResult(
            success=True,
            command=command,
            error_message=None,
        )

    except Exception as exc:
        return LEDCommandResult(
            success=False,
            command=command,
            error_message=f"Failed to send LED command '{command}': {exc}",
        )


def send_booting(ser) -> LEDCommandResult:
    """
    Send the booting state command to the Arduino.
    """
    return _send_command(ser, router_config.LED_BOOTING_CMD)


def send_connected(ser) -> LEDCommandResult:
    """
    Send the connected state command to the Arduino.
    """
    return _send_command(ser, router_config.LED_CONNECTED_CMD)


def send_disconnected(ser) -> LEDCommandResult:
    """
    Send the disconnected state command to the Arduino.
    """
    return _send_command(ser, router_config.LED_DISCONNECTED_CMD)


def send_error(ser) -> LEDCommandResult:
    """
    Send the error state command to the Arduino.
    """
    return _send_command(ser, router_config.LED_ERROR_CMD)


def send_off(ser) -> LEDCommandResult:
    """
    Send the off state command to the Arduino.
    """
    return _send_command(ser, router_config.LED_OFF_CMD)


def send_state(ser, state: str) -> LEDCommandResult:
    """
    Translate a system state into its configured LED command and send it.

    This is the preferred scalable interface for router_monitor and future AI logic.

    Parameters:
        ser: Active serial connection object
        state (str): System state label such as BOOTING or CONNECTED

    Returns:
        LEDCommandResult: structured transmission result
    """
    if state not in router_config.LED_COMMANDS:
        return LEDCommandResult(
            success=False,
            command=state,
            error_message=f"Unknown LED state '{state}'. No mapped command found.",
        )

    command = router_config.LED_COMMANDS[state]
    return _send_command(ser, command)


def send_custom_command(ser, command: str) -> LEDCommandResult:
    """
    Send a direct custom command to the Arduino.

    Intended for future advanced behavior where router_monitor or AI
    may issue hardware instructions beyond the default state set.

    Parameters:
        ser: Active serial connection object
        command (str): Raw outbound command string

    Returns:
        LEDCommandResult: structured transmission result
    """
    cleaned_command = command.strip()

    if not cleaned_command:
        return LEDCommandResult(
            success=False,
            command=command,
            error_message="Custom LED command is empty.",
        )

    return _send_command(ser, cleaned_command)


# ============================================================
# Notes on what changed
# ============================================================
# 1. Added a real module header so this reads like a production hardware-control module.
# 2. Introduced one core internal sender:
#       _send_command()
#    so command transmission logic is no longer duplicated.
# 3. Added _validate_serial_connection() so bad serial objects fail cleanly.
# 4. Wrapped command results in LEDCommandResult for easier integration with router_monitor.
# 5. Kept your original role-specific functions:
#       send_booting()
#       send_connected()
#       send_disconnected()
#    but made them use the shared internal sender.
# 6. Added send_error() and send_off() to support fuller system-state handling.
# 7. Added send_state(), which is the more scalable industry-style interface:
#       state -> mapped command -> Arduino
# 8. Added send_custom_command() so future AI logic can issue direct hardware instructions
#    without rewriting the module.
# 9. Kept this file limited to command delivery only, which is cleaner architecture:
#       AI/router_monitor decides what to send
#       led_controller sends it
# 10. This structure prepares the file for growth into a more advanced control layer
#     without turning it into a policy/decision module.