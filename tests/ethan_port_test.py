"""اختبار الميزات اللي اتاخدت من ethan-agent.

بيغطي: الذاكرة المنظّمة + الأدلة + الترقية + التقادم + الاسترجاع بالنية +
قواعد السلوك + تصدير البروفايل + مهارات Markdown + cron + حماية الدوران +
بيانات الأدوات.
"""

from __future__ import annotations

import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.cron import CronSpec, next_run  # noqa: E402
from agent.loop_control import LoopGuard, finalize_suffix, reflection_message  # noqa: E402
from agent.memory import Memory  # noqa: E402
from agent.personal import (  # noqa: E402
    Personal,
    classify_intent,
    dimension_of,
    type_of_dimension,
)
from agent.skills_md import MarkdownSkills  # noqa: E402
from agent import tools  # noqa: E402

CHAT = 4242


def main() -> int:
    checks: list[tuple[bool, str]] = []

    def check(ok: bool, label: str) -> None:
        checks.append((bool(ok), label))

    # ---------- 1) الأبعاد ----------
    check(dimension_of("الاسم") == "identity.preferred_name", "بُعد: الاسم")
    check(dimension_of("بحب") == "preference.likes", "بُعد: بحب")
    check(dimension_of("مشروع") == "activity.project", "بُعد: مشروع")
    check(dimension_of("قرار") == "decision.chosen", "بُعد: قرار")
    check(dimension_of("علاقة") == "relationship.role", "بُعد: علاقة")
    check(dimension_of("طريقة") == "methodology.workflow", "بُعد: طريقة")
    check(type_of_dimension("identity.location") == "identity", "نوع البُعد")

    # حقائق قديمة بدون بُعد بتتربط تلقائيًا
    legacy_db = Path(tempfile.mkdtemp()) / "legacy.db"
    legacy = Memory(legacy_db)
    legacy_id = legacy.save_fact(99, "الاسم", "قديم", scalar=True)
    legacy_personal = Personal(legacy)
    filled = legacy_personal.backfill_dimensions()
    check(filled == 1, "ترحيل: حقيقة قديمة اتعبّت")
    check(
        legacy.all_facts(99)[0]["dimension"] == "identity.preferred_name",
        "ترحيل: البُعد صح",
    )

    # ---------- 2) حفظ صريح + دليل ----------
    db = Path(tempfile.mkdtemp()) / "memory.db"
    memory = Memory(db)
    personal = Personal(memory)
    fact_id = memory.save_fact(
        CHAT,
        "الاسم",
        "عبدالله",
        "test",
        scalar=True,
        dimension="identity.preferred_name",
        evidence="explicit",
        confidence=0.95,
        quote="اسمي عبدالله",
        session_id="s1",
    )
    facts = memory.all_facts(CHAT)
    check(len(facts) == 1 and facts[0]["value"] == "عبدالله", "حفظ: قيمة واحدة")
    check(facts[0]["dimension"] == "identity.preferred_name", "حفظ: البُعد اتخزن")
    check(facts[0]["quote"] == "اسمي عبدالله", "حفظ: الاقتباس (quote) اتخزن")
    check(abs(float(facts[0]["confidence"]) - 0.95) < 1e-6, "حفظ: الثقة اتخزنت")
    check(memory.fact_sessions(fact_id) == 1, "دليل: جلسة واحدة")

    # ---------- 3) الاستبدال (supersede) ----------
    new_id = memory.save_fact(
        CHAT,
        "الاسم",
        "أحمد",
        "test",
        scalar=True,
        dimension="identity.preferred_name",
        evidence="corrected",
        confidence=1.0,
        quote="لأ اسمي أحمد",
        session_id="s2",
    )
    active = memory.all_facts(CHAT)
    all_rows = memory.all_facts(CHAT, include_inactive=True)
    check(len(active) == 1 and active[0]["value"] == "أحمد", "استبدال: القيمة النشطة الجديدة")
    check(len(all_rows) == 2, "استبدال: التاريخ محفوظ")
    old = [row for row in all_rows if row["value"] == "عبدالله"][0]
    check(old["status"] == "superseded", "استبدال: القديم superseded")
    check(old["superseded_by"] == new_id, "استبدال: رابط القديم بالجديد")

    # ---------- 4) الملاحظة والترقية ----------
    obs_id = memory.save_fact(
        CHAT,
        "طريقة",
        "ببدأ بالمهمة الصعبة",
        "test",
        dimension="methodology.workflow",
        evidence="observed",
        confidence=0.5,
        quote="بشتغل كده",
        session_id="s1",
        status="pending",
    )
    check(not any(f["id"] == obs_id for f in memory.all_facts(CHAT)), "ملاحظة: pending مش نشطة")
    memory.add_evidence(CHAT, obs_id, "s2", "observed", "بشتغل كده تاني")
    promoted = memory.promote_pending(CHAT)
    check(promoted == 1, "ملاحظة: اترقّت بعد جلستين")
    promoted_fact = [f for f in memory.all_facts(CHAT) if f["id"] == obs_id][0]
    check(promoted_fact["evidence"] == "inferred", "ملاحظة: الدليل بقى inferred")
    check(float(promoted_fact["confidence"]) >= 0.7, "ملاحظة: الثقة اتقوّت")

    # ---------- 5) التقادم ----------
    old_fact = memory.save_fact(
        CHAT,
        "مشروع",
        "مشروع قديم",
        "test",
        dimension="activity.project",
        evidence="explicit",
        quote="مشروعي مشروع قديم",
        session_id="s1",
    )
    ancient = time.time() - 200 * 86400
    with memory._lock:  # noqa: SLF001 — اختبار داخلي مقصود
        memory._db.execute(
            "UPDATE facts SET created_at=?, updated_at=?, last_recalled_at=NULL WHERE id=?",
            (ancient, ancient, old_fact),
        )
        memory._db.commit()
    result = memory.consolidate(CHAT)
    check(result["dormant"] >= 1, "تقادم: المهمة القديمة نامت")
    check(not any(f["id"] == old_fact for f in memory.all_facts(CHAT)), "تقادم: مش في النشط")
    with memory._lock:  # noqa: SLF001
        memory._db.execute(
            "UPDATE facts SET updated_at=?, created_at=? WHERE id=?", (ancient, ancient, old_fact)
        )
        memory._db.commit()
    memory.consolidate(CHAT)
    forgotten = [
        f for f in memory.all_facts(CHAT, include_inactive=True) if f["id"] == old_fact
    ][0]
    check(forgotten["status"] == "forgotten", "تقادم: اتمسح بعد 180 يوم")
    check(forgotten["value"] == "[منسي]", "تقادم: القيمة اتمسحت")

    # الهوية معفاة من التقادم
    name_id = memory.save_fact(
        CHAT, "المدينة", "القاهرة", "test", scalar=True,
        dimension="identity.location", session_id="s1",
    )
    with memory._lock:  # noqa: SLF001
        memory._db.execute(
            "UPDATE facts SET updated_at=?, created_at=? WHERE id=?", (ancient, ancient, name_id)
        )
        memory._db.commit()
    memory.consolidate(CHAT)
    check(any(f["id"] == name_id for f in memory.all_facts(CHAT)), "تقادم: الهوية معفاة")

    # ---------- 6) الاسترجاع بالنية ----------
    memory.save_fact(
        CHAT, "بحب", "القهوة السادة", "test",
        dimension="preference.likes", session_id="s1",
    )
    memory.save_fact(
        CHAT, "هدف", "أبني agent عربي", "test",
        dimension="identity.long_term_goal", session_id="s1",
    )
    check(classify_intent("فاكر ايه عن شغلي؟") == "identity", "نية: هوية")
    check(classify_intent("بحب ايه؟") == "preference", "نية: تفضيل")
    check(classify_intent("واقف في ايه؟") == "activity", "نية: نشاط")
    check(classify_intent("قررت ايه؟") == "decision", "نية: قرار")
    top = personal.recall(CHAT, "بحب ايه؟", limit=3)
    check(bool(top) and top[0]["key"] == "بحب", "استرجاع: التفضيل الأول")
    top_goal = personal.recall(CHAT, "هدفي ايه؟", limit=3)
    check(bool(top_goal) and top_goal[0]["key"] == "هدف", "استرجاع: الهدف الأول")
    reply = personal.recall_reply(CHAT, "بحب")
    check("القهوة" in reply, "استرجاع: الرد فيه القيمة")

    # ---------- 7) قواعد السلوك ----------
    rule_reply = personal.handle(CHAT, "من دلوقتي ردودك تكون مختصرة")
    check(bool(rule_reply) and "اتعلمت" in str(rule_reply), "قاعدة: اتعلمت من التصريح")
    rules = personal.rules(CHAT)
    check(len(rules) == 1 and "ردودك" in rules[0]["rule"], "قاعدة: اتخزنت")
    long_reply = "ا" * 900
    check(len(personal.apply_rules(CHAT, long_reply)) <= 501, "قاعدة: الاختصار اتطبق")
    correction = personal.handle(CHAT, "لا، المفروض تقولي الأول")
    check(bool(correction) and "اتعلمت" in str(correction), "قاعدة: اتعلمت من التصحيح")
    check(len(personal.rules(CHAT)) == 2, "قاعدة: التصحيح اتضاف")
    check(personal.forget_rule(CHAT, int(rules[0]["id"])), "قاعدة: اتمسحت")

    # ---------- 7.5) الملاحظة الضعيفة من كلام غير مباشر ----------
    weak_reply = personal.handle(CHAT, "مهتم بالذكاء الاصطناعي")
    check("سجلت ملاحظة" in str(weak_reply), "ملاحظة ضعيفة: اتسجلت")
    check(
        not any("الذكاء" in str(f["value"]) for f in memory.all_facts(CHAT)),
        "ملاحظة ضعيفة: مش نشطة",
    )
    personal.rotate_session(CHAT)
    personal.handle(CHAT, "مهتم بالذكاء الاصطناعي")
    memory.promote_pending(CHAT)
    check(
        any("الذكاء" in str(f["value"]) for f in memory.all_facts(CHAT)),
        "ملاحظة ضعيفة: اترقّت بعد يومين",
    )

    # ---------- 8) البروفايل ----------
    path = personal.export_profile(CHAT)
    text = path.read_text(encoding="utf-8")
    check(path.exists() and "بروفايل المستخدم" in text, "بروفايل: الملف اتكتب")
    check("أحمد" in text and "القهوة" in text, "بروفايل: القيم موجودة")
    check("قواعد السلوك" in text, "بروفايل: القواعد موجودة")
    path.unlink(missing_ok=True)

    # ---------- 9) مهارات Markdown ----------
    skill_dir = Path(tempfile.mkdtemp())
    (skill_dir / "hello").mkdir()
    (skill_dir / "hello" / "SKILL.md").write_text(
        "---\n"
        "name: hello\n"
        "description: رد ترحيبي\n"
        "trigger: \"أهلاً بالعالم|hello world\"\n"
        "reply: \"أهلاً {match} 👋\"\n"
        "---\n",
        encoding="utf-8",
    )
    (skill_dir / "site").mkdir()
    (skill_dir / "site" / "SKILL.md").write_text(
        "---\n"
        "name: site\n"
        "trigger: \"افتح الموقع\"\n"
        "tool: open_target\n"
        "args: {\"target\": \"{match}\"}\n"
        "---\n",
        encoding="utf-8",
    )
    md = MarkdownSkills(skill_dir)
    loaded = md.all()
    check(len(loaded) == 2, "مهارات MD: اتحمّلت")
    action = md.match("أهلاً بالعالم")
    check(action is not None and action.reply is not None, "مهارات MD: رد")
    check("أهلاً بالعالم" in str(action.reply), "مهارات MD: {match} اتعوّض")
    tool_action = md.match("افتح الموقع")
    check(
        tool_action is not None and tool_action.tool == "open_target",
        "مهارات MD: أداة",
    )

    # ---------- 10) cron ----------
    base = datetime(2026, 10, 21, 10, 30).timestamp()
    every_15 = datetime.fromtimestamp(next_run("*/15 * * * *", base))
    check((every_15.hour, every_15.minute) == (10, 45), "cron: */15")
    sunday_9 = datetime.fromtimestamp(next_run("0 9 * * 0", base))
    check(sunday_9.weekday() == 6 and sunday_9.hour == 9, "cron: الأحد 9")
    first_of_month = datetime.fromtimestamp(next_run("30 8 1 * *", base))
    check(first_of_month.day == 1 and first_of_month.hour == 8, "cron: أول الشهر")
    spec = CronSpec("0 9 * * mon-fri")
    check(spec.matches(datetime(2026, 10, 21, 9, 0)), "cron: أيام العمل")
    check(not spec.matches(datetime(2026, 10, 24, 9, 0)), "cron: السبت مرفوض")
    try:
        CronSpec("bad")
        check(False, "cron: تعبير غلط مرفوض")
    except ValueError:
        check(True, "cron: تعبير غلط مرفوض")

    # ---------- 11) حماية الدوران ----------
    guard = LoopGuard()
    calls = [{"function": {"name": "read_file", "arguments": "{\"path\":\"a\"}"}}]
    for _ in range(3):
        guard.record(calls, ["⛔ خطأ"])
    check(guard.stuck(), "loop: اكتشف التكرار")
    check(not guard.exhausted(), "loop: لسه فيه فرصة")
    guard.mark_reflected()
    guard.mark_reflected()
    check(guard.exhausted(), "loop: استنفد المحاولات")
    check("بتكرر" in reflection_message(guard), "loop: رسالة التشخيص")
    check("توقفت" in finalize_suffix(), "loop: رسالة الإنهاء")

    # ---------- 12) بيانات الأدوات ----------
    described = tools.describe()
    names = {row["name"] for row in described}
    check({"read_file", "shell", "write_file"} <= names, "أدوات: الوصف موجود")
    long_text = "A" * 9000 + "TAIL"
    cut = tools.truncate(long_text, 2000)
    check(len(cut) < 2600 and "TAIL" in cut, "أدوات: قص الرأس والذيل")

    # ---------- النتيجة ----------
    for ok, label in checks:
        print(("✅" if ok else "❌") + " " + label)
    failed = [label for ok, label in checks if not ok]
    print()
    if failed:
        print(f"فشل {len(failed)} من {len(checks)}")
        return 1
    print(f"كل الاختبارات نجحت ✅ ({len(checks)} فحص)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
