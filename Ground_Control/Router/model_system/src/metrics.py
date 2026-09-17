from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ClassificationMetrics:
    accuracy: float
    precision: float
    recall: float
    f1_score: float
    true_negative: int
    false_positive: int
    false_negative: int
    true_positive: int


def compute_confusion_counts(
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


def compute_classification_metrics(
        targets: list[int],
        predictions: list[int],
) -> ClassificationMetrics:
    total = len(targets)
    if total == 0:
        return ClassificationMetrics(
            accuracy=0.0,
            precision=0.0,
            recall=0.0,
            f1_score=0.0,
            true_negative=0,
            false_positive=0,
            false_negative=0,
            true_positive=0,
        )

    tn, fp, fn, tp = compute_confusion_counts(targets, predictions)

    accuracy = (tn + tp) / total if total > 0 else 0.0
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1_score = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )

    return ClassificationMetrics(
        accuracy=accuracy,
        precision=precision,
        recall=recall,
        f1_score=f1_score,
        true_negative=tn,
        false_positive=fp,
        false_negative=fn,
        true_positive=tp,
    )


def metrics_to_dict(metrics: ClassificationMetrics) -> dict[str, float | int]:
    return {
        "accuracy": metrics.accuracy,
        "precision": metrics.precision,
        "recall": metrics.recall,
        "f1_score": metrics.f1_score,
        "true_negative": metrics.true_negative,
        "false_positive": metrics.false_positive,
        "false_negative": metrics.false_negative,
        "true_positive": metrics.true_positive,
    }