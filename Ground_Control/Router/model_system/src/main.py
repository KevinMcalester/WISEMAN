from __future__ import annotations

import sys

from . import model_config
from ground_control.Router.model_system.src.later_imp.observer import Observer
from .predictor import Predictor
from .trainer import Trainer


def run_train() -> None:
    trainer = Trainer()
    trainer.train()


def run_predict() -> None:
    predictor = Predictor()
    predictions = predictor.predict_csv()
    predictor.save_predictions(predictions)

    print(f"Predictions generated: {len(predictions)}")
    print(f"Saved CSV:   {model_config.PREDICTIONS_CSV}")
    print(f"Saved JSONL: {model_config.PREDICTIONS_JSONL}")


def run_observe() -> None:
    observer = Observer()
    observations = observer.observe_csv()
    observer.save_observations(observations)
    observer.save_report(observations)

    print(f"Observed rows: {len(observations)}")
    print(f"Saved predictions CSV:   {model_config.PREDICTIONS_CSV}")
    print(f"Saved predictions JSONL: {model_config.PREDICTIONS_JSONL}")
    print(f"Saved report:            {model_config.LATEST_REPORT_FILE}")


def print_usage() -> None:
    print("Usage:")
    print("  python main.py train")
    print("  python main.py predict")
    print("  python main.py observe")


def main() -> None:
    if len(sys.argv) < 2:
        mode = model_config.DEFAULT_MODE
    else:
        mode = sys.argv[1].strip().lower()

    if mode == model_config.MODE_TRAIN:
        run_train()
    elif mode == model_config.MODE_PREDICT:
        run_predict()
    elif mode == model_config.MODE_OBSERVE:
        run_observe()
    else:
        print(f"Unknown mode: {mode}")
        print_usage()


if __name__ == "__main__":
    main()