from __future__ import annotations

import csv
import json
from collections import deque
from pathlib import Path
from typing import Any


class TrainingParser:
    """
    Parses DataLogger JSONL files from training_logs/ and prepares
    event-level and window-level datasets for model training.

    Outputs:
        data/prepared_events.jsonl
        data/prepared_events.csv
        data/prepared_windows.jsonl
        data/prepared_windows.csv
    """

    def __init__(self) -> None:
        base_dir = Path(__file__).parent
        self.training_dir = base_dir / "training_logs"
        self.output_dir = base_dir / "data"
        self.output_dir.mkdir(exist_ok=True)

        self.event_jsonl_path = self.output_dir / "prepared_events.jsonl"
        self.event_csv_path = self.output_dir / "prepared_events.csv"
        self.window_jsonl_path = self.output_dir / "prepared_windows.jsonl"
        self.window_csv_path = self.output_dir / "prepared_windows.csv"

        self.window_size = 12

    def run(self) -> None:
        files = sorted(self.training_dir.glob("session_*.jsonl"))

        if not files:
            print(f"No training log files found in: {self.training_dir}")
            return

        all_event_rows: list[dict[str, Any]] = []
        all_window_rows: list[dict[str, Any]] = []

        for file_path in files:
            session_events = self._read_jsonl(file_path)
            if not session_events:
                continue

            event_rows, window_rows = self._parse_session(session_events, file_path.name)
            all_event_rows.extend(event_rows)
            all_window_rows.extend(window_rows)

        self._write_jsonl(self.event_jsonl_path, all_event_rows)
        self._write_csv(self.event_csv_path, all_event_rows)

        self._write_jsonl(self.window_jsonl_path, all_window_rows)
        self._write_csv(self.window_csv_path, all_window_rows)

        print(f"Parsed {len(files)} file(s).")
        print(f"Event rows:  {len(all_event_rows)}")
        print(f"Window rows: {len(all_window_rows)}")
        print(f"Saved: {self.event_jsonl_path}")
        print(f"Saved: {self.event_csv_path}")
        print(f"Saved: {self.window_jsonl_path}")
        print(f"Saved: {self.window_csv_path}")

    def _read_jsonl(self, file_path: Path) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []

        with open(file_path, "r", encoding="utf-8") as file:
            for line_number, line in enumerate(file, start=1):
                line = line.strip()
                if not line:
                    continue

                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as error:
                    print(f"Skipping bad JSON in {file_path.name}:{line_number} -> {error}")

        rows.sort(key=lambda item: item.get("event_index", 0))
        return rows

    def _parse_session(
            self,
            session_events: list[dict[str, Any]],
            source_file: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        event_rows: list[dict[str, Any]] = []
        window_rows: list[dict[str, Any]] = []

        previous_elapsed = None
        previous_event = None
        previous_label = None

        current_state = None
        disconnect_started_at = None
        disconnect_count = 0
        reconnect_count = 0

        event_window: deque[dict[str, Any]] = deque(maxlen=self.window_size)

        for item in session_events:
            data = item.get("data", {}) or {}

            elapsed_seconds = float(item.get("elapsed_seconds", 0.0))
            event_name = str(item.get("event", "UNKNOWN"))
            label = str(item.get("label", "normal"))
            session_label = str(item.get("session_label", label))
            event_index = int(item.get("event_index", 0))
            session_id = str(item.get("session_id", "unknown"))

            delta_seconds = 0.0 if previous_elapsed is None else max(0.0, elapsed_seconds - previous_elapsed)

            abnormal = 1 if label == "abnormal" or bool(data.get("abnormal", False)) else 0
            abnormal_reason = data.get("abnormal_reason") or ""

            state_changed_to_connected = 0
            state_changed_to_disconnected = 0

            if event_name == "STATE_CHANGED":
                state_value = data.get("state")
                if state_value == "CONNECTED":
                    current_state = "CONNECTED"
                    state_changed_to_connected = 1

                    if disconnect_started_at is not None:
                        reconnect_count += 1
                        disconnect_started_at = None

                elif state_value == "DISCONNECTED":
                    current_state = "DISCONNECTED"
                    state_changed_to_disconnected = 1
                    disconnect_count += 1

                    if disconnect_started_at is None:
                        disconnect_started_at = elapsed_seconds

            reconnect_duration_seconds = data.get("reconnect_duration_seconds")
            if reconnect_duration_seconds is None:
                reconnect_duration_seconds = 0.0
            else:
                reconnect_duration_seconds = float(reconnect_duration_seconds)

            row = {
                "source_file": source_file,
                "session_id": session_id,
                "event_index": event_index,
                "elapsed_seconds": round(elapsed_seconds, 3),
                "delta_seconds": round(delta_seconds, 3),
                "event": event_name,
                "label": label,
                "session_label": session_label,
                "abnormal": abnormal,
                "abnormal_reason": abnormal_reason,
                "current_state": current_state or "",
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
                "disconnect_count_so_far": disconnect_count,
                "reconnect_count_so_far": reconnect_count,
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
                "previous_event": previous_event or "",
                "previous_label": previous_label or "",
            }

            event_rows.append(row)
            event_window.append(row)

            if len(event_window) == self.window_size:
                window_rows.append(self._build_window_row(list(event_window)))

            previous_elapsed = elapsed_seconds
            previous_event = event_name
            previous_label = label

        return event_rows, window_rows

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

        reconnect_values = [row["reconnect_duration_seconds"] for row in window if row["reconnect_duration_seconds"] > 0]
        command_duration_values = [row["command_duration_seconds"] for row in window if row["command_duration_seconds"] > 0]
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

    def _write_jsonl(self, file_path: Path, rows: list[dict[str, Any]]) -> None:
        with open(file_path, "w", encoding="utf-8") as file:
            for row in rows:
                file.write(json.dumps(row) + "\n")

    def _write_csv(self, file_path: Path, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return

        fieldnames = list(rows[0].keys())

        with open(file_path, "w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    @staticmethod
    def _safe_float(value: Any) -> float:
        if value in (None, ""):
            return 0.0
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _safe_int(value: Any) -> int:
        if value in (None, ""):
            return 0
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0


def main() -> None:
    parser = TrainingParser()
    parser.run()


if __name__ == "__main__":
    main()