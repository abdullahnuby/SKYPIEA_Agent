"""اختبار شامل: كوربوس 1000+ مهمة، التدريب، بوابة الثقة، والتوجيه."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.aliases import resolve  # noqa: E402
from agent.brain import Brain  # noqa: E402
from agent.memory import Memory  # noqa: E402
from agent.text import normalize  # noqa: E402
from agent.train.corpus import GOLD_PROBES, OOS_PROBES, generate  # noqa: E402
from agent.train.data import conflicts, dataset  # noqa: E402
from agent.train.routes import build  # noqa: E402
from agent.train.train import train_model  # noqa: E402


def main() -> int:
    checks: list[tuple[bool, str]] = []

    def check(ok: bool, label: str) -> None:
        checks.append((bool(ok), label))

    # ---------- الكوربوس ----------
    tasks = generate()
    rows = dataset()
    check(len(tasks) >= 1000, f"كوربوس المهام: {len(tasks)} صياغة")
    check(len(rows) >= 1000, f"أمثلة التدريب (بعد التنويع): {len(rows)}")

    counts: dict[str, int] = {}
    for _, label in rows:
        counts[label] = counts.get(label, 0) + 1
    smallest = min(counts.values())
    check(smallest >= 30, f"أقل نية عندها {smallest} مثال")
    check(len(counts) == 22, f"عدد النوايا: {len(counts)}")
    check(conflicts() == [], "مفيش تعارض تصنيفات")

    # ---------- التدريب ----------
    model, report = train_model(rows)
    check(report["test_accuracy"] >= 0.90, f"دقة الاختبار {report['test_accuracy']:.1%}")

    # ---------- صيغ جديدة (مش من التدريب) ----------
    seen = {normalize(text, lower=True) for text, _ in rows}
    gold = [(t, e) for t, e in GOLD_PROBES if normalize(t, lower=True) not in seen]
    check(len(gold) >= 15, f"عدد صيغ التقييم الجديدة: {len(gold)}")

    right = 0
    accepted = 0
    for text, expected in gold:
        label, prob, margin = model.predict(text)
        if label != expected:
            continue
        right += 1
        required = Brain.SAFE_MARGIN if label in Brain.SAFE_LABELS else Brain.MODEL_MARGIN
        if prob >= Brain.MODEL_THRESHOLD and margin >= required:
            accepted += 1

    check(right / len(gold) >= 0.85, f"دقة الصيغ الجديدة: {right}/{len(gold)}")
    check(
        accepted / len(gold) >= 0.75,
        f"بيعدّي من بوابة الثقة: {accepted}/{len(gold)}",
    )

    # ---------- رفض الغريب (أخطاء خطيرة = صفر) ----------
    dangerous = 0
    for text in OOS_PROBES:
        label, prob, margin = model.predict(text)
        if label == "unknown" or label in Brain.SAFE_LABELS or prob < Brain.MODEL_THRESHOLD:
            continue
        if margin >= Brain.MODEL_MARGIN:
            dangerous += 1
            print(f"⚠️ جملة غريبة عدّت كأمر: «{text}» → {label} ({margin:.2f})")
    check(dangerous == 0, f"إنذارات كاذبة خطيرة: {dangerous}")

    # ---------- التوجيه ----------
    spec = build("open", "ممكن تفتحلي يوتيوب")
    check(spec is not None and spec["tool"] == "open_target", "توجيه: فتح")
    check(
        spec is not None and "youtube" in str(spec["args"].get("target", "")),
        "توجيه: يوتيوب → رابط",
    )
    spec = build("search", "ابحث عن أسعار الذهب")
    check(spec is not None and spec["tool"] == "search_web", "توجيه: بحث")
    spec = build("read", "اقرا ملف notes.txt")
    check(spec is not None and spec["args"].get("path") == "notes.txt", "توجيه: قراءة ملف")

    check(resolve("اليوتيوب") == "https://youtube.com", "أسماء: اليوتيوب → رابط")
    check(resolve("الفيس بوك") == "https://facebook.com", "أسماء: الفيس بوك → رابط")
    check(resolve("الحاسبة") == "calc.exe", "أسماء: الحاسبة → برنامج")
    check(resolve("حاجة غريبة") == "حاجة غريبة", "أسماء: المجهول يفضل زي ما هو")

    # ---------- العقل ----------
    memory = Memory(Path(tempfile.mkdtemp(prefix="model-")) / "m.db")
    brain = Brain(memory)
    brain.model = model

    def think(text: str):
        return brain.think(7, text)

    action = think("ممكن تفتحلي يوتيوب")
    check(action is not None and action.tool == "open_target", "عقل: صيغة جديدة → فتح")

    action = think("الهارد فاضل فيه كام")
    check(action is not None and action.tool == "shell", "عقل: صيغة جديدة → مساحة")

    action = think("نسبة البطارية كام")
    check(action is not None and action.tool == "shell", "عقل: صيغة جديدة → بطارية")

    check(think("حل الواجب بتاعي") is None, "عقل: خارج النطاق مرفوض")
    check(think("احجزلي مطعم") is None, "عقل: خارج النطاق مرفوض 2")
    check(think("الجو حلو النهاردة") is None, "عقل: كلام عادي مرفوض")

    memory.close()

    failed = 0
    for ok, label in checks:
        print(("✅ " if ok else "❌ ") + label)
        failed += 0 if ok else 1

    print()
    print("كل الاختبارات نجحت ✅" if not failed else f"فشل {failed} من {len(checks)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
