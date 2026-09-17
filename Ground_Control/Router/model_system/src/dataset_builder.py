from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import torch
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from torch.utils.data import TensorDataset

from . import model_config
from  .data_loader import DataLoader


@dataclass
class DatasetBundle:
    x_train: torch.Tensor
    y_train: torch.Tensor
    x_val: torch.Tensor
    y_val: torch.Tensor
    x_test: torch.Tensor
    y_test: torch.Tensor
    train_dataset: TensorDataset
    val_dataset: TensorDataset
    test_dataset: TensorDataset
    scaler: StandardScaler
    train_metadata: list[dict[str, Any]]
    val_metadata: list[dict[str, Any]]
    test_metadata: list[dict[str, Any]]
    input_dim: int


class DatasetBuilder:
    """
    Builds train/validation/test datasets from prepared CSV data.
    Handles:
    - loading
    - splitting
    - scaling
    - tensor conversion
    """

    def __init__(self) -> None:
        self.loader = DataLoader()

    def build(self) -> DatasetBundle:
        features, labels, metadata = self.loader.load_features_and_labels()

        if len(features) < 4:
            raise ValueError(
                "Not enough rows to build train/validation/test datasets. "
                "Collect or parse more data first."
            )

        x = np.asarray(features, dtype=np.float32)
        y = np.asarray(labels, dtype=np.int64)
        meta = np.asarray(metadata, dtype=object)

        if len(np.unique(y)) < 2:
            raise ValueError(
                "Dataset needs at least two label classes to train a classifier."
            )

        x_train, x_test, y_train, y_test, meta_train, meta_test = train_test_split(
            x,
            y,
            meta,
            test_size=model_config.TEST_SIZE,
            random_state=model_config.RANDOM_SEED,
            shuffle=model_config.SHUFFLE_DATA,
            stratify=y if self._can_stratify(y) else None,
        )

        if len(x_train) < 2:
            raise ValueError("Training split is too small after test split.")

        val_ratio_relative_to_train = self._get_validation_ratio_relative_to_train()

        x_train, x_val, y_train, y_val, meta_train, meta_val = train_test_split(
            x_train,
            y_train,
            meta_train,
            test_size=val_ratio_relative_to_train,
            random_state=model_config.RANDOM_SEED,
            shuffle=model_config.SHUFFLE_DATA,
            stratify=y_train if self._can_stratify(y_train) else None,
        )

        scaler = StandardScaler()
        x_train_scaled = scaler.fit_transform(x_train)
        x_val_scaled = scaler.transform(x_val)
        x_test_scaled = scaler.transform(x_test)

        x_train_tensor = torch.tensor(x_train_scaled, dtype=torch.float32)
        y_train_tensor = torch.tensor(y_train, dtype=torch.long)

        x_val_tensor = torch.tensor(x_val_scaled, dtype=torch.float32)
        y_val_tensor = torch.tensor(y_val, dtype=torch.long)

        x_test_tensor = torch.tensor(x_test_scaled, dtype=torch.float32)
        y_test_tensor = torch.tensor(y_test, dtype=torch.long)

        train_dataset = TensorDataset(x_train_tensor, y_train_tensor)
        val_dataset = TensorDataset(x_val_tensor, y_val_tensor)
        test_dataset = TensorDataset(x_test_tensor, y_test_tensor)

        return DatasetBundle(
            x_train=x_train_tensor,
            y_train=y_train_tensor,
            x_val=x_val_tensor,
            y_val=y_val_tensor,
            x_test=x_test_tensor,
            y_test=y_test_tensor,
            train_dataset=train_dataset,
            val_dataset=val_dataset,
            test_dataset=test_dataset,
            scaler=scaler,
            train_metadata=self._metadata_array_to_list(meta_train),
            val_metadata=self._metadata_array_to_list(meta_val),
            test_metadata=self._metadata_array_to_list(meta_test),
            input_dim=x_train_tensor.shape[1],
        )

    @staticmethod
    def _metadata_array_to_list(meta: np.ndarray) -> list[dict[str, Any]]:
        return [dict(item) for item in meta.tolist()]

    @staticmethod
    def _can_stratify(labels: np.ndarray) -> bool:
        unique_values, counts = np.unique(labels, return_counts=True)
        if len(unique_values) < 2:
            return False
        return bool(np.all(counts >= 2))

    @staticmethod
    def _get_validation_ratio_relative_to_train() -> float:
        test_size = float(model_config.TEST_SIZE)
        validation_size = float(model_config.VALIDATION_SIZE)

        if test_size >= 1.0 or validation_size >= 1.0:
            raise ValueError("TEST_SIZE and VALIDATION_SIZE must be less than 1.0")

        if test_size <= 0.0 or validation_size <= 0.0:
            raise ValueError("TEST_SIZE and VALIDATION_SIZE must be greater than 0.0")

        remaining_after_test = 1.0 - test_size
        if remaining_after_test <= 0.0:
            raise ValueError("TEST_SIZE leaves no data for training/validation.")

        relative_validation_size = validation_size / remaining_after_test

        if relative_validation_size <= 0.0 or relative_validation_size >= 1.0:
            raise ValueError(
                "Relative validation split is invalid. "
                "Adjust TEST_SIZE and VALIDATION_SIZE."
            )

        return relative_validation_size


def main() -> None:
    builder = DatasetBuilder()
    bundle = builder.build()

    print("Dataset build successful.")
    print(f"Input dimension: {bundle.input_dim}")
    print(f"Train rows: {len(bundle.train_dataset)}")
    print(f"Validation rows: {len(bundle.val_dataset)}")
    print(f"Test rows: {len(bundle.test_dataset)}")

    print("Train tensor shapes:")
    print(f"x_train: {tuple(bundle.x_train.shape)}")
    print(f"y_train: {tuple(bundle.y_train.shape)}")

    print("Validation tensor shapes:")
    print(f"x_val: {tuple(bundle.x_val.shape)}")
    print(f"y_val: {tuple(bundle.y_val.shape)}")

    print("Test tensor shapes:")
    print(f"x_test: {tuple(bundle.x_test.shape)}")
    print(f"y_test: {tuple(bundle.y_test.shape)}")


if __name__ == "__main__":
    main()