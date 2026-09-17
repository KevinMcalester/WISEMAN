from __future__ import annotations

import json
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

from ground_control.Router import router_config
from ground_control.Router.model_system.src.predictor import Predictor


class RealTimeObserver:
    """
    Watches a live DataLogger JSONL file, converts raw log entries into
    prepared event rows/windows, runs model predictions, and prints alerts.

    It does NOT retrain anything.
    It uses the trained model + scaler already saved in model_system/models/saved.
    """

    def __init__(
            self,
            log_file_path: str | Path,
            poll_interval_seconds: float = 0.5,
            window_size: int = 12,
    ) -> None:
        self.log_file_path = Path(log_file_path)
        self.poll_interval_seconds = poll_interval_seconds
        self.window_size = window_size

        self.predictor = Predictor()

        self.active = False
        self.thread: threading.Thread | None = None
        self.file_position = 0

        self.event_window: deque[dict[str, Any]] = deque(maxlen=self.window_size)

        self.previous_event = ""
        self.previous_label = ""
        self.current_state = ""
        self.disconnect_count = 0
        self.reconnect_count = 0
        self.last_elapsed_seconds: float | None = None
        self.last_alerted_window_end: int | None = None

    def start(self) -> None:
        if self.active:
            return

        self.active = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

        print(f"[LIVE_OBSERVER] Watching: {self.log_file_path}")

    def stop(self) -> None:
        self.active = False

        if self.thread is not None and self.thread.is_alive():
            self.thread.join(timeout=2)

        print("[LIVE_OBSERVER] Stopped.")

    def _run_loop(self) -> None:
        while self.active:
            try:
                self._process_new_lines()
            except Exception as error:
                print(f"[LIVE_OBSERVER][ERROR] {error}")

            time.sleep(self.poll_interval_seconds)

    def _process_new_lines(self) -> None:
        if not self.log_file_path.exists():
            return

        with open(self.log_file_path, "r", encoding="utf-8") as file:
            file.seek(self.file_position)

            while self.active:
                line = file.readline()
                if not line:
                    break

                self.file_position = file.tell()
                line = line.strip()
                if not line:
                    continue

                try:
                    raw_entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                prepared_event = self._convert_raw_entry_to_prepared_event(raw_entry)
                self.event_window.append(prepared_event)

                if len(self.event_window) == self.window_size:
                    window_row = self._build_window_row(list(self.event_window))
                    self._predict_and_report(window_row)

    def _convert_raw_entry_to_prepared_event(self, raw_entry: dict[str, Any]) -> dict[str, Any]:
        data = raw_entry.get("data", {}) or {}

        session_id = str(raw_entry.get("session_id", "unknown"))
        event_index = int(raw_entry.get("event_index", 0))
        elapsed_seconds = float(raw_entry.get("elapsed_seconds", 0.0))
        event_name = str(raw_entry.get("event", "UNKNOWN"))
        label = str(raw_entry.get("label", "normal"))
        session_label = str(raw_entry.get("session_label", label))

        delta_seconds = 0.0
        if self.last_elapsed_seconds is not None:
            delta_seconds = max(0.0, elapsed_seconds - self.last_elapsed_seconds)

        abnormal = 1 if (label == "abnormal" or bool(data.get("abnormal", False))) else 0
        abnormal_reason = str(data.get("abnormal_reason") or "")

        state_changed_to_connected = 0
        state_changed_to_disconnected = 0
        reconnect_duration_seconds = self._safe_float(data.get("reconnect_duration_seconds"))

        if event_name == "STATE_CHANGED":
            state_value = str(data.get("state", ""))

            if state_value == "CONNECTED":
                self.current_state = "CONNECTED"
                state_changed_to_connected = 1
                self.reconnect_count += 1

            elif state_value == "DISCONNECTED":
                self.current_state = "DISCONNECTED"
                state_changed_to_disconnected = 1
                self.disconnect_count += 1

        elif event_name == "CONNECTION_LOST":
            self.current_state = "DISCONNECTED"
            self.disconnect_count += 1

        elif event_name == "CONNECTION_ESTABLISHED":
            self.current_state = "CONNECTED"
            self.reconnect_count += 1

        row = {
            "source_file": self.log_file_path.name,
            "session_id": session_id,
            "event_index": event_index,
            "elapsed_seconds": round(elapsed_seconds, 3),
            "delta_seconds": round(delta_seconds, 3),
            "event": event_name,
            "label": label,
            "session_label": session_label,
            "abnormal": abnormal,
            "abnormal_reason": abnormal_reason,
            "current_state": self.current_state,
            "state_changed_to_connected": state_changed_to_connected,
            "state_changed_to_disconnected": state_changed_to_disconnected,
            "is_connection_lost": 1 if event_name == "CONNECTION_LOST" else 0,
            "is_connection_established": 1 if event_name == "CONNECTION_ESTABLISHED" else 0,
            "is_connection_check_failed": 1 if event_name == "CONNECTION_CHECK_FAILED" else 0,
            "is_arduino_response": 1 if event_name == "ARDUINO_RESPONSE" else 0,
            "is_led_command_sent": 1 if event_name == "LED_COMMAND_SENT" else 0,
            "is_generator_action": 1 if event_name == "GENERATOR_ACTION" else 0,
            "is_generator_command_result": 1 if event_name == "GENERATOR_COMMAND_RESULT" else 0,
            "is_error": 1 if event_name == "ERROR" else 0,
            "disconnect_count_so_far": self.disconnect_count,
            "reconnect_count_so_far": self.reconnect_count,
            "reconnect_duration_seconds": round(reconnect_duration_seconds, 3),
            "has_response_ack_connected": 1 if data.get("response") == "ACK:CONNECTED" else 0,
            "has_response_ack_disconnected": 1 if data.get("response") == "ACK:DISCONNECTED" else 0,
            "command_success": 1 if data.get("success") is True else 0,
            "command_failed": 1 if data.get("success") is False else 0,
            "command_returncode": self._safe_int(data.get("returncode")),
            "command_duration_seconds": self._safe_float(data.get("command_duration_seconds")),
            "downtime_seconds": self._safe_float(data.get("downtime_seconds")),
            "network_target": 1 if data.get("target") == "network" else 0,
            "arduino_target": 1 if data.get("target") == "arduino" else 0,
            "previous_event": self.previous_event,
            "previous_label": self.previous_label,
        }

        self.previous_event = event_name
        self.previous_label = label
        self.last_elapsed_seconds = elapsed_seconds

        return row

    def _build_window_row(self, window: list[dict[str, Any]]) -> dict[str, Any]:
        first = window[0]
        last = window[-1]

        connection_lost_count = sum(row["is_connection_lost"] for row in window)
        connection_established_count = sum(row["is_connection_established"] for row in window)
        connection_check_failed_count = sum(row["is_connection_check_failed"] for row in window)
        arduino_response_count = sum(row["is_arduino_response"] for row in window)
        led_command_count = sum(row["is_led_command_sent"] for row in window)
        generator_action_count = sum(row["is_generator_action"] for row in window)
        generator_command_result_count = sum(row["is_generator_command_result"] for row in window)
        error_count = sum(row["is_error"] for row in window)
        abnormal_count = sum(row["abnormal"] for row in window)
        command_failed_count = sum(row["command_failed"] for row in window)

        reconnect_values = [
            row["reconnect_duration_seconds"]
            for row in window
            if row["reconnect_duration_seconds"] > 0
        ]
        command_duration_values = [
            row["command_duration_seconds"]
            for row in window
            if row["command_duration_seconds"] > 0
        ]
        delta_values = [row["delta_seconds"] for row in window]

        window_label = "abnormal" if abnormal_count > 0 else "normal"

        return {
            "source_file": last["source_file"],
            "session_id": last["session_id"],
            "start_event_index": first["event_index"],
            "end_event_index": last["event_index"],
            "start_elapsed_seconds": first["elapsed_seconds"],
            "end_elapsed_seconds": last["elapsed_seconds"],
            "window_span_seconds": round(last["elapsed_seconds"] - first["elapsed_seconds"], 3),
            "window_size": len(window),
            "connection_lost_count": connection_lost_count,
            "connection_established_count": connection_established_count,
            "connection_check_failed_count": connection_check_failed_count,
            "arduino_response_count": arduino_response_count,
            "led_command_count": led_command_count,
            "generator_action_count": generator_action_count,
            "generator_command_result_count": generator_command_result_count,
            "error_count": error_count,
            "abnormal_count": abnormal_count,
            "command_failed_count": command_failed_count,
            "max_reconnect_duration_seconds": round(max(reconnect_values), 3) if reconnect_values else 0.0,
            "avg_reconnect_duration_seconds": round(sum(reconnect_values) / len(reconnect_values), 3) if reconnect_values else 0.0,
            "max_command_duration_seconds": round(max(command_duration_values), 3) if command_duration_values else 0.0,
            "avg_command_duration_seconds": round(sum(command_duration_values) / len(command_duration_values), 3) if command_duration_values else 0.0,
            "avg_delta_seconds": round(sum(delta_values) / len(delta_values), 3) if delta_values else 0.0,
            "last_event": last["event"],
            "last_state": last["current_state"],
            "window_label": window_label,
            "session_label": last["session_label"],
        }

    def _predict_and_report(self, window_row: dict[str, Any]) -> None:
        end_event_index = int(window_row["end_event_index"])

        if self.last_alerted_window_end == end_event_index:
            return

        self.last_alerted_window_end = end_event_index
        prediction = self.predictor.predict_row(window_row)

        abnormal_probability = float(prediction["abnormal_probability"])
        predicted_label = str(prediction["predicted_label"])
        severity = str(prediction["severity"])

        issues: list[str] = []

        if predicted_label == router_config.ABNORMAL_LABEL:
            issues.append("model_predicted_abnormal_behavior")

        if window_row["connection_lost_count"] >= router_config.HIGH_CONNECTION_LOST_COUNT:
            issues.append("repeated_connection_loss")

        if window_row["command_failed_count"] >= router_config.HIGH_COMMAND_FAILURE_COUNT:
            issues.append("repeated_command_failures")

        if window_row["max_reconnect_duration_seconds"] >= router_config.SLOW_RECONNECT_SECONDS:
            issues.append("slow_reconnect_detected")

        if window_row["connection_check_failed_count"] > 0:
            issues.append("connection_check_failures_present")

        if window_row["error_count"] > 0:
            issues.append("runtime_errors_present")

        if severity in ("warning", "critical") or issues:
            print(
                "[LIVE_OBSERVER] "
                f"session={window_row['session_id']} "
                f"window={window_row['start_event_index']}->{window_row['end_event_index']} "
                f"label={predicted_label} "
                f"abnormal_probability={abnormal_probability:.4f} "
                f"severity={severity} "
                f"issues={issues}"
            )

    @staticmethod
    def _safe_float(value: Any) -> float:
        if value in (None, "", "None"):
            return 0.0
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _safe_int(value: Any) -> int:
        if value in (None, "", "None"):
            return 0
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0


def main() -> None:
    example_log_path = Path(__file__).resolve().parents[2] / "training_logs" / "session_example.jsonl"
    observer = RealTimeObserver(log_file_path=example_log_path)
    observer.start()

    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        observer.stop()


if __name__ == "__main__":
    main()
