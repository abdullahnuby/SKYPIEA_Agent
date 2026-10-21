"""تشغيل فعلي للمهارات (قراءة فقط) — للتأكد إن أوامر PowerShell سليمة."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import tools  # noqa: E402
from agent.brain import Brain  # noqa: E402
from agent.config import Config  # noqa: E402
from agent.memory import Memory  # noqa: E402
from agent.runtime import rt  # noqa: E402

PHRASES = [
    "مساحة الديسك",
    "الرام",
    "العمليات",
    "البطارية",
    "الاي بي",
    "الساعة كام",
    "تاريخ النهارده",
    "احسب (2+3)*4",
    "ايه الملفات في .",
]


def main() -> int:
    cfg = Config.load()
    cfg.workspace.mkdir(parents=True, exist_ok=True)
    rt.cfg = cfg
    rt.memory = Memory(Path(tempfile.mkdtemp(prefix="real-")) / "t.db")
    brain = Brain(rt.memory)

    failed = 0
    for phrase in PHRASES:
        action = brain.think(1, phrase)
        print(f"\n=== {phrase}")
        if action is None:
            print("❌ مش متعرّف عليها")
            failed += 1
            continue

        if action.reply:
            print(action.reply)
            continue

        output = asyncio.run(tools.run(action.tool or "", action.args))
        bad = "خطأ" in output or "[exit code: 1]" in output or output.strip().startswith("⛔")
        print(("❌ " if bad else "✅ ") + (output[:600].replace("\n", "\n   ")))
        failed += 1 if bad else 0

    rt.memory.close()
    print()
    print("كل المهارات اشتغلت ✅" if not failed else f"فشل {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
