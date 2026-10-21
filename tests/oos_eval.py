"""قياس الإنذارات الكاذبة: جمل عادية مش أوامر — لازم تتسجّل unknown أو تُرفض."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.brain import Brain  # noqa: E402
from agent.config import Config  # noqa: E402
from agent.memory import Memory  # noqa: E402
from agent.train.corpus import OOS_PROBES  # noqa: E402


def main() -> int:
    cfg = Config.load()
    memory = Memory(Path(tempfile.mkdtemp(prefix="oos-")) / "m.db")
    brain = Brain(memory, cfg.intent_model)

    passed = 0
    for text in OOS_PROBES:
        action = brain.think(999, text)
        if action is None:
            print(f"✅ «{text}» → مرفوض")
        else:
            passed += 1
            print(f"⚠️ «{text}» → {action.tool or 'رد'}: {(action.reply or action.args)}")

    memory.close()
    print(f"\nإجمالي اللي عدّى غلط: {passed}/{len(OOS_PROBES)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
