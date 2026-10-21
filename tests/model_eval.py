"""تقييم الموديل على صيغ جديدة (مش من بيانات التدريب)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.config import Config  # noqa: E402
from agent.text import normalize  # noqa: E402
from agent.train.corpus import GOLD_PROBES  # noqa: E402
from agent.train.data import dataset  # noqa: E402
from agent.train.model import IntentModel  # noqa: E402


def main() -> int:
    cfg = Config.load()
    model = IntentModel.load(cfg.intent_model)
    if model is None:
        print("مفيش موديل — شغّل py -m agent.train.train")
        return 1

    seen = {normalize(text, lower=True) for text, _ in dataset()}
    correct = 0
    novel = 0
    for text, expected in GOLD_PROBES:
        if normalize(text, lower=True) in seen:
            print(f"⏭️  «{text}» موجود في التدريب — متخطّى")
            continue
        novel += 1
        label, prob, margin = model.predict(text)
        ok = label == expected
        correct += ok
        print(
            f"{'✅' if ok else '❌'} «{text}» → {label} "
            f"({prob:.2f}, فرق {margin:.2f}) متوقع: {expected}"
        )

    print(f"\n{correct}/{novel} على {novel} صيغة جديدة")
    return 0 if correct >= max(1, int(novel * 0.9)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
