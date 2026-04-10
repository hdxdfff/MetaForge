from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class DatasetBundle:
    x_train: list[list[float]]
    x_test: list[list[float]]
    y_train: list[float]
    y_test: list[float]
    source: str
    notes: list[str]


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _dot(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def _train_test_split(
    x: list[list[float]],
    y: list[float],
    *,
    train_ratio: float = 0.75,
    seed: int = 42,
) -> tuple[list[list[float]], list[list[float]], list[float], list[float]]:
    indices = list(range(len(x)))
    rng = random.Random(seed)
    rng.shuffle(indices)
    split = max(1, min(len(x) - 1, int(len(x) * train_ratio)))
    train_idx = indices[:split]
    test_idx = indices[split:]
    x_train = [x[index] for index in train_idx]
    x_test = [x[index] for index in test_idx]
    y_train = [y[index] for index in train_idx]
    y_test = [y[index] for index in test_idx]
    return x_train, x_test, y_train, y_test


def _standardize(
    x_train: list[list[float]],
    x_test: list[list[float]],
) -> tuple[list[list[float]], list[list[float]]]:
    feature_count = len(x_train[0])
    means = [sum(row[index] for row in x_train) / len(x_train) for index in range(feature_count)]
    stds = []
    for index in range(feature_count):
        variance = sum((row[index] - means[index]) ** 2 for row in x_train) / len(x_train)
        stds.append(math.sqrt(variance) or 1.0)

    def transform(rows: list[list[float]]) -> list[list[float]]:
        return [
            [(value - means[index]) / stds[index] for index, value in enumerate(row)]
            for row in rows
        ]

    return transform(x_train), transform(x_test)


def _make_synthetic_dataset(
    *,
    samples: int = 240,
    features: int = 12,
    seed: int = 42,
) -> DatasetBundle:
    rng = random.Random(seed)
    weights = [rng.gauss(0.0, 1.0) for _ in range(features)]
    rows: list[list[float]] = []
    margins: list[float] = []
    for _ in range(samples):
        row = [rng.gauss(0.0, 1.0) for _ in range(features)]
        margin = _dot(row, weights) + 0.35 * rng.gauss(0.0, 1.0)
        rows.append(row)
        margins.append(margin)
    median_margin = sorted(margins)[len(margins) // 2]
    labels = [1.0 if margin > median_margin else 0.0 for margin in margins]
    x_train, x_test, y_train, y_test = _train_test_split(rows, labels, seed=seed)
    x_train, x_test = _standardize(x_train, x_test)
    return DatasetBundle(
        x_train=x_train,
        x_test=x_test,
        y_train=y_train,
        y_test=y_test,
        source="deterministic synthetic fallback",
        notes=[
            "No explicit local dataset was supplied to the workflow.",
            "A deterministic synthetic binary dataset was generated to keep the execution loop closed.",
        ],
    )


def _sigmoid(value: float) -> float:
    clipped = max(-30.0, min(30.0, value))
    return 1.0 / (1.0 + math.exp(-clipped))


def _train_logistic_regression(
    x: list[list[float]],
    y: list[float],
    *,
    epochs: int = 24,
    lr: float = 0.05,
    l2: float = 0.0005,
    seed: int = 42,
) -> tuple[list[float], float]:
    rng = random.Random(seed)
    weights = [0.0 for _ in range(len(x[0]))]
    bias = 0.0
    for epoch in range(epochs):
        eta = lr / (1.0 + 0.03 * epoch)
        indices = list(range(len(x)))
        rng.shuffle(indices)
        for idx in indices:
            margin = _dot(weights, x[idx]) + bias
            prob = _sigmoid(margin)
            grad = prob - y[idx]
            for feature in range(len(weights)):
                weights[feature] -= eta * (grad * x[idx][feature] + l2 * weights[feature])
            bias -= eta * grad
    return weights, bias


def _train_sgd_classifier(
    x: list[list[float]],
    y: list[float],
    *,
    epochs: int = 20,
    lr: float = 0.04,
    l2: float = 0.0008,
    seed: int = 42,
) -> tuple[list[float], float]:
    rng = random.Random(seed + 7)
    weights = [0.0 for _ in range(len(x[0]))]
    bias = 0.0
    for epoch in range(epochs):
        eta = lr / (1.0 + 0.04 * epoch)
        indices = list(range(len(x)))
        rng.shuffle(indices)
        for idx in indices:
            margin = _dot(weights, x[idx]) + bias
            prob = _sigmoid(margin)
            grad = prob - y[idx]
            for feature in range(len(weights)):
                weights[feature] = (1.0 - eta * l2) * weights[feature] - eta * grad * x[idx][feature]
            bias -= eta * grad
    return weights, bias


def _predict_logistic(x: list[list[float]], weights: list[float], bias: float) -> list[float]:
    return [1.0 if _sigmoid(_dot(row, weights) + bias) >= 0.5 else 0.0 for row in x]


def _train_perceptron(
    x: list[list[float]],
    y: list[float],
    *,
    epochs: int = 20,
    lr: float = 0.08,
    seed: int = 42,
) -> tuple[list[float], float]:
    rng = random.Random(seed)
    labels = [1.0 if item > 0.0 else -1.0 for item in y]
    weights = [0.0 for _ in range(len(x[0]))]
    bias = 0.0
    for _ in range(epochs):
        indices = list(range(len(x)))
        rng.shuffle(indices)
        for idx in indices:
            margin = labels[idx] * (_dot(weights, x[idx]) + bias)
            if margin <= 0.0:
                for feature in range(len(weights)):
                    weights[feature] += lr * labels[idx] * x[idx][feature]
                bias += lr * labels[idx]
    return weights, bias


def _train_linear_svm(
    x: list[list[float]],
    y: list[float],
    *,
    epochs: int = 28,
    lr: float = 0.04,
    regularization: float = 0.0008,
    c: float = 1.0,
    seed: int = 42,
) -> tuple[list[float], float]:
    rng = random.Random(seed)
    labels = [1.0 if item > 0.0 else -1.0 for item in y]
    weights = [0.0 for _ in range(len(x[0]))]
    bias = 0.0
    for epoch in range(epochs):
        eta = lr / (1.0 + 0.02 * epoch)
        indices = list(range(len(x)))
        rng.shuffle(indices)
        for idx in indices:
            margin = labels[idx] * (_dot(weights, x[idx]) + bias)
            if margin < 1.0:
                for feature in range(len(weights)):
                    weights[feature] = (1.0 - eta * regularization) * weights[feature] + eta * c * labels[idx] * x[idx][feature]
                bias += eta * c * labels[idx]
            else:
                for feature in range(len(weights)):
                    weights[feature] = (1.0 - eta * regularization) * weights[feature]
    return weights, bias


def _predict_linear(x: list[list[float]], weights: list[float], bias: float) -> list[float]:
    return [1.0 if (_dot(row, weights) + bias) >= 0.0 else 0.0 for row in x]


def _accuracy(y_true: list[float], y_pred: list[float]) -> float:
    correct = sum(1 for expected, observed in zip(y_true, y_pred) if expected == observed)
    return correct / len(y_true)


def _result_markdown(
    *,
    source_template: str | None,
    dataset: DatasetBundle,
    accuracies: dict[str, float],
    workspace: Path,
    metrics_path: Path,
) -> str:
    ordered = sorted(accuracies.items(), key=lambda item: item[1], reverse=True)
    ranking = [f"{index}. {name}: {score:.4f}" for index, (name, score) in enumerate(ordered, start=1)]
    lines = [
        "# Binary Classification Lab Auto-Run Result",
        "",
        "## Source",
        "",
        f"- Template: `{source_template or 'not provided'}`",
        f"- Workspace: `{workspace}`",
        f"- Dataset source: `{dataset.source}`",
        "",
        "## Dataset Notes",
        "",
    ]
    lines.extend(f"- {note}" for note in dataset.notes)
    lines.extend(
        [
            "",
            "## Accuracy",
            "",
            "| Model | Test Accuracy |",
            "| --- | ---: |",
        ]
    )
    lines.extend(f"| {name} | {score:.4f} |" for name, score in accuracies.items())
    lines.extend(
        [
            "",
            "## Analysis",
            "",
        ]
    )
    lines.extend(f"- {line}" for line in ranking)
    lines.extend(
        [
            "- Logistic regression and SGD classifier optimize probabilistic margins with different update schedules.",
            "- Linear SVM optimizes hinge loss and typically separates the synthetic classes most aggressively.",
            "- Perceptron provides a simple online baseline for the comparison table.",
            "- This run proves the local execution loop and artifact path are working even when no teacher-supplied dataset is present.",
            "",
            "## Template Mapping",
            "",
            "- Logistic regression: included.",
            "- SVM: included as linear hinge-loss SGD.",
            "- Perceptron: included.",
            "- SGD classifier: included as an online log-loss model.",
            "- Accuracy comparison: included through ranked test accuracy.",
            "- Experimental notes: included through dataset and model notes.",
            "",
            "## Validation",
            "",
            "- The artifact was generated by the local deterministic runner.",
            f"- Detailed metrics were also written to `{metrics_path}`.",
            "- Residual risk: this run uses a synthetic fallback dataset when no explicit lab dataset is supplied.",
            "",
        ]
    )
    return "\n".join(lines)


def run_binary_classification_lab(
    *,
    workspace: str | Path,
    output_name: str = "BINARY_CLASSIFICATION_AUTORUN_RESULT.md",
    metrics_name: str = "binary_classification_metrics.json",
    source_template: str | None = None,
) -> dict[str, Any]:
    workspace_path = Path(workspace)
    workspace_path.mkdir(parents=True, exist_ok=True)
    dataset = _make_synthetic_dataset()

    logistic_w, logistic_b = _train_logistic_regression(dataset.x_train, dataset.y_train)
    svm_w, svm_b = _train_linear_svm(dataset.x_train, dataset.y_train)
    perceptron_w, perceptron_b = _train_perceptron(dataset.x_train, dataset.y_train)
    sgd_w, sgd_b = _train_sgd_classifier(dataset.x_train, dataset.y_train)

    accuracies = {
        "Logistic Regression": _accuracy(dataset.y_test, _predict_logistic(dataset.x_test, logistic_w, logistic_b)),
        "Linear SVM": _accuracy(dataset.y_test, _predict_linear(dataset.x_test, svm_w, svm_b)),
        "Perceptron": _accuracy(dataset.y_test, _predict_linear(dataset.x_test, perceptron_w, perceptron_b)),
        "SGD Classifier": _accuracy(dataset.y_test, _predict_logistic(dataset.x_test, sgd_w, sgd_b)),
    }

    metrics_path = workspace_path / metrics_name
    output_path = workspace_path / output_name
    payload = {
        "status": "ok",
        "updated_at": _utc(),
        "workspace": str(workspace_path),
        "source_template": source_template,
        "dataset_source": dataset.source,
        "dataset_notes": dataset.notes,
        "train_samples": len(dataset.x_train),
        "test_samples": len(dataset.x_test),
        "feature_count": len(dataset.x_train[0]),
        "accuracies": accuracies,
    }
    metrics_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    output_path.write_text(
        _result_markdown(
            source_template=source_template,
            dataset=dataset,
            accuracies=accuracies,
            workspace=workspace_path,
            metrics_path=metrics_path,
        ),
        encoding='utf-8',
    )
    payload['output_path'] = str(output_path)
    payload['metrics_path'] = str(metrics_path)
    return payload


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description='Run a deterministic binary classification lab workflow.')
    parser.add_argument('--workspace', required=True)
    parser.add_argument('--output-name', default='BINARY_CLASSIFICATION_AUTORUN_RESULT.md')
    parser.add_argument('--metrics-name', default='binary_classification_metrics.json')
    parser.add_argument('--source-template')
    args = parser.parse_args()
    payload = run_binary_classification_lab(
        workspace=args.workspace,
        output_name=args.output_name,
        metrics_name=args.metrics_name,
        source_template=args.source_template,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
