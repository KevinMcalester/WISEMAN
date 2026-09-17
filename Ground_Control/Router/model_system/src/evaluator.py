from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import torch
from torch.utils.data import DataLoader as TorchDataLoader

from . import model_config
from .dataset_builder import DatasetBuilder
from .metrics import compute_classification_metrics, metrics_to_dict
from .model import build_model

class Evaluator:
    """
    Loads the trained model and evaluates it on the test dataset.
    """

    def __init__(self) -> None:
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.dataset_bundle = DatasetBuilder().build()
        self.metadata = self._load_metadata()
        self.model = self._load_model()

        self.test_loader = TorchDataLoader(
            self.dataset_bundle.test_dataset,
            batch_size=model_config.BATCH_SIZE,
            shuffle=False,
        )

    def evaluate(self) -> dict[str, Any]:
        self.model.eval()

        predictions: list[int] = []
        targets: list[int] = []

        with torch.no_grad():
            for batch_x, batch_y in self.test_loader:
                batch_x = batch_x.to(self.device)
                batch_y = batch_y.to(self.device)

                logits = self.model(batch_x)
                batch_predictions = torch.argmax(logits, dim=1)

                predictions.extend(batch_predictions.cpu().tolist())
                targets.extend(batch_y.cpu().tolist())

        metrics = compute_classification_metrics(targets, predictions)

        result = {
            "model_name": model_config.MODEL_NAME,
            "test_rows": len(self.dataset_bundle.test_dataset),
            "metrics": metrics_to_dict(metrics),
        }

        return result

    def save_evaluation(self, evaluation: dict[str, Any], output_path: Path | None = None) -> Path:
        target = output_path or (model_config.REPORTS_DIR / f"{model_config.MODEL_NAME}_evaluation.json")

        with open(target, "w", encoding="utf-8") as file:
            json.dump(evaluation, file, indent=2)

        return target

    def _load_metadata(self) -> dict[str, Any]:
        if not model_config.METADATA_FILE.exists():
            raise FileNotFoundError(f"Metadata file not found: {model_config.METADATA_FILE}")

        with open(model_config.METADATA_FILE, "r", encoding="utf-8") as file:
            return json.load(file)

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


def main() -> None:
    evaluator = Evaluator()
    evaluation = evaluator.evaluate()
    output_path = evaluator.save_evaluation(evaluation)

    print("Evaluation complete.")
    print(json.dumps(evaluation, indent=2))
    print(f"Saved evaluation: {output_path}")


if __name__ == "__main__":
    main()