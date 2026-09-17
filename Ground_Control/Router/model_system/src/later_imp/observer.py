from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from ground_control.Router.model_system.src import model_config
from ground_control.Router.model_system.src.predictor import Predictor


class Observer:
    """
    Observes prepared model input rows, runs predictions,
    flags likely issues, and writes a readable report.
    """

    def __init__(self) -> None:
        self.predictor = Predictor()

    def observe_csv(self, csv_path: Path | None = None) -> list[dict[str, Any]]:
        target_path = csv_path or model_config.get_active_dataset_csv()

        if not target_path.exists():
            raise FileNotFoundError(f"Observation CSV not found: {target_path}")

        dataframe = pd.read_csv(target_path)
        rows = dataframe.to_dict(orient="records")

        observations: list[dict[str, Any]] = []

        for row in rows:
            prediction = self.predictor.predict_row(row)
            issues = self._detect_issues(row, prediction)

            observation = dict(row)
            observation.update(prediction)
            observation["issues"] = issues
            observation["issue_count"] = len(issues)
            observation["needs_attention"] = len(issues) > 0

            observations.append(observation)

        return observations

    def save_observations(
            self,
            observations: list[dict[str, Any]],
            csv_path: Path | None = None,
            jsonl_path: Path | None = None,
    ) -> None:
        csv_target = csv_path or model_config.PREDICTIONS_CSV
        jsonl_target = jsonl_path or model_config.PREDICTIONS_JSONL

        flattened_rows: list[dict[str, Any]] = []
        for row in observations:
            flattened = dict(row)
            flattened["issues"] = " | ".join(row.get("issues", []))
            flattened_rows.append(flattened)

        if flattened_rows:
            dataframe = pd.DataFrame(flattened_rows)
            dataframe.to_csv(csv_target, index=False)

        with open(jsonl_target, "w", encoding="utf-8") as file:
            for row in observations:
                file.write(json.dumps(row) + "\n")

    def build_report_text(self, observations: list[dict[str, Any]]) -> str:
        total_rows = len(observations)
        abnormal_predictions = sum(
            1 for row in observations if row.get("predicted_label") == model_config.ABNORMAL_LABEL
        )
        warning_rows = sum(1 for row in observations if row.get("severity") == "warning")
        critical_rows = sum(1 for row in observations if row.get("severity") == "critical")
        rows_with_issues = sum(1 for row in observations if row.get("needs_attention"))

        lines: list[str] = []
        lines.append("Router Observer Report")
        lines.append("=" * 60)
        lines.append(f"Total observed rows: {total_rows}")
        lines.append(f"Predicted abnormal rows: {abnormal_predictions}")
        lines.append(f"Warning rows: {warning_rows}")
        lines.append(f"Critical rows: {critical_rows}")
        lines.append(f"Rows with detected issues: {rows_with_issues}")
        lines.append("")

        high_priority_rows = [
            row for row in observations
            if row.get("severity") in ("warning", "critical") or row.get("needs_attention")
        ]

        if not high_priority_rows:
            lines.append("No major issues detected.")
            return "\n".join(lines)

        lines.append("Highlighted observations")
        lines.append("-" * 60)

        for index, row in enumerate(high_priority_rows[:20], start=1):
            identifier = self._get_row_identifier(row)
            lines.append(f"{index}. {identifier}")
            lines.append(f"   predicted_label: {row.get('predicted_label')}")
            lines.append(f"   abnormal_probability: {row.get('abnormal_probability')}")
            lines.append(f"   severity: {row.get('severity')}")

            issues = row.get("issues", [])
            if issues:
                lines.append(f"   issues: {', '.join(issues)}")

            lines.append("")

        return "\n".join(lines)

    def save_report(self, observations: list[dict[str, Any]], report_path: Path | None = None) -> None:
        target_path = report_path or model_config.LATEST_REPORT_FILE
        report_text = self.build_report_text(observations)

        with open(target_path, "w", encoding="utf-8") as file:
            file.write(report_text)

    def _detect_issues(self, row: dict[str, Any], prediction: dict[str, Any]) -> list[str]:
        issues: list[str] = []

        abnormal_probability = float(prediction.get("abnormal_probability", 0.0))

        if prediction.get("predicted_label") == model_config.ABNORMAL_LABEL:
            issues.append("model_predicted_abnormal_behavior")

        if abnormal_probability >= model_config.CRITICAL_PROBABILITY_THRESHOLD:
            issues.append("critical_model_confidence")
        elif abnormal_probability >= model_config.WARNING_PROBABILITY_THRESHOLD:
            issues.append("warning_model_confidence")

        connection_lost_count = self._safe_int(row.get("connection_lost_count"))
        if connection_lost_count >= model_config.HIGH_CONNECTION_LOST_COUNT:
            issues.append("repeated_connection_loss")

        command_failed_count = self._safe_int(row.get("command_failed_count"))
        if command_failed_count >= model_config.HIGH_COMMAND_FAILURE_COUNT:
            issues.append("repeated_command_failures")

        max_reconnect_duration_seconds = self._safe_float(row.get("max_reconnect_duration_seconds"))
        if max_reconnect_duration_seconds >= model_config.SLOW_RECONNECT_SECONDS:
            issues.append("slow_reconnect_detected")

        connection_check_failed_count = self._safe_int(row.get("connection_check_failed_count"))
        if connection_check_failed_count > 0:
            issues.append("connection_check_failures_present")

        error_count = self._safe_int(row.get("error_count"))
        if error_count > 0:
            issues.append("runtime_errors_present")

        abnormal_count = self._safe_int(row.get("abnormal_count"))
        if abnormal_count > 0:
            issues.append("abnormal_events_present_in_window")

        return issues

    @staticmethod
    def _get_row_identifier(row: dict[str, Any]) -> str:
        session_id = row.get("session_id", "unknown_session")
        start_event_index = row.get("start_event_index")
        end_event_index = row.get("end_event_index")

        if start_event_index is not None and end_event_index is not None:
            return f"session={session_id} window={start_event_index}->{end_event_index}"

        event_index = row.get("event_index")
        if event_index is not None:
            return f"session={session_id} event={event_index}"

        return f"session={session_id}"

    @staticmethod
    def _safe_int(value: Any) -> int:
        if value in (None, "", "None"):
            return 0
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _safe_float(value: Any) -> float:
        if value in (None, "", "None"):
            return 0.0
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0


def main() -> None:
    observer = Observer()
    observations = observer.observe_csv()
    observer.save_observations(observations)
    observer.save_report(observations)

    print(f"Observed rows: {len(observations)}")
    print(f"Saved predictions CSV:   {model_config.PREDICTIONS_CSV}")
    print(f"Saved predictions JSONL: {model_config.PREDICTIONS_JSONL}")
    print(f"Saved report:            {model_config.LATEST_REPORT_FILE}")

    if observations:
        print("First observation:")
        print(observations[0])


if __name__ == "__main__":
    main()
