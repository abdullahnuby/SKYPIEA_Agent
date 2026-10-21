"""ضبط بوابة الثقة: كام أمر صح بيعدّي مقابل كام جملة غريبة بتعدّي غلط."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.config import Config  # noqa: E402
from agent.text import normalize  # noqa: E402
from agent.train.corpus import GOLD_PROBES, OOS_PROBES  # noqa: E402
from agent.train.data import dataset  # noqa: E402
from agent.train.model import IntentModel  # noqa: E402

# الردود الكلامية البسيطة: لو اتصنّفت غلط مش كارثة
SAFE_LABELS = {"greet", "who", "time", "date", "help"}
SAFE_MARGIN = 0.15
ACTION_MARGINS = (0.20, 0.25, 0.30, 0.35)


def accepted(label: str, prob: float, margin: float, action_margin: float) -> bool:
    if label == "unknown" or prob < 0.15:
        return False
    if label in SAFE_LABELS:
        return margin >= SAFE_MARGIN
    return margin >= action_margin


def main() -> int:
    cfg = Config.load()
    model = IntentModel.load(cfg.intent_model)
    if model is None:
        print("مفيش موديل")
        return 1

    seen = {normalize(text, lower=True) for text, _ in dataset()}

    gold = [
        (text, expected)
        for text, expected in GOLD_PROBES
        if normalize(text, lower=True) not in seen
    ]
    gold_preds = [(expected, *model.predict(text)) for text, expected in gold]
    oos_preds = [model.predict(text) for text in OOS_PROBES]

    print(f"صيغ جديدة: {len(gold)} | جمل غريبة: {len(oos_preds)}\n")
    print(f"{'عتبة الأوامر':>12} | {'صح وعدّى':>10} | {'غلط وعدّى':>10}")
    print("-" * 42)
    for t in ACTION_MARGINS:
        ok = sum(
            1
            for expected, label, prob, margin in gold_preds
            if label == expected and accepted(label, prob, margin, t)
        )
        fp = sum(1 for label, prob, margin in oos_preds if accepted(label, prob, margin, t))
        print(f"{t:>12.2f} | {ok:>10} | {fp:>10}")

    print("\nاللي بيعدّى غلط عند 0.30:")
    for text, (label, prob, margin) in zip(OOS_PROBES, oos_preds):
        if accepted(label, prob, margin, 0.30):
            print(f"  ⚠️ «{text}» → {label} ({prob:.2f}, فرق {margin:.2f})")

    print("\nأوامر صح اتقفلت عند 0.30:")
    for text, (expected, label, prob, margin) in zip(gold, gold_preds):
        if label == expected and not accepted(label, prob, margin, 0.30):
            print(f"  🔒 «{text}» → {label} (فرق {margin:.2f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
