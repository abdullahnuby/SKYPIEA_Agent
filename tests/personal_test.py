"""اختبار الذاكرة الشخصية: استخراج + حفظ + استرجاع + تكامل مع العقل."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.config import Config  # noqa: E402
from agent.core import Agent  # noqa: E402
from agent.memory import Memory  # noqa: E402
from agent.personal import Personal  # noqa: E402
from agent.runtime import rt  # noqa: E402


class FakeTG:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, chat_id, text, keyboard=None, **kwargs):  # noqa: ANN001, ANN003
        self.sent.append(str(text))
        return {"ok": True}

    async def typing(self, chat_id):  # noqa: ANN001
        return None

    async def send_photo(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return False


def main() -> int:
    checks: list[tuple[bool, str]] = []

    def check(ok: bool, label: str) -> None:
        checks.append((bool(ok), label))

    tmp = Path(tempfile.mkdtemp(prefix="personal-"))
    db_path = tmp / "memory.db"
    memory = Memory(db_path)
    person = Personal(memory)
    chat = 42

    # ---------- استخراج ----------
    person.observe(chat, "اسمي عبدالله")
    check(person.name(chat) == "عبدالله", "استخراج: الاسم")

    person.observe(chat, "أنا من القاهرة")
    check(
        any(f["key"] == "المدينة" and f["value"] == "القاهرة" for f in memory.all_facts(chat)),
        "استخراج: المدينة",
    )

    person.observe(chat, "أنا مهندس")
    check(
        any(f["key"] == "الوظيفة" for f in memory.all_facts(chat)),
        "استخراج: الوظيفة",
    )

    person.observe(chat, "بشتغل في شركة بيانات")
    check(
        any(f["key"] == "الشغل" for f in memory.all_facts(chat)),
        "استخراج: الشغل",
    )

    person.observe(chat, "بحب القهوة السادة")
    person.observe(chat, "بحب الشوكولاتة")
    likes = [f["value"] for f in memory.get_facts(chat, "بحب")]
    check(len(likes) == 2, "استخراج: أكتر من حاجة بيحبها")

    person.observe(chat, "مش بحب الزحمة")
    dislikes = [f["value"] for f in memory.get_facts(chat, "مش_بحب")]
    check(dislikes == ["الزحمة"], "استخراج: مش بيحب")
    check(all("الزحمة" not in v for v in likes), "استخراج: مفيش تداخل بين بحب/مش بحب")

    person.observe(chat, "رقمي 01012345678")
    check(
        any(f["key"] == "الموبايل" for f in memory.all_facts(chat)),
        "استخراج: الموبايل",
    )

    person.observe(chat, "مشروعي متجر إلكتروني")
    check(any(f["key"] == "مشروع" for f in memory.all_facts(chat)), "استخراج: المشروع")

    person.observe(chat, "هدفي أتعلم بايثون")
    check(any(f["key"] == "هدف" for f in memory.all_facts(chat)), "استخراج: الهدف")

    person.observe(chat, "بستخدم كروم")
    check(any(f["key"] == "بستخدم" for f in memory.all_facts(chat)), "استخراج: بيستخدم")

    person.observe(chat, "اسمي ايه؟")
    check(
        not any(f["value"].strip("؟ ?") in {"ايه", "إيه"} for f in memory.all_facts(chat)),
        "استخراج: الأسئلة مش بتتحفظ كحقائق",
    )

    # ---------- قيمة واحدة ----------
    person.observe(chat, "اسمي أحمد")
    names = memory.get_facts(chat, "الاسم")
    check(len(names) == 1 and names[0]["value"] == "أحمد", "الاسم: بيتحدّث مش بيتكرر")
    person.observe(chat, "اسمي عبدالله")

    # ---------- الأسرار ----------
    before = memory.count_facts(chat)
    person.observe(chat, "الباسورد بتاعي 123456")
    check(memory.count_facts(chat) == before, "أسرار: الباسورد مش بيتحفظ")
    reply = person.handle(chat, "افتكر إن كلمة السر هي 123")
    check("🔒" in (reply or "") and memory.count_facts(chat) == before, "أسرار: رفض واضح")

    # ---------- ملاحظة صريحة ----------
    reply = person.handle(chat, "افتكر إن شغلي بيبدأ 9 الصبح")
    check("حفظت" in (reply or ""), "ملاحظة: تأكيد الحفظ")
    check(
        any("بيبدأ 9" in f["value"] for f in memory.get_facts(chat, "ملاحظة")),
        "ملاحظة: اتخزنت",
    )

    # ---------- استرجاع ----------
    reply = person.handle(chat, "انت فاكر ايه عني؟")
    check("اللي فاكره" in (reply or "") and "عبدالله" in (reply or ""), "استرجاع: البروفايل")
    check("القهوة" in (reply or ""), "استرجاع: بيحب القهوة")

    reply = person.handle(chat, "اسمي ايه؟")
    check("عبدالله" in (reply or ""), "استرجاع: سؤال الاسم")

    memory.add_message(chat, {"role": "user", "content": "عايز أعمل موقع جديد للمتجر"})
    reply = person.handle(chat, "احنا كنا بنتكلم عن ايه؟")
    check("موقع جديد" in (reply or ""), "استرجاع: آخر المحادثات")

    block = person.prompt_block(chat)
    check("عبدالله" in block and "القهوة" in block, "LLM: معلومات المستخدم بتتحقن")

    check(person.personalize(chat, "أهلاً 👋").startswith("أهلاً يا عبدالله"), "تحية شخصية")

    # ---------- الاستمرارية ----------
    memory.close()
    memory = Memory(db_path)
    person = Personal(memory)
    check(person.name(chat) == "عبدالله", "استمرارية: الذاكرة بعد إعادة الفتح")

    # ---------- المسح ----------
    fact = memory.get_facts(chat, "بحب")[0]
    check(person.forget(chat, int(fact["id"])), "مسح: اتشالت")
    check(len(memory.get_facts(chat, "بحب")) == 1, "مسح: الباقي زي ما هو")

    # ---------- التكامل مع الـ Agent ----------
    cfg = replace(Config.load(), agent_mode="rules", workspace=tmp / "ws")
    cfg.workspace.mkdir(parents=True, exist_ok=True)
    rt.cfg = cfg
    rt.memory = memory
    tg = FakeTG()
    agent = Agent(cfg, None, tg, memory)  # type: ignore[arg-type]
    chat2 = 77

    asyncio.run(agent.handle(chat2, "اسمي عبدالله"))
    check(any("حفظت" in m for m in tg.sent), "Agent: بيرد بتأكيد الحفظ")

    tg.sent.clear()
    asyncio.run(agent.handle(chat2, "انت فاكر ايه عني؟"))
    check(any("عبدالله" in m for m in tg.sent), "Agent: بيرد من الذاكرة")

    tg.sent.clear()
    asyncio.run(agent.handle(chat2, "السلام عليكم"))
    check(
        any(m.startswith("أهلاً يا عبدالله") for m in tg.sent),
        "Agent: تحية شخصية",
    )

    tg.sent.clear()
    asyncio.run(agent.handle(chat2, "مساحة الديسك"))
    check(any("Name" in m or "FreeGB" in m for m in tg.sent), "Agent: الأوامر لسه شغالة")

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
