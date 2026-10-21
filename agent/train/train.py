"""تدريب موديل النوايا وتقييمه.

    py -m agent.train.train
"""

from __future__ import annotations

import random
from pathlib import Path

import numpy as np

from ..config import Config
from .data import dataset
from .model import IntentModel, featurize


def train_model(
    rows: list[tuple[str, str]],
    *,
    epochs: int = 1200,
    lr: float = 2.0,
    l2: float = 1e-5,
    test_ratio: float = 0.2,
    seed: int = 7,
) -> tuple[IntentModel, dict[str, float]]:
    rng = random.Random(seed)
    data = list(rows)
    rng.shuffle(data)

    split = max(1, int(len(data) * (1 - test_ratio)))
    train_rows, test_rows = data[:split], data[split:]

    classes = sorted({label for _, label in data})
    index_of = {label: i for i, label in enumerate(classes)}

    X = np.stack([featurize(text) for text, _ in train_rows])
    y = np.array([index_of[label] for _, label in train_rows], dtype=np.int64)

    X_test = np.stack([featurize(text) for text, _ in test_rows])
    y_test = np.array([index_of[label] for _, label in test_rows], dtype=np.int64)

    n, dim = X.shape
    c = len(classes)
    W = np.zeros((c, dim), dtype=np.float32)
    b = np.zeros(c, dtype=np.float32)
    onehot = np.zeros((n, c), dtype=np.float32)
    onehot[np.arange(n), y] = 1.0

    rate = lr
    for _ in range(epochs):
        logits = X @ W.T + b
        logits -= logits.max(axis=1, keepdims=True)
        exp = np.exp(logits)
        probs = exp / exp.sum(axis=1, keepdims=True)

        diff = (probs - onehot) / n
        W -= rate * (diff.T @ X + l2 * W)
        b -= rate * diff.sum(axis=0)
        rate *= 0.999

    model = IntentModel(classes, W, b)

    train_pred = np.argmax(X @ W.T + b, axis=1)
    test_logits = X_test @ W.T + b
    test_pred = np.argmax(test_logits, axis=1)

    report = {
        "train_accuracy": float((train_pred == y).mean()),
        "test_accuracy": float((test_pred == y_test).mean()),
        "train_size": float(len(train_rows)),
        "test_size": float(len(test_rows)),
        "classes": float(c),
    }
    return model, report


def train_and_save(path: Path) -> tuple[IntentModel, dict[str, float]]:
    model, report = train_model(dataset())
    model.save(path)
    return model, report


def main() -> int:
    cfg = Config.load()
    model, report = train_and_save(cfg.intent_model)
    print(f"اتدرّب على {int(report['train_size'])} مثال، واتاختبر على {int(report['test_size'])}")
    print(f"دقة التدريب: {report['train_accuracy']:.1%}")
    print(f"دقة الاختبار: {report['test_accuracy']:.1%}")
    print(f"عدد التصنيفات: {int(report['classes'])}")
    print(f"اتحفظ في: {cfg.intent_model}")

    probes = [
        "ممكن تفتحلي يوتيوب؟",
        "اديني مساحة الديسك",
        "قولي كام الساعة",
        "عايز اشوف العمليات الشغالة",
        "ممكن صورة للشاشة بسرعة",
    ]
    print("\nأمثلة:")
    for phrase in probes:
        label, prob, margin = model.predict(phrase)
        print(f"  «{phrase}» → {label} ({prob:.2f}, فرق {margin:.2f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
