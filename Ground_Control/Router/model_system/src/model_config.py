from __future__ import annotations

from pathlib import Path


# ============================================================
# BASE PATHS
# ============================================================

SRC_DIR = Path(__file__).resolve().parent
MODEL_SYSTEM_DIR = SRC_DIR.parent

DATA_DIR = MODEL_SYSTEM_DIR / "data"
MODELS_DIR = MODEL_SYSTEM_DIR / "models"
MODELS_SAVED_DIR = MODELS_DIR / "saved"
OUTPUTS_DIR = MODEL_SYSTEM_DIR / "outputs"
REPORTS_DIR = OUTPUTS_DIR / "reports"
PREDICTIONS_DIR = OUTPUTS_DIR / "predictions"

# Optional legacy/raw training logs if you still want them nearby
TRAINING_LOGS_DIR = MODEL_SYSTEM_DIR / "training_logs"

# Ensure required directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
MODELS_DIR.mkdir(parents=True, exist_ok=True)
MODELS_SAVED_DIR.mkdir(parents=True, exist_ok=True)
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
PREDICTIONS_DIR.mkdir(parents=True, exist_ok=True)
TRAINING_LOGS_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# PREPARED DATA FILES
# ============================================================

PREPARED_EVENTS_CSV = DATA_DIR / "prepared_events.csv"
PREPARED_EVENTS_JSONL = DATA_DIR / "prepared_events.jsonl"

PREPARED_WINDOWS_CSV = DATA_DIR / "prepared_windows.csv"
PREPARED_WINDOWS_JSONL = DATA_DIR / "prepared_windows.jsonl"

# Primary dataset for first prototype
ACTIVE_DATASET_CSV = PREPARED_WINDOWS_CSV
ACTIVE_DATASET_JSONL = PREPARED_WINDOWS_JSONL


# ============================================================
# LABEL / TARGET SETTINGS
# ============================================================

# For prepared_windows.csv
WINDOW_LABEL_COLUMN = "window_label"

# For prepared_events.csv
EVENT_LABEL_COLUMN = "label"

# First prototype will train on windows
ACTIVE_LABEL_COLUMN = WINDOW_LABEL_COLUMN

NORMAL_LABEL = "normal"
ABNORMAL_LABEL = "abnormal"

LABEL_TO_INDEX = {
    NORMAL_LABEL: 0,
    ABNORMAL_LABEL: 1,
}

INDEX_TO_LABEL = {
    0: NORMAL_LABEL,
    1: ABNORMAL_LABEL,
}


# ============================================================
# FEATURE SETTINGS
# ============================================================

# Start with numeric window-level features only.
# Keep this list aligned with your parser output.
WINDOW_FEATURE_COLUMNS = [
    "window_span_seconds",
    "window_size",
    "connection_lost_count",
    "connection_established_count",
    "connection_check_failed_count",
    "arduino_response_count",
    "led_command_count",
    "generator_action_count",
    "generator_command_result_count",
    "error_count",
    "abnormal_count",
    "command_failed_count",
    "max_reconnect_duration_seconds",
    "avg_reconnect_duration_seconds",
    "max_command_duration_seconds",
    "avg_command_duration_seconds",
    "avg_delta_seconds",
]

# Optional event-level feature list for later experiments
EVENT_FEATURE_COLUMNS = [
    "elapsed_seconds",
    "delta_seconds",
    "abnormal",
    "state_changed_to_connected",
    "state_changed_to_disconnected",
    "is_connection_lost",
    "is_connection_established",
    "is_connection_check_failed",
    "is_arduino_response",
    "is_led_command_sent",
    "is_generator_action",
    "is_generator_command_result",
    "is_error",
    "disconnect_count_so_far",
    "reconnect_count_so_far",
    "reconnect_duration_seconds",
    "has_response_ack_connected",
    "has_response_ack_disconnected",
    "command_success",
    "command_failed",
    "command_returncode",
    "command_duration_seconds",
    "downtime_seconds",
    "network_target",
    "arduino_target",
]

ACTIVE_FEATURE_COLUMNS = WINDOW_FEATURE_COLUMNS


# ============================================================
# DATA SPLIT / TRAINING SETTINGS
# ============================================================

TEST_SIZE = 0.20
VALIDATION_SIZE = 0.20
RANDOM_SEED = 42
SHUFFLE_DATA = True

BATCH_SIZE = 8
LEARNING_RATE = 0.001
WEIGHT_DECAY = 0.0
EPOCHS = 40

# Small prototype MLP
INPUT_HIDDEN_DIM_1 = 32
INPUT_HIDDEN_DIM_2 = 16
DROPOUT = 0.10

USE_CLASS_WEIGHTS = False


# ============================================================
# MODEL FILE SETTINGS
# ============================================================

MODEL_NAME = "router_observer_v1"

MODEL_FILE = MODELS_SAVED_DIR / f"{MODEL_NAME}.pt"
SCALER_FILE = MODELS_SAVED_DIR / f"{MODEL_NAME}_scaler.pkl"
METADATA_FILE = MODELS_SAVED_DIR / f"{MODEL_NAME}_metadata.json"


# ============================================================
# PREDICTION / OBSERVER SETTINGS
# ============================================================

DEFAULT_DECISION_THRESHOLD = 0.50

# Severity thresholds for reporting
WARNING_PROBABILITY_THRESHOLD = 0.60
CRITICAL_PROBABILITY_THRESHOLD = 0.85

# Domain-specific observer thresholds
SLOW_RECONNECT_SECONDS = 15.0
HIGH_COMMAND_FAILURE_COUNT = 2
HIGH_CONNECTION_LOST_COUNT = 2


# ============================================================
# REPORT OUTPUT SETTINGS
# ============================================================

PREDICTIONS_CSV = PREDICTIONS_DIR / f"{MODEL_NAME}_predictions.csv"
PREDICTIONS_JSONL = PREDICTIONS_DIR / f"{MODEL_NAME}_predictions.jsonl"
LATEST_REPORT_FILE = REPORTS_DIR / f"{MODEL_NAME}_latest_report.txt"


# ============================================================
# RUNTIME MODES
# ============================================================

MODE_TRAIN = "train"
MODE_EVALUATE = "evaluate"
MODE_PREDICT = "predict"
MODE_OBSERVE = "observe"

DEFAULT_MODE = MODE_TRAIN


# ============================================================
# SANITY CHECK HELPERS
# ============================================================

def get_active_feature_columns() -> list[str]:
    return list(ACTIVE_FEATURE_COLUMNS)


def get_active_dataset_csv() -> Path:
    return ACTIVE_DATASET_CSV


def get_active_label_column() -> str:
    return ACTIVE_LABEL_COLUMN


