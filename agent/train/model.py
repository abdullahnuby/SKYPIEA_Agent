"""موديل تصنيف نوايا صغير: char n-grams + انحدار لوجستي (numpy فقط)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np

from ..text import normalize

DIM = 2048


def _bucket(gram: str, dim: int) -> int:
    digest = hashlib.blake2b(gram.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") % dim


def featurize(text: str, dim: int = DIM) -> np.ndarray:
    """كلمات + ثنائيات كلمات + مقاطع حروف (3-grams) مع hashing، ثم تطبيع L2."""
    vec = np.zeros(dim, dtype=np.float32)
    norm = normalize(text, lower=True)
    if not norm:
        return vec
    words = norm.split()
    grams = list(words)
    grams += [f"{a}|{b}" for a, b in zip(words, words[1:])]
    grams += [norm[i : i + 3] for i in range(max(0, len(norm) - 2))]
    for gram in grams:
        vec[_bucket(gram, dim)] += 1.0
    length = float(np.linalg.norm(vec))
    if length:
        vec /= length
    return vec


def _softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - logits.max(axis=-1, keepdims=True)
    exp = np.exp(shifted)
    return exp / exp.sum(axis=-1, keepdims=True)


class IntentModel:
    def __init__(self, labels: list[str], weights: np.ndarray, bias: np.ndarray) -> None:
        self.labels = labels
        self.weights = weights
        self.bias = bias
        self.dim = int(weights.shape[1])

    def predict(self, text: str) -> tuple[str, float, float]:
        probs = _softmax(self.weights @ featurize(text, self.dim) + self.bias)
        order = np.argsort(probs)
        top = int(order[-1])
        second = int(order[-2]) if len(order) > 1 else top
        return self.labels[top], float(probs[top]), float(probs[top] - probs[second])

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            path,
            weights=self.weights,
            bias=self.bias,
            labels=np.array(self.labels),
        )

    @classmethod
    def load(cls, path: Path) -> "IntentModel | None":
        try:
            if not path.exists():
                return None
            data = np.load(path, allow_pickle=False)
            return cls(
                labels=[str(x) for x in data["labels"]],
                weights=data["weights"].astype(np.float32),
                bias=data["bias"].astype(np.float32),
            )
        except Exception:  # noqa: BLE001 — موديل تالف مايكسرش البوت
            return None
