"""
proto_reader.py

Serial communication layer between the Raspberry Pi and the Arduino.

Purpose:
- Handle detection of the Arduino device
- Establish and manage the serial connection
- Send and receive protocol messages between systems

Design Principles:
- This module ONLY manages communication
- router_monitor decides what messages mean
- led_controller uses this module to send commands
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import serial
import serial.tools.list_ports

from ground_control.Router import  router_config


# ============================================================
# Data Structures
# ============================================================

@dataclass(frozen=True)
class SerialConnectionResult:
    """
    Structured result for serial connection attempts.
    """
    success: bool
    port: str | None
    error_message: str | None = None


# ============================================================
# Port Discovery
# ============================================================

def find_host() -> str | None:
    """
    Attempt to automatically detect the Arduino device.

    Returns:
        port name if found, otherwise None
    """
    ports = serial.tools.list_ports.comports()

    for port in ports:
        if "Arduino" in port.description or "ttyACM" in port.device:
            return port.device

    return None


def list_ports() -> None:
    """
    Print available serial ports for manual selection.
    """
    ports = serial.tools.list_ports.comports()

    print("\nAvailable ports:")
    for p in ports:
        print(f"{p.device}  |  {p.description}")


# ============================================================
# Serial Connection
# ============================================================

def connect_serial() -> serial.Serial:
    """
    Establish a serial connection to the Arduino.

    Returns:
        serial.Serial object
    """
    port = find_host()

    if port is None and router_config.ENABLE_SERIAL_AUTODETECT:
        print("No Arduino detected automatically.")
        list_ports()
        port = input(
            "\nEnter the port manually (example: COM3 or /dev/ttyACM0): "
        ).strip()

    if port is None:
        raise RuntimeError("Unable to determine serial port for Arduino.")

    print(f"\nConnecting to {port}...\n")

    ser = serial.Serial(
        port,
        router_config.SERIAL_BAUDRATE,
        timeout=router_config.SERIAL_TIMEOUT_SECONDS,
    )

    # Allow Arduino reset handshake
    time.sleep(2)

    return ser


# ============================================================
# Message Transmission
# ============================================================

def send_message(ser: serial.Serial, message: str) -> None:
    """
    Send a message to the Arduino.

    Parameters:
        ser: active serial connection
        message: string command to send
    """
    if ser is None or not ser.is_open:
        raise RuntimeError("Attempted to send message with closed serial connection.")

    payload = (message.strip() + "\n").encode()
    ser.write(payload)


# ============================================================
# Message Reception
# ============================================================

def read_message(ser: serial.Serial) -> str | None:
    """
    Read an incoming message from the Arduino.

    Returns:
        decoded message string or None if no message available
    """
    if ser is None or not ser.is_open:
        return None

    try:
        if ser.in_waiting:
            message = ser.readline().decode(errors="ignore").strip()
            return message

    except Exception:
        return None

    return None


# ============================================================
# Connection Shutdown
# ============================================================

def close_serial(ser: serial.Serial) -> None:
    """
    Safely close the serial connection.
    """
    if ser and ser.is_open:
        ser.close()


# ============================================================
# Notes on what changed
# ============================================================
# 1. Added a module header so this reads as a proper communication layer.
# 2. Introduced SerialConnectionResult dataclass for future structured connection handling.
# 3. Separated the file into logical sections:
#       Port Discovery
#       Serial Connection
#       Message Transmission
#       Message Reception
#       Connection Shutdown
# 4. Replaced hardcoded SERIAL_TIMEOUT with config.SERIAL_TIMEOUT_SECONDS.
# 5. Added validation so sending messages on a closed serial port raises a controlled error.
# 6. Cleaned message formatting before sending to avoid whitespace issues.
# 7. Added safe exception handling to read_message() so serial noise cannot crash the system.
# 8. Added clearer docstrings so future development and AI integration can easily reference behavior.
# 9. Maintained compatibility with led_controller by preserving send_message().
# 10. Structured the module so router_monitor can act as the orchestration layer.