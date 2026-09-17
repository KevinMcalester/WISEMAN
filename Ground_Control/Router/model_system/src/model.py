from __future__ import annotations

import torch
import torch.nn as nn

from . import model_config


class RouterObserverModel(nn.Module):
    """
    Lightweight feedforward classifier for router behavior windows.

    Design goals:
    - small memory footprint
    - fast training on a laptop
    - easy deployment to a 16 GB RAM device
    - stable enough for small tabular datasets
    """

    def __init__(
            self,
            input_dim: int,
            hidden_dim_1: int | None = None,
            hidden_dim_2: int | None = None,
            dropout: float | None = None,
    ) -> None:
        super().__init__()

        hidden_dim_1 = hidden_dim_1 if hidden_dim_1 is not None else model_config.INPUT_HIDDEN_DIM_1
        hidden_dim_2 = hidden_dim_2 if hidden_dim_2 is not None else model_config.INPUT_HIDDEN_DIM_2
        dropout = dropout if dropout is not None else model_config.DROPOUT

        self.input_dim = input_dim
        self.hidden_dim_1 = hidden_dim_1
        self.hidden_dim_2 = hidden_dim_2
        self.dropout_rate = dropout
        self.output_dim = 2  # normal / abnormal

        self.network = nn.Sequential(
            nn.Linear(self.input_dim, self.hidden_dim_1),
            nn.ReLU(),
            nn.BatchNorm1d(self.hidden_dim_1),
            nn.Dropout(self.dropout_rate),

            nn.Linear(self.hidden_dim_1, self.hidden_dim_2),
            nn.ReLU(),
            nn.BatchNorm1d(self.hidden_dim_2),
            nn.Dropout(self.dropout_rate),

            nn.Linear(self.hidden_dim_2, self.output_dim)
        )

        self._initialize_weights()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.network(x)

    def predict_logits(self, x: torch.Tensor) -> torch.Tensor:
        self.eval()
        with torch.no_grad():
            return self.forward(x)

    def predict_probabilities(self, x: torch.Tensor) -> torch.Tensor:
        logits = self.predict_logits(x)
        return torch.softmax(logits, dim=1)

    def predict_classes(self, x: torch.Tensor) -> torch.Tensor:
        probabilities = self.predict_probabilities(x)
        return torch.argmax(probabilities, dim=1)

    def _initialize_weights(self) -> None:
        for module in self.modules():
            if isinstance(module, nn.Linear):
                nn.init.kaiming_uniform_(module.weight, nonlinearity="relu")
                if module.bias is not None:
                    nn.init.zeros_(module.bias)


def build_model(input_dim: int) -> RouterObserverModel:
    return RouterObserverModel(input_dim=input_dim)


def count_parameters(model: nn.Module) -> int:
    return sum(parameter.numel() for parameter in model.parameters() if parameter.requires_grad)


def estimate_model_size_bytes(model: nn.Module) -> int:
    total_bytes = 0
    for parameter in model.parameters():
        total_bytes += parameter.numel() * parameter.element_size()
    return total_bytes


def estimate_model_size_kb(model: nn.Module) -> float:
    return estimate_model_size_bytes(model) / 1024.0


def estimate_model_size_mb(model: nn.Module) -> float:
    return estimate_model_size_bytes(model) / (1024.0 * 1024.0)


def main() -> None:
    input_dim = len(model_config.get_active_feature_columns())
    model = build_model(input_dim=input_dim)

    print("RouterObserverModel created successfully.")
    print(f"Input dimension: {input_dim}")
    print(f"Trainable parameters: {count_parameters(model)}")
    print(f"Estimated size: {estimate_model_size_kb(model):.2f} KB")
    print(model)


if __name__ == "__main__":
    main()
