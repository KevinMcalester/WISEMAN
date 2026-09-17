from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import model_config


@dataclass(frozen=True)
class FeatureDefinition:
    name: str
    dtype: str
    default: float | int
    required: bool = True
    description: str = ""


WINDOW_FEATURE_DEFINITIONS: list[FeatureDefinition] = [
    FeatureDefinition(
        name="window_span_seconds",
        dtype="float",
        default=0.0,
        description="Elapsed time covered by the window.",
    ),
    FeatureDefinition(
        name="window_size",
        dtype="int",
        default=0,
        description="Number of events inside the window.",
    ),
    FeatureDefinition(
        name="connection_lost_count",
        dtype="int",
        default=0,
        description="How many connection lost events occurred in the window.",
    ),
    FeatureDefinition(
        name="connection_established_count",
        dtype="int",
        default=0,
        description="How many reconnection events occurred in the window.",
    ),
    FeatureDefinition(
        name="connection_check_failed_count",
        dtype="int",
        default=0,
        description="How many connection check failures occurred in the window.",
    ),
    FeatureDefinition(
        name="arduino_response_count",
        dtype="int",
        default=0,
        description="How many Arduino responses were seen in the window.",
    ),
    FeatureDefinition(
        name="led_command_count",
        dtype="int",
        default=0,
        description="How many LED command events occurred in the window.",
    ),
    FeatureDefinition(
        name="generator_action_count",
        dtype="int",
        default=0,
        description="How many generator actions occurred in the window.",
    ),
    FeatureDefinition(
        name="generator_command_result_count",
        dtype="int",
        default=0,
        description="How many generator command result events occurred in the window.",
    ),
    FeatureDefinition(
        name="error_count",
        dtype="int",
        default=0,
        description="How many generic error events occurred in the window.",
    ),
    FeatureDefinition(
        name="abnormal_count",
        dtype="int",
        default=0,
        description="How many abnormal events were already marked inside the window.",
    ),
    FeatureDefinition(
        name="command_failed_count",
        dtype="int",
        default=0,
        description="How many command failures occurred in the window.",
    ),
    FeatureDefinition(
        name="max_reconnect_duration_seconds",
        dtype="float",
        default=0.0,
        description="Maximum reconnect duration observed in the window.",
    ),
    FeatureDefinition(
        name="avg_reconnect_duration_seconds",
        dtype="float",
        default=0.0,
        description="Average reconnect duration observed in the window.",
    ),
    FeatureDefinition(
        name="max_command_duration_seconds",
        dtype="float",
        default=0.0,
        description="Maximum command execution duration in the window.",
    ),
    FeatureDefinition(
        name="avg_command_duration_seconds",
        dtype="float",
        default=0.0,
        description="Average command execution duration in the window.",
    ),
    FeatureDefinition(
        name="avg_delta_seconds",
        dtype="float",
        default=0.0,
        description="Average time gap between events in the window.",
    ),
]


EVENT_FEATURE_DEFINITIONS: list[FeatureDefinition] = [
    FeatureDefinition("elapsed_seconds", "float", 0.0),
    FeatureDefinition("delta_seconds", "float", 0.0),
    FeatureDefinition("abnormal", "int", 0),
    FeatureDefinition("state_changed_to_connected", "int", 0),
    FeatureDefinition("state_changed_to_disconnected", "int", 0),
    FeatureDefinition("is_connection_lost", "int", 0),
    FeatureDefinition("is_connection_established", "int", 0),
    FeatureDefinition("is_connection_check_failed", "int", 0),
    FeatureDefinition("is_arduino_response", "int", 0),
    FeatureDefinition("is_led_command_sent", "int", 0),
    FeatureDefinition("is_generator_action", "int", 0),
    FeatureDefinition("is_generator_command_result", "int", 0),
    FeatureDefinition("is_error", "int", 0),
    FeatureDefinition("disconnect_count_so_far", "int", 0),
    FeatureDefinition("reconnect_count_so_far", "int", 0),
    FeatureDefinition("reconnect_duration_seconds", "float", 0.0),
    FeatureDefinition("has_response_ack_connected", "int", 0),
    FeatureDefinition("has_response_ack_disconnected", "int", 0),
    FeatureDefinition("command_success", "int", 0),
    FeatureDefinition("command_failed", "int", 0),
    FeatureDefinition("command_returncode", "int", 0),
    FeatureDefinition("command_duration_seconds", "float", 0.0),
    FeatureDefinition("downtime_seconds", "float", 0.0),
    FeatureDefinition("network_target", "int", 0),
    FeatureDefinition("arduino_target", "int", 0),
]


def get_window_feature_names() -> list[str]:
    return [feature.name for feature in WINDOW_FEATURE_DEFINITIONS]


def get_event_feature_names() -> list[str]:
    return [feature.name for feature in EVENT_FEATURE_DEFINITIONS]


def get_active_feature_definitions() -> list[FeatureDefinition]:
    active_names = set(model_config.get_active_feature_columns())

    if active_names == set(get_window_feature_names()):
        return WINDOW_FEATURE_DEFINITIONS

    if active_names == set(get_event_feature_names()):
        return EVENT_FEATURE_DEFINITIONS

    definitions: list[FeatureDefinition] = []
    all_definitions = WINDOW_FEATURE_DEFINITIONS + EVENT_FEATURE_DEFINITIONS

    for name in model_config.get_active_feature_columns():
        for definition in all_definitions:
            if definition.name == name:
                definitions.append(definition)
                break

    return definitions


def build_default_feature_row() -> dict[str, float | int]:
    row: dict[str, float | int] = {}

    for definition in get_active_feature_definitions():
        row[definition.name] = definition.default

    return row


def coerce_feature_value(value: Any, dtype: str, default: float | int) -> float | int:
    if value in (None, "", "None"):
        return default

    try:
        if dtype == "int":
            return int(float(value))
        if dtype == "float":
            return float(value)
    except (TypeError, ValueError):
        return default

    return default


def normalize_feature_row(row: dict[str, Any]) -> dict[str, float | int]:
    normalized = build_default_feature_row()

    for definition in get_active_feature_definitions():
        raw_value = row.get(definition.name, definition.default)
        normalized[definition.name] = coerce_feature_value(
            value=raw_value,
            dtype=definition.dtype,
            default=definition.default,
        )

    return normalized


def validate_feature_columns(columns: list[str]) -> tuple[bool, list[str]]:
    expected = set(model_config.get_active_feature_columns())
    provided = set(columns)

    missing = sorted(expected - provided)
    is_valid = len(missing) == 0
    return is_valid, missing


def get_label_index(label: str) -> int:
    return model_config.LABEL_TO_INDEX[label]


def get_label_name(index: int) -> str:
    return model_config.INDEX_TO_LABEL[index]