"""اختبار العقل: فهم الأوامر العربية + التعلم + الحساب."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.brain import Action, Brain, normalize, safe_calc  # noqa: E402
from agent.memory import Memory  # noqa: E402
from agent.policy import Decision, Policy  # noqa: E402


def main() -> int:
    checks: list[tuple[bool, str]] = []

    def check(ok: bool, label: str) -> None:
        checks.append((bool(ok), label))

    # --- تطبيع ---
    check(normalize("أَهْلاً بِك") == "اهلا بك", "تطبيع: تشكيل + همزة")
    check(normalize("مدرسة") == "مدرسه", "تطبيع: تاء مربوطة")
    check(normalize("على") == "علي", "تطبيع: ألف مقصورة")
    check(normalize("صور  الشاشة!!") == "صور الشاشه", "تطبيع: مسافات وعلامات")

    tmp = Path(tempfile.mkdtemp(prefix="brain-"))
    memory = Memory(tmp / "brain.db")
    brain = Brain(memory)

    # --- المهارات الجاهزة ---
    cases = [
        ("افتح يوتيوب", "open_target", "يوتيوب"),
        ("ابحث عن أسعار اللابتوب", "search_web", None),
        ("اقرا ملف notes.txt", "read_file", "notes.txt"),
        ("صور الشاشة", "screenshot", None),
        ("مساحة الديسك", "shell", None),
        ("اقفل الجهاز", "shell", None),
        ("الرام", "shell", None),
        ("اعمل مجلد مشروعي", "shell", None),
        ("دور على ملف *.py", "find_files", None),
        ("ايه الملفات في workspace", "list_dir", "workspace"),
    ]
    for text, tool, target in cases:
        action = brain.think(1, text)
        ok = action is not None and action.tool == tool
        if ok and target is not None:
            args = action.args or {}
            ok = target in str(args.get("target") or args.get("path") or args.get("command") or "")
        check(ok, f"مهارة: «{text}» → {tool}")

    # --- ردود ---
    reply = brain.think(1, "الساعة كام")
    check(reply is not None and ":" in (reply.reply or ""), "رد: الساعة")
    reply = brain.think(1, "احسب 2+3*4")
    check(reply is not None and reply.reply == "= 14", "رد: حساب")

    # --- التعلم ---
    phrase = "رتب المكتب"
    action = Action(tool="shell", args={"command": "Get-ChildItem"})
    intent_id = brain.learn(1, phrase, action)
    check(intent_id > 0, "تعلم: حفظ أمر")

    same = brain.think(1, "رتب المكتب")
    check(same is not None and same.tool == "shell", "تعلم: مطابقة تامة")

    variant = brain.think(1, "رتب المكتب بتاعي")
    check(variant is not None and variant.tool == "shell", "تعلم: مطابقة صيغة مختلفة")

    reply_action = Action(reply="تمام يا فندم")
    brain.learn(1, "قولي حالتك", reply_action)
    got = brain.think(1, "قولي حالتك")
    check(got is not None and got.reply == "تمام يا فندم", "تعلم: رد ثابت")

    check(len(brain.learned(1)) == 2, "تعلم: القائمة")
    check(brain.forget(1, intent_id), "تعلم: الحذف")
    check(brain.think(1, "رتب المكتب") is None, "تعلم: اتمسح فعلاً")

    check(brain.think(1, "اعمل قهوة") is None, "غير معروف → None")

    # --- الحاسبة ---
    check(safe_calc("(2+3)*4") == "= 20", "حساب: أقواس")
    check(safe_calc("1/0").startswith("القسمة"), "حساب: قسمة على صفر")
    check("مسموح" in safe_calc("__import__('os')") or "مش" in safe_calc("__import__('os')"), "حساب: كود مرفوض")

    # --- السياسة ---
    policy = Policy(tmp, "ask")
    check(policy.check("open_target", {"target": "https://x.com"}).decision is Decision.ALLOW, "سياسة: رابط مسموح")
    check(policy.check("open_target", {"target": "calc.exe"}).decision is Decision.ASK, "سياسة: برنامج يسأل")
    check(policy.check("shell", {"command": "Get-PSDrive"}).decision is Decision.ALLOW, "سياسة: Get-PSDrive مسموح")
    check(policy.check("screenshot", {}).decision is Decision.ALLOW, "سياسة: سكرين شوت مسموح")

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
