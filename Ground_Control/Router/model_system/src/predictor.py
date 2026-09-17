from __future__ import annotations

import json
import pickle
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch

from . import model_config
from . import feature_schema
from .model import build_model
class Predictor:
    """
    Loads a trained model and scaler, then predicts
    normal vs abnormal from prepared rows.
    """

    def __init__(self) -> None:
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.metadata = self._load_metadata()
        self.scaler = self._load_scaler()
        self.model = self._load_model()

        self.feature_columns: list[str] = list(self.metadata["feature_columns"])
        self.label_to_index: dict[str, int] = dict(self.metadata["label_to_index"])
        self.index_to_label: dict[str, str] = {
            int(key): value for key, value in self.metadata["index_to_label"].items()
        }

    def predict_row(self, row: dict[str, Any]) -> dict[str, Any]:
        normalized_row = self._normalize_input_row(row)
        feature_vector = self._build_feature_vector(normalized_row)
        probabilities = self._predict_probabilities(feature_vector)

        abnormal_probability = float(probabilities[model_config.LABEL_TO_INDEX[model_config.ABNORMAL_LABEL]])
        normal_probability = float(probabilities[model_config.LABEL_TO_INDEX[model_config.NORMAL_LABEL]])

        predicted_index = int(np.argmax(probabilities))
        predicted_label = self.index_to_label[predicted_index]
        severity = self._determine_severity(abnormal_probability)

        return {
            "predicted_label": predicted_label,
            "predicted_index": predicted_index,
            "normal_probability": round(normal_probability, 6),
            "abnormal_probability": round(abnormal_probability, 6),
            "severity": severity,
        }

    def predict_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []

        for row in rows:
            prediction = self.predict_row(row)
            merged_result = dict(row)
            merged_result.update(prediction)
            results.append(merged_result)

        return results

    def predict_csv(self, csv_path: Path | None = None) -> list[dict[str, Any]]:
        target_path = csv_path or model_config.get_active_dataset_csv()

        if not target_path.exists():
            raise FileNotFoundError(f"Prediction CSV not found: {target_path}")

        dataframe = pd.read_csv(target_path)
        records = dataframe.to_dict(orient="records")
        return self.predict_rows(records)

    def save_predictions(
            self,
            predictions: list[dict[str, Any]],
            csv_path: Path | None = None,
            jsonl_path: Path | None = None,
    ) -> None:
        csv_target = csv_path or model_config.PREDICTIONS_CSV
        jsonl_target = jsonl_path or model_config.PREDICTIONS_JSONL

        if predictions:
            dataframe = pd.DataFrame(predictions)
            dataframe.to_csv(csv_target, index=False)

        with open(jsonl_target, "w", encoding="utf-8") as file:
            for row in predictions:
                file.write(json.dumps(row) + "\n")

    def _normalize_input_row(self, row: dict[str, Any]) -> dict[str, Any]:
        normalized_features = {}

        for feature_name in self.feature_columns:
            raw_value = row.get(feature_name, 0)
            definition = self._get_feature_definition(feature_name)

            if definition is None:
                normalized_features[feature_name] = 0.0
                continue

            normalized_features[feature_name] = feature_schema.coerce_feature_value(
                value=raw_value,
                dtype=definition.dtype,
                default=definition.default,
            )

        normalized_row = dict(row)
        normalized_row.update(normalized_features)
        return normalized_row

    def _build_feature_vector(self, row: dict[str, Any]) -> np.ndarray:
        vector = np.asarray(
            [[float(row.get(column_name, 0.0)) for column_name in self.feature_columns]],
            dtype=np.float32,
        )

        scaled_vector = self.scaler.transform(vector)
        return scaled_vector

    def _predict_probabilities(self, feature_vector: np.ndarray) -> np.ndarray:
        tensor = torch.tensor(feature_vector, dtype=torch.float32).to(self.device)

        self.model.eval()
        with torch.no_grad():
            logits = self.model(tensor)
            probabilities = torch.softmax(logits, dim=1)

        return probabilities.cpu().numpy()[0]

    def _determine_severity(self, abnormal_probability: float) -> str:
        if abnormal_probability >= model_config.CRITICAL_PROBABILITY_THRESHOLD:
            return "critical"
        if abnormal_probability >= model_config.WARNING_PROBABILITY_THRESHOLD:
            return "warning"
        return "normal"

    def _load_metadata(self) -> dict[str, Any]:
        if not model_config.METADATA_FILE.exists():
            raise FileNotFoundError(f"Metadata file not found: {model_config.METADATA_FILE}")

        with open(model_config.METADATA_FILE, "r", encoding="utf-8") as file:
            return json.load(file)

    def _load_scaler(self) -> Any:
        if not model_config.SCALER_FILE.exists():
            raise FileNotFoundError(f"Scaler file not found: {model_config.SCALER_FILE}")

        with open(model_config.SCALER_FILE, "rb") as file:
            return pickle.load(file)

    def _load_model(self) -> torch.nn.Module:
        if not model_config.MODEL_FILE.exists():
            raise FileNotFoundError(f"Model file not found: {model_config.MODEL_FILE}")

        input_dim = int(self.metadata["input_dim"])
        model = build_model(input_dim=input_dim)
        state_dict = torch.load(model_config.MODEL_FILE, map_location=self.device)
        model.load_state_dict(state_dict)
        model.to(self.device)
        model.eval()
        return model

    @staticmethod
    def _get_feature_definition(feature_name: str):
        for definition in feature_schema.get_active_feature_definitions():
            if definition.name == feature_name:
                return definition
        return None


def main() -> None:
    predictor = Predictor()
    predictions = predictor.predict_csv()

    predictor.save_predictions(predictions)

    print(f"Predictions generated: {len(predictions)}")
    print(f"Saved CSV:   {model_config.PREDICTIONS_CSV}")
    print(f"Saved JSONL: {model_config.PREDICTIONS_JSONL}")

    if predictions:
        print("First prediction:")
        print(predictions[0])


if __name__ == "__main__":
    main()