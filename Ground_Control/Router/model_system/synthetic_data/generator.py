from __future__ import annotations

import csv
import json
import random
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class GeneratorConfig:
    session_count: int = 120
    min_events_per_session: int = 80
    max_events_per_session: int = 220
    abnormal_session_ratio: float = 0.55
    window_size: int = 12
    seed: int = 42


class SyntheticPreparedDataGenerator:
    """
    Generates synthetic prepared event rows and prepared window rows
    in the same format your existing model pipeline expects.
    """

    def __init__(self, config: GeneratorConfig | None = None) -> None:
        self.config = config or GeneratorConfig()

        base_dir = Path(__file__).resolve().parent
        self.output_dir = base_dir / "data"
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.events_jsonl_path = self.output_dir / "prepared_events.jsonl"
        self.events_csv_path = self.output_dir / "prepared_events.csv"
        self.windows_jsonl_path = self.output_dir / "prepared_windows.jsonl"
        self.windows_csv_path = self.output_dir / "prepared_windows.csv"

        random.seed(self.config.seed)

    def run(self) -> None:
        all_event_rows: list[dict[str, Any]] = []
        all_window_rows: list[dict[str, Any]] = []

        for session_number in range(1, self.config.session_count + 1):
            session_label = (
                "abnormal"
                if random.random() < self.config.abnormal_session_ratio
                else "normal"
            )

            event_rows = self._generate_session(session_number, session_label)
            window_rows = self._build_windows(event_rows)

            all_event_rows.extend(event_rows)
            all_window_rows.extend(window_rows)

        self._write_jsonl(self.events_jsonl_path, all_event_rows)
        self._write_csv(self.events_csv_path, all_event_rows)

        self._write_jsonl(self.windows_jsonl_path, all_window_rows)
        self._write_csv(self.windows_csv_path, all_window_rows)

        print("Synthetic prepared data created.")
        print(f"Sessions: {self.config.session_count}")
        print(f"Event rows: {len(all_event_rows)}")
        print(f"Window rows: {len(all_window_rows)}")
        print(f"Saved: {self.events_jsonl_path}")
        print(f"Saved: {self.events_csv_path}")
        print(f"Saved: {self.windows_jsonl_path}")
        print(f"Saved: {self.windows_csv_path}")

    def _generate_session(self, session_number: int, session_label: str) -> list[dict[str, Any]]:
        session_id = str(uuid.uuid4())[:8]
        source_file = f"synthetic_session_{session_number:04d}_{session_label}.jsonl"

        event_rows: list[dict[str, Any]] = []

        event_count = random.randint(
            self.config.min_events_per_session,
            self.config.max_events_per_session,
        )

        current_state = "CONNECTED"
        elapsed_seconds = 0.0
        disconnect_count = 0
        reconnect_count = 0
        previous_event = ""
        previous_label = session_label

        pending_reconnect_duration = 0.0
        disconnected = False

        for event_index in range(1, event_count + 1):
            row = self._make_base_row(
                source_file=source_file,
                session_id=session_id,
                event_index=event_index,
                elapsed_seconds=elapsed_seconds,
                previous_event=previous_event,
                previous_label=previous_label,
                session_label=session_label,
                current_state=current_state,
                disconnect_count=disconnect_count,
                reconnect_count=reconnect_count,
            )

            event_type, delta_seconds = self._choose_next_event(
                session_label=session_label,
                current_state=current_state,
                disconnected=disconnected,
            )

            elapsed_seconds += delta_seconds
            row["elapsed_seconds"] = round(elapsed_seconds, 3)
            row["delta_seconds"] = round(delta_seconds, 3)
            row["event"] = event_type

            if event_type == "ARDUINO_RESPONSE":
                row["is_arduino_response"] = 1
                if current_state == "CONNECTED":
                    row["has_response_ack_connected"] = 1
                else:
                    row["has_response_ack_disconnected"] = 1

            elif event_type == "GENERATOR_ACTION":
                row["is_generator_action"] = 1
                row["network_target"] = 1
                row["downtime_seconds"] = round(random.uniform(3.0, 12.0), 3)

            elif event_type == "GENERATOR_COMMAND_RESULT":
                row["is_generator_command_result"] = 1
                row["network_target"] = 1

                command_success = self._sample_command_success(session_label)
                row["command_success"] = 1 if command_success else 0
                row["command_failed"] = 0 if command_success else 1
                row["command_returncode"] = 0 if command_success else random.choice([1, -1, 3221225786])
                row["command_duration_seconds"] = round(
                    random.uniform(0.8, 7.0) if command_success else random.uniform(8.0, 22.0),
                    3,
                )

                if not command_success:
                    row["abnormal"] = 1
                    row["label"] = "abnormal"
                    row["abnormal_reason"] = "synthetic_command_failure"

            elif event_type == "LED_COMMAND_SENT":
                row["is_led_command_sent"] = 1

            elif event_type == "CONNECTION_LOST":
                row["is_connection_lost"] = 1
                disconnected = True
                current_state = "DISCONNECTED"
                disconnect_count += 1
                row["current_state"] = current_state
                row["disconnect_count_so_far"] = disconnect_count
                row["abnormal"] = 1
                row["label"] = "abnormal"
                row["abnormal_reason"] = "synthetic_connection_lost"

                pending_reconnect_duration = self._sample_reconnect_duration(session_label)

            elif event_type == "CONNECTION_ESTABLISHED":
                row["is_connection_established"] = 1
                current_state = "CONNECTED"
                disconnected = False
                reconnect_count += 1
                row["current_state"] = current_state
                row["reconnect_count_so_far"] = reconnect_count
                row["reconnect_duration_seconds"] = round(pending_reconnect_duration, 3)

                if pending_reconnect_duration >= 15.0:
                    row["abnormal"] = 1
                    row["label"] = "abnormal"
                    row["abnormal_reason"] = "synthetic_slow_reconnect"

                pending_reconnect_duration = 0.0

            elif event_type == "CONNECTION_CHECK_FAILED":
                row["is_connection_check_failed"] = 1
                row["abnormal"] = 1
                row["label"] = "abnormal"
                row["abnormal_reason"] = "synthetic_connection_check_failed"

            elif event_type == "STATE_CHANGED":
                if current_state == "CONNECTED":
                    row["state_changed_to_connected"] = 1
                else:
                    row["state_changed_to_disconnected"] = 1

                if current_state == "DISCONNECTED":
                    row["abnormal"] = 1
                    row["label"] = "abnormal"
                    if not row["abnormal_reason"]:
                        row["abnormal_reason"] = "synthetic_state_disconnected"

            elif event_type == "ERROR":
                row["is_error"] = 1
                row["abnormal"] = 1
                row["label"] = "abnormal"
                row["abnormal_reason"] = "synthetic_runtime_error"

            row["current_state"] = current_state
            row["disconnect_count_so_far"] = disconnect_count
            row["reconnect_count_so_far"] = reconnect_count

            event_rows.append(row)
            previous_event = row["event"]
            previous_label = row["label"]

        return event_rows

    def _choose_next_event(self, session_label: str, current_state: str, disconnected: bool) -> tuple[str, float]:
        if disconnected:
            choices = [
                ("STATE_CHANGED", 0.18),
                ("ARDUINO_RESPONSE", 0.16),
                ("GENERATOR_COMMAND_RESULT", 0.16),
                ("CONNECTION_ESTABLISHED", 0.26),
                ("CONNECTION_CHECK_FAILED", 0.10),
                ("ERROR", 0.04 if session_label == "abnormal" else 0.01),
                ("LED_COMMAND_SENT", 0.10),
            ]
        else:
            choices = [
                ("ARDUINO_RESPONSE", 0.26),
                ("GENERATOR_ACTION", 0.12),
                ("GENERATOR_COMMAND_RESULT", 0.14),
                ("LED_COMMAND_SENT", 0.10),
                ("CONNECTION_LOST", 0.14 if session_label == "normal" else 0.22),
                ("STATE_CHANGED", 0.08),
                ("CONNECTION_CHECK_FAILED", 0.08 if session_label == "normal" else 0.12),
                ("ERROR", 0.02 if session_label == "normal" else 0.06),
                ("CONNECTION_ESTABLISHED", 0.04),
            ]

        event_type = self._weighted_choice(choices)

        if event_type == "CONNECTION_ESTABLISHED":
            delta_seconds = random.uniform(4.0, 30.0)
        elif event_type == "CONNECTION_LOST":
            delta_seconds = random.uniform(1.0, 8.0)
        elif event_type == "GENERATOR_COMMAND_RESULT":
            delta_seconds = random.uniform(1.0, 7.0)
        elif event_type == "GENERATOR_ACTION":
            delta_seconds = random.uniform(4.0, 20.0)
        elif event_type == "ARDUINO_RESPONSE":
            delta_seconds = random.uniform(1.0, 6.0)
        elif event_type == "ERROR":
            delta_seconds = random.uniform(1.0, 10.0)
        else:
            delta_seconds = random.uniform(1.0, 5.0)

        return event_type, delta_seconds

    def _sample_command_success(self, session_label: str) -> bool:
        if session_label == "abnormal":
            return random.random() < 0.68
        return random.random() < 0.90

    def _sample_reconnect_duration(self, session_label: str) -> float:
        if session_label == "abnormal":
            if random.random() < 0.55:
                return random.uniform(15.0, 40.0)
            return random.uniform(5.0, 14.5)
        return random.uniform(2.0, 12.0)

    def _make_base_row(
            self,
            source_file: str,
            session_id: str,
            event_index: int,
            elapsed_seconds: float,
            previous_event: str,
            previous_label: str,
            session_label: str,
            current_state: str,
            disconnect_count: int,
            reconnect_count: int,
    ) -> dict[str, Any]:
        return {
            "source_file": source_file,
            "session_id": session_id,
            "event_index": event_index,
            "elapsed_seconds": round(elapsed_seconds, 3),
            "delta_seconds": 0.0,
            "event": "",
            "label": session_label,
            "session_label": session_label,
            "abnormal": 1 if session_label == "abnormal" else 0,
            "abnormal_reason": "",
            "current_state": current_state,
            "state_changed_to_connected": 0,
            "state_changed_to_disconnected": 0,
            "is_connection_lost": 0,
            "is_connection_established": 0,
            "is_connection_check_failed": 0,
            "is_arduino_response": 0,
            "is_led_command_sent": 0,
            "is_generator_action": 0,
            "is_generator_command_result": 0,
            "is_error": 0,
            "disconnect_count_so_far": disconnect_count,
            "reconnect_count_so_far": reconnect_count,
            "reconnect_duration_seconds": 0.0,
            "has_response_ack_connected": 0,
            "has_response_ack_disconnected": 0,
            "command_success": 0,
            "command_failed": 0,
            "command_returncode": 0,
            "command_duration_seconds": 0.0,
            "downtime_seconds": 0.0,
            "network_target": 0,
            "arduino_target": 0,
            "previous_event": previous_event,
            "previous_label": previous_label,
        }

    def _build_windows(self, event_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        windows: list[dict[str, Any]] = []
        queue: deque[dict[str, Any]] = deque(maxlen=self.config.window_size)

        for row in event_rows:
            queue.append(row)
            if len(queue) == self.config.window_size:
                windows.append(self._build_window_row(list(queue)))

        return windows

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

    @staticmethod
    def _weighted_choice(choices: list[tuple[str, float]]) -> str:
        total = sum(weight for _, weight in choices)
        pick = random.uniform(0.0, total)
        current = 0.0

        for name, weight in choices:
            current += weight
            if pick <= current:
                return name

        return choices[-1][0]

    @staticmethod
    def _write_jsonl(file_path: Path, rows: list[dict[str, Any]]) -> None:
        with open(file_path, "w", encoding="utf-8") as file:
            for row in rows:
                file.write(json.dumps(row) + "\n")

    @staticmethod
    def _write_csv(file_path: Path, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return

        with open(file_path, "w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)


def main() -> None:
    generator = SyntheticPreparedDataGenerator(
        GeneratorConfig(
            session_count=200,
            min_events_per_session=100,
            max_events_per_session=260,
            abnormal_session_ratio=0.50,
            window_size=12,
            seed=42,
        )
    )
    generator.run()


if __name__ == "__main__":
    main()
