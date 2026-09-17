from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from . import model_config
from . import feature_schema


class DataLoader:
    """
    Loads prepared training data from CSV files and returns
    normalized feature rows plus labels and metadata.
    """

    def __init__(self, dataset_path: Path | None = None) -> None:
        self.dataset_path = dataset_path or model_config.get_active_dataset_csv()
        self.label_column = model_config.get_active_label_column()
        self.feature_columns = model_config.get_active_feature_columns()

    def load_dataframe(self) -> pd.DataFrame:
        if not self.dataset_path.exists():
            raise FileNotFoundError(f"Dataset file not found: {self.dataset_path}")

        dataframe = pd.read_csv(self.dataset_path)

        if dataframe.empty:
            raise ValueError(f"Dataset is empty: {self.dataset_path}")

        is_valid, missing = feature_schema.validate_feature_columns(list(dataframe.columns))
        if not is_valid:
            raise ValueError(
                f"Dataset is missing required feature columns: {missing}"
            )

        if self.label_column not in dataframe.columns:
            raise ValueError(
                f"Dataset is missing required label column: {self.label_column}"
            )

        return dataframe

    def load_records(self) -> list[dict[str, Any]]:
        dataframe = self.load_dataframe()
        records = dataframe.to_dict(orient="records")
        normalized_records: list[dict[str, Any]] = []

        for record in records:
            normalized_record = self._normalize_record(record)
            normalized_records.append(normalized_record)

        return normalized_records

    def load_features_and_labels(self) -> tuple[list[list[float]], list[int], list[dict[str, Any]]]:
        records = self.load_records()

        features: list[list[float]] = []
        labels: list[int] = []
        metadata: list[dict[str, Any]] = []

        for record in records:
            feature_vector = self._build_feature_vector(record)
            label_index = feature_schema.get_label_index(str(record[self.label_column]))
            record_metadata = self._extract_metadata(record)

            features.append(feature_vector)
            labels.append(label_index)
            metadata.append(record_metadata)

        return features, labels, metadata

    def get_feature_column_count(self) -> int:
        return len(self.feature_columns)

    def _normalize_record(self, record: dict[str, Any]) -> dict[str, Any]:
        normalized_features = feature_schema.normalize_feature_row(record)

        normalized_record = dict(record)
        normalized_record.update(normalized_features)

        if self.label_column in normalized_record:
            normalized_record[self.label_column] = str(normalized_record[self.label_column]).strip().lower()

        return normalized_record

    def _build_feature_vector(self, record: dict[str, Any]) -> list[float]:
        vector: list[float] = []

        for column_name in self.feature_columns:
            value = record.get(column_name, 0.0)
            vector.append(float(value))

        return vector

    def _extract_metadata(self, record: dict[str, Any]) -> dict[str, Any]:
        metadata_keys = [
            "source_file",
            "session_id",
            "event_index",
            "start_event_index",
            "end_event_index",
            "event",
            "last_event",
            "last_state",
            "session_label",
        ]

        metadata: dict[str, Any] = {}

        for key in metadata_keys:
            if key in record:
                metadata[key] = record[key]

        return metadata


def load_training_data(
        dataset_path: Path | None = None,
) -> tuple[list[list[float]], list[int], list[dict[str, Any]]]:
    loader = DataLoader(dataset_path=dataset_path)
    return loader.load_features_and_labels()


def main() -> None:
    loader = DataLoader()
    features, labels, metadata = loader.load_features_and_labels()

    print(f"Loaded dataset: {loader.dataset_path}")
    print(f"Rows: {len(features)}")
    print(f"Feature columns: {loader.get_feature_column_count()}")

    if features:
        print("First feature vector:")
        print(features[0])

    if labels:
        print("First label index:")
        print(labels[0])

    if metadata:
        print("First metadata row:")
        print(metadata[0])


if __name__ == "__main__":
    main()
