from __future__ import annotations

import json
import pickle
import random
from dataclasses import dataclass

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader as TorchDataLoader

from ground_control.Router.model_system.src import model_config
from ground_control.Router.model_system.src.dataset_builder import DatasetBuilder, DatasetBundle
from ground_control.Router.model_system.src.model import build_model, count_parameters, estimate_model_size_kb


@dataclass
class TrainingHistory:
    train_losses: list[float]
    val_losses: list[float]
    train_accuracies: list[float]
    val_accuracies: list[float]


class Trainer:
    """
    Trains the lightweight router observer model on prepared window data.
    """

    def __init__(self) -> None:
        self._set_random_seed(model_config.RANDOM_SEED)
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        self.dataset_builder = DatasetBuilder()
        self.dataset_bundle: DatasetBundle = self.dataset_builder.build()

        self.model = build_model(input_dim=self.dataset_bundle.input_dim).to(self.device)
        self.criterion = self._build_loss_function()
        self.optimizer = torch.optim.Adam(
            self.model.parameters(),
            lr=model_config.LEARNING_RATE,
            weight_decay=model_config.WEIGHT_DECAY,
        )

        self.train_loader = TorchDataLoader(
            self.dataset_bundle.train_dataset,
            batch_size=model_config.BATCH_SIZE,
            shuffle=True,
        )

        self.val_loader = TorchDataLoader(
            self.dataset_bundle.val_dataset,
            batch_size=model_config.BATCH_SIZE,
            shuffle=False,
        )

        self.test_loader = TorchDataLoader(
            self.dataset_bundle.test_dataset,
            batch_size=model_config.BATCH_SIZE,
            shuffle=False,
        )

    def train(self) -> TrainingHistory:
        history = TrainingHistory(
            train_losses=[],
            val_losses=[],
            train_accuracies=[],
            val_accuracies=[],
        )

        best_val_loss = float("inf")
        best_state_dict = None

        print("Starting training...")
        print(f"Device: {self.device}")
        print(f"Trainable parameters: {count_parameters(self.model)}")
        print(f"Estimated model size: {estimate_model_size_kb(self.model):.2f} KB")
        print(f"Train rows: {len(self.dataset_bundle.train_dataset)}")
        print(f"Validation rows: {len(self.dataset_bundle.val_dataset)}")
        print(f"Test rows: {len(self.dataset_bundle.test_dataset)}")

        for epoch in range(1, model_config.EPOCHS + 1):
            train_loss, train_accuracy = self._run_epoch(train_mode=True)
            val_loss, val_accuracy = self._run_epoch(train_mode=False)

            history.train_losses.append(train_loss)
            history.val_losses.append(val_loss)
            history.train_accuracies.append(train_accuracy)
            history.val_accuracies.append(val_accuracy)

            print(
                f"Epoch {epoch:03d}/{model_config.EPOCHS} | "
                f"train_loss={train_loss:.4f} train_acc={train_accuracy:.4f} | "
                f"val_loss={val_loss:.4f} val_acc={val_accuracy:.4f}"
            )

            if val_loss < best_val_loss:
                best_val_loss = val_loss
                best_state_dict = {
                    key: value.detach().cpu().clone()
                    for key, value in self.model.state_dict().items()
                }

        if best_state_dict is not None:
            self.model.load_state_dict(best_state_dict)

        self._save_artifacts(history)
        self._print_test_metrics()

        return history

    def _run_epoch(self, train_mode: bool) -> tuple[float, float]:
        loader = self.train_loader if train_mode else self.val_loader

        if train_mode:
            self.model.train()
        else:
            self.model.eval()

        total_loss = 0.0
        total_correct = 0
        total_examples = 0

        for batch_x, batch_y in loader:
            batch_x = batch_x.to(self.device)
            batch_y = batch_y.to(self.device)

            if train_mode:
                self.optimizer.zero_grad()

            with torch.set_grad_enabled(train_mode):
                logits = self.model(batch_x)
                loss = self.criterion(logits, batch_y)

                if train_mode:
                    loss.backward()
                    self.optimizer.step()

            predictions = torch.argmax(logits, dim=1)
            total_correct += (predictions == batch_y).sum().item()
            total_examples += batch_y.size(0)
            total_loss += loss.item() * batch_y.size(0)

        if total_examples == 0:
            return 0.0, 0.0

        average_loss = total_loss / total_examples
        accuracy = total_correct / total_examples
        return average_loss, accuracy

    def _build_loss_function(self) -> nn.Module:
        if not model_config.USE_CLASS_WEIGHTS:
            return nn.CrossEntropyLoss()

        class_counts = torch.bincount(self.dataset_bundle.y_train)
        if len(class_counts) < 2:
            return nn.CrossEntropyLoss()

        class_weights = class_counts.sum().float() / class_counts.float().clamp_min(1.0)
        class_weights = class_weights / class_weights.sum()
        class_weights = class_weights.to(self.device)

        return nn.CrossEntropyLoss(weight=class_weights)

    def _print_test_metrics(self) -> None:
        self.model.eval()

        total_correct = 0
        total_examples = 0

        all_predictions: list[int] = []
        all_targets: list[int] = []

        with torch.no_grad():
            for batch_x, batch_y in self.test_loader:
                batch_x = batch_x.to(self.device)
                batch_y = batch_y.to(self.device)

                logits = self.model(batch_x)
                predictions = torch.argmax(logits, dim=1)

                total_correct += (predictions == batch_y).sum().item()
                total_examples += batch_y.size(0)

                all_predictions.extend(predictions.cpu().tolist())
                all_targets.extend(batch_y.cpu().tolist())

        accuracy = (total_correct / total_examples) if total_examples > 0 else 0.0

        tn, fp, fn, tp = self._compute_confusion_counts(all_targets, all_predictions)

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1_score = (
            2 * precision * recall / (precision + recall)
            if (precision + recall) > 0
            else 0.0
        )

        print("\nFinal test metrics")
        print(f"test_accuracy={accuracy:.4f}")
        print(f"precision={precision:.4f}")
        print(f"recall={recall:.4f}")
        print(f"f1_score={f1_score:.4f}")
        print(f"confusion_matrix: tn={tn} fp={fp} fn={fn} tp={tp}")

    @staticmethod
    def _compute_confusion_counts(
            targets: list[int],
            predictions: list[int],
    ) -> tuple[int, int, int, int]:
        tn = fp = fn = tp = 0

        for target, prediction in zip(targets, predictions):
            if target == 0 and prediction == 0:
                tn += 1
            elif target == 0 and prediction == 1:
                fp += 1
            elif target == 1 and prediction == 0:
                fn += 1
            elif target == 1 and prediction == 1:
                tp += 1

        return tn, fp, fn, tp

    def _save_artifacts(self, history: TrainingHistory) -> None:
        torch.save(self.model.state_dict(), model_config.MODEL_FILE)

        with open(model_config.SCALER_FILE, "wb") as file:
            pickle.dump(self.dataset_bundle.scaler, file)

        metadata = {
            "model_name": model_config.MODEL_NAME,
            "input_dim": self.dataset_bundle.input_dim,
            "feature_columns": model_config.get_active_feature_columns(),
            "label_column": model_config.get_active_label_column(),
            "label_to_index": model_config.LABEL_TO_INDEX,
            "index_to_label": model_config.INDEX_TO_LABEL,
            "epochs": model_config.EPOCHS,
            "batch_size": model_config.BATCH_SIZE,
            "learning_rate": model_config.LEARNING_RATE,
            "weight_decay": model_config.WEIGHT_DECAY,
            "dropout": model_config.DROPOUT,
            "hidden_dim_1": model_config.INPUT_HIDDEN_DIM_1,
            "hidden_dim_2": model_config.INPUT_HIDDEN_DIM_2,
            "train_rows": len(self.dataset_bundle.train_dataset),
            "val_rows": len(self.dataset_bundle.val_dataset),
            "test_rows": len(self.dataset_bundle.test_dataset),
            "history": {
                "train_losses": history.train_losses,
                "val_losses": history.val_losses,
                "train_accuracies": history.train_accuracies,
                "val_accuracies": history.val_accuracies,
            },
        }

        with open(model_config.METADATA_FILE, "w", encoding="utf-8") as file:
            json.dump(metadata, file, indent=2)

        print("\nSaved artifacts:")
        print(f"Model:    {model_config.MODEL_FILE}")
        print(f"Scaler:   {model_config.SCALER_FILE}")
        print(f"Metadata: {model_config.METADATA_FILE}")

    @staticmethod
    def _set_random_seed(seed: int) -> None:
        random.seed(seed)
        np.random.seed(seed)
        torch.manual_seed(seed)

        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)


def main() -> None:
    trainer = Trainer()
    trainer.train()


if __name__ == "__main__":
    main()
