"""
router_monitor.py

Primary orchestration module for the Subnet Guardian system.

Purpose:
- Start and coordinate all core system modules
- Maintain the main runtime loop
- Detect network state transitions
- Send hardware state updates to the Arduino
- Record system activity for monitoring and future AI analysis

Design Principles:
- router_monitor is the system conductor
- specialized modules perform their own responsibilities
- this file coordinates system flow, state handling, and recovery behavior
"""
from __future__ import annotations

import os
import time


from ground_control.Router import router_config
from ground_control.Router import proto_reader
from ground_control.Router import connection_check
from ground_control.Router import event_logger
from ground_control.Router import led_controller

#import router_config
#import proto_reader
#import connection_check
#import event_logger
#import led_controller

from ground_control.Router.data_logger import DataLogger
from ground_control.Router.observer import RealTimeObserver


ABNORMAL_RECONNECT_THRESHOLD_SECONDS = float(
    os.getenv("DATA_LOGGER_ABNORMAL_RECONNECT_THRESHOLD_SECONDS", "15")
)


def _determine_system_state(is_connected: bool) -> str:
    if is_connected:
        return router_config.STATE_CONNECTED
    return router_config.STATE_DISCONNECTED


def _log_led_result(result, target_state: str, data_logger: DataLogger) -> None:
    if result.success:
        message = f"{router_config.EVENT_LED_COMMAND_SENT} -> state={target_state} command={result.command}"
        event_logger.log_event(message)
        data_logger.log_event(
            router_config.EVENT_LED_COMMAND_SENT,
            state=target_state,
            command=result.command
        )
    else:
        message = f"{router_config.EVENT_SERIAL_ERROR} -> LED command failed for state={target_state}: {result.error_message}"
        event_logger.log_event(message)
        data_logger.log_event(
            router_config.EVENT_SERIAL_ERROR,
            state=target_state,
            error=result.error_message,
            abnormal=True,
            abnormal_reason="led_command_failed",
            event_label="abnormal"
        )


def _handle_state_transition(
        ser,
        previous_state: str | None,
        current_state: str,
        data_logger: DataLogger,
        disconnect_started_at: float | None,
) -> str:
    if current_state == previous_state:
        return previous_state

    event_logger.log_event(f"STATE_CHANGED -> {current_state}")

    if current_state == router_config.STATE_DISCONNECTED:
        data_logger.log_event(
            "STATE_CHANGED",
            state=current_state,
            abnormal=True,
            abnormal_reason="state_changed_to_disconnected",
            event_label="abnormal"
        )
    elif current_state == router_config.STATE_CONNECTED and disconnect_started_at is not None:
        reconnect_duration_seconds = round(time.time() - disconnect_started_at, 3)
        reconnect_abnormal = reconnect_duration_seconds > ABNORMAL_RECONNECT_THRESHOLD_SECONDS

        data_logger.log_event(
            "STATE_CHANGED",
            state=current_state,
            reconnect_duration_seconds=reconnect_duration_seconds,
            reconnect_threshold_seconds=ABNORMAL_RECONNECT_THRESHOLD_SECONDS,
            abnormal=reconnect_abnormal,
            abnormal_reason="slow_reconnect" if reconnect_abnormal else None,
            event_label="abnormal" if reconnect_abnormal else data_logger.label
        )
    else:
        data_logger.log_event(
            "STATE_CHANGED",
            state=current_state
        )

    led_result = led_controller.send_state(ser, current_state)
    _log_led_result(led_result, current_state, data_logger)

    return current_state


def _log_arduino_response(ser, data_logger: DataLogger) -> None:
    response = proto_reader.read_message(ser)
    if response:
        event_logger.log_event(f"ARDUINO_RESPONSE -> {response}")
        data_logger.log_event("ARDUINO_RESPONSE", response=response)


def _log_connection_event(
        connection_status,
        previous_state: str | None,
        current_state: str,
        data_logger: DataLogger,
        disconnect_started_at: float | None,
) -> None:

    if current_state == previous_state:
        return

    if connection_status.is_connected:
        event_logger.log_event(
            f"{router_config.EVENT_CONNECTION_ESTABLISHED} -> host={connection_status.host}"
        )

        if disconnect_started_at is not None:
            reconnect_duration_seconds = round(time.time() - disconnect_started_at, 3)
            reconnect_abnormal = reconnect_duration_seconds > ABNORMAL_RECONNECT_THRESHOLD_SECONDS

            data_logger.log_event(
                router_config.EVENT_CONNECTION_ESTABLISHED,
                host=connection_status.host,
                reconnect_duration_seconds=reconnect_duration_seconds,
                reconnect_threshold_seconds=ABNORMAL_RECONNECT_THRESHOLD_SECONDS,
                abnormal=reconnect_abnormal,
                abnormal_reason="slow_reconnect" if reconnect_abnormal else None,
                event_label="abnormal" if reconnect_abnormal else data_logger.label
            )
        else:
            data_logger.log_event(
                router_config.EVENT_CONNECTION_ESTABLISHED,
                host=connection_status.host
            )

    else:
        if connection_status.error_message:
            event_logger.log_event(
                f"{router_config.EVENT_CONNECTION_CHECK_FAILED} -> {connection_status.error_message}"
            )

            data_logger.log_event(
                router_config.EVENT_CONNECTION_CHECK_FAILED,
                error=connection_status.error_message,
                abnormal=True,
                abnormal_reason="connection_check_failed",
                event_label="abnormal"
            )

        else:
            event_logger.log_event(
                f"{router_config.EVENT_CONNECTION_LOST} -> host={connection_status.host} code={connection_status.return_code}"
            )

            data_logger.log_event(
                router_config.EVENT_CONNECTION_LOST,
                host=connection_status.host,
                code=connection_status.return_code,
                abnormal=True,
                abnormal_reason="connection_lost",
                event_label="abnormal"
            )


def main() -> None:
    # Training logger (30 minute session)
    data_logger = DataLogger(label="normal", duration_minutes=30)
    live_observer = RealTimeObserver(log_file_path=data_logger.file_path)
    live_observer.start()

    event_logger.log_event(router_config.EVENT_SYSTEM_START)
    data_logger.log_event(router_config.EVENT_SYSTEM_START)

    ser = None
    previous_state = None
    disconnect_started_at = None

    try:
        ser = proto_reader.connect_serial()
        event_logger.log_event(router_config.EVENT_SERIAL_CONNECTED)
        data_logger.log_event(router_config.EVENT_SERIAL_CONNECTED)

        boot_result = led_controller.send_state(ser, router_config.STATE_BOOTING)
        _log_led_result(boot_result, router_config.STATE_BOOTING, data_logger)

        while True:
            connection_status = connection_check.get_connection_status()
            current_state = _determine_system_state(connection_status.is_connected)

            if previous_state != router_config.STATE_DISCONNECTED and current_state == router_config.STATE_DISCONNECTED:
                disconnect_started_at = time.time()

            _log_connection_event(
                connection_status=connection_status,
                previous_state=previous_state,
                current_state=current_state,
                data_logger=data_logger,
                disconnect_started_at=disconnect_started_at,
            )

            previous_state = _handle_state_transition(
                ser=ser,
                previous_state=previous_state,
                current_state=current_state,
                data_logger=data_logger,
                disconnect_started_at=disconnect_started_at,
            )

            if disconnect_started_at is not None and current_state == router_config.STATE_CONNECTED:
                disconnect_started_at = None

            _log_arduino_response(ser, data_logger)

            time.sleep(router_config.CHECK_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        pass

    except Exception as error:
        event_logger.log_event(f"ERROR -> {error}")
        data_logger.log_event(
            "ERROR",
            message=str(error),
            abnormal=True,
            abnormal_reason="main_loop_exception",
            event_label="abnormal"
        )

        if ser is not None:
            error_result = led_controller.send_state(ser, router_config.STATE_ERROR)
            _log_led_result(error_result, router_config.STATE_ERROR, data_logger)

    finally:
        live_observer.stop()

        if ser is not None:
            proto_reader.close_serial(ser)
            event_logger.log_event(router_config.EVENT_SERIAL_DISCONNECTED)
            data_logger.log_event(router_config.EVENT_SERIAL_DISCONNECTED)

        event_logger.log_event(router_config.EVENT_SYSTEM_STOP)
        data_logger.log_event(router_config.EVENT_SYSTEM_STOP)

        data_logger.stop()


if __name__ == "__main__":
    main()
# =========================
#===================================
# Notes on what changed
# ============================================================
# 1. Added a real module header so router_monitor reads like a production orchestration file.
# 2. Broke the monolithic logic into smaller orchestration helpers:
#       _determine_system_state()
#       _log_led_result()
#       _handle_state_transition()
#       _log_arduino_response()
# 3. Replaced hardcoded string events with config-backed event constants where appropriate.
# 4. Replaced direct LED role calls with led_controller.send_state(), which is more scalable.
# 5. Moved state-transition behavior into one function so the main loop stays cleaner.
# 6. Upgraded connection monitoring to use connection_check.get_connection_status()
#    instead of only a boolean, allowing richer logging and future AI visibility.
# 7. Replaced CHECK_INTERVAL with CHECK_INTERVAL_SECONDS to match the tightened config design.
# 8. Added structured logging for outbound LED command success/failure.
# 9. Kept Arduino inbound message polling in its own helper for cleaner orchestration.
# 10. Added explicit boot-state signaling through the unified LED state interface.
# 11. Added error-state signaling so hardware can reflect failures when exceptions occur.
# 12. Preserved the system-wide architecture:
#       router_monitor runs everything together
#       each module still owns its own responsibility
# 13. Shifted the file closer to an industry-style controller/orchestrator pattern
#     instead of a single procedural loop with inline handling everywhere.


# run on:
# cd C:\Users\kevin\CLionProjects\WeekProject\Router
# C:\Users\kevin\CLionProjects\RF_module\.venv\Scripts\python.exe router_monitor.py
