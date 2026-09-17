from __future__ import annotations

from typing import Any

from . import model_config


class ReportBuilder:
    """
    Builds readable text reports from observer output.
    """

    def build_observer_report(self, observations: list[dict[str, Any]]) -> str:
        total_rows = len(observations)
        abnormal_rows = sum(
            1 for row in observations if row.get("predicted_label") == model_config.ABNORMAL_LABEL
        )
        warning_rows = sum(1 for row in observations if row.get("severity") == "warning")
        critical_rows = sum(1 for row in observations if row.get("severity") == "critical")
        rows_with_issues = sum(1 for row in observations if row.get("needs_attention"))

        lines: list[str] = []
        lines.append("Router Observer Report")
        lines.append("=" * 60)
        lines.append(f"Total rows observed: {total_rows}")
        lines.append(f"Predicted abnormal rows: {abnormal_rows}")
        lines.append(f"Warning rows: {warning_rows}")
        lines.append(f"Critical rows: {critical_rows}")
        lines.append(f"Rows with issues: {rows_with_issues}")
        lines.append("")

        highlighted = [
            row for row in observations
            if row.get("needs_attention") or row.get("severity") in ("warning", "critical")
        ]

        if not highlighted:
            lines.append("No major issues detected.")
            return "\n".join(lines)

        lines.append("Highlighted Rows")
        lines.append("-" * 60)

        for index, row in enumerate(highlighted[:20], start=1):
            lines.append(f"{index}. {self._identify_row(row)}")
            lines.append(f"   predicted_label: {row.get('predicted_label')}")
            lines.append(f"   abnormal_probability: {row.get('abnormal_probability')}")
            lines.append(f"   severity: {row.get('severity')}")

            issues = row.get("issues", [])
            if issues:
                lines.append(f"   issues: {', '.join(issues)}")

            lines.append("")

        return "\n".join(lines)

    def build_evaluation_report(self, evaluation: dict[str, Any]) -> str:
        metrics = evaluation.get("metrics", {})

        lines: list[str] = []
        lines.append("Router Model Evaluation Report")
        lines.append("=" * 60)
        lines.append(f"Model name: {evaluation.get('model_name')}")
        lines.append(f"Test rows: {evaluation.get('test_rows')}")
        lines.append("")
        lines.append(f"Accuracy: {metrics.get('accuracy', 0.0):.4f}")
        lines.append(f"Precision: {metrics.get('precision', 0.0):.4f}")
        lines.append(f"Recall: {metrics.get('recall', 0.0):.4f}")
        lines.append(f"F1 Score: {metrics.get('f1_score', 0.0):.4f}")
        lines.append("")
        lines.append(
            "Confusion Counts: "
            f"TN={metrics.get('true_negative', 0)} "
            f"FP={metrics.get('false_positive', 0)} "
            f"FN={metrics.get('false_negative', 0)} "
            f"TP={metrics.get('true_positive', 0)}"
        )

        return "\n".join(lines)

    @staticmethod
    def _identify_row(row: dict[str, Any]) -> str:
        session_id = row.get("session_id", "unknown_session")
        start_event_index = row.get("start_event_index")
        end_event_index = row.get("end_event_index")

        if start_event_index is not None and end_event_index is not None:
            return f"session={session_id} window={start_event_index}->{end_event_index}"

        event_index = row.get("event_index")
        if event_index is not None:
            return f"session={session_id} event={event_index}"

        return f"session={session_id}"