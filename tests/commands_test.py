"""اختبار أوامر البوت الجديدة (rules / cron / tools / profile / recall)."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.config import Config  # noqa: E402
from agent.core import Agent  # noqa: E402
from agent.main import Dispatcher  # noqa: E402
from agent.memory import Memory  # noqa: E402

CHAT = 777001


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

    def last(self) -> str:
        return self.sent[-1] if self.sent else ""


async def main() -> int:
    checks: list[tuple[bool, str]] = []

    def check(ok: bool, label: str) -> None:
        checks.append((bool(ok), label))

    tmp = Path(tempfile.mkdtemp())
    cfg = replace(
        Config.load(),
        db_path=tmp / "agent.db",
        workspace=tmp / "workspace",
        log_path=tmp / "audit.log",
        approval_mode="auto",
        agent_mode="rules",
    )
    cfg.workspace.mkdir(parents=True, exist_ok=True)
    memory = Memory(cfg.db_path)
    tg = FakeTG()
    agent = Agent(cfg, None, tg, memory)  # type: ignore[arg-type]
    dispatcher = Dispatcher(cfg, agent, tg, memory)  # type: ignore[arg-type]

    await dispatcher._command(CHAT, "/status", "")
    status = tg.last()
    check("قواعد سلوك" in status and "مهارات Markdown" in status, "أمر: /status")
    check("rules" in status or "قواعد" in status, "أمر: /status الوضع")

    await dispatcher._command(CHAT, "/cron", "0 9 * * * راجع الإيميل")
    cron_reply = tg.last()
    check("اتجدولت" in cron_reply and "0 9 * * *" in cron_reply, "أمر: /cron")
    tasks = memory.list_tasks(CHAT)
    check(len(tasks) == 1 and tasks[0]["cron_expr"] == "0 9 * * *", "أمر: cron اتخزن")

    await dispatcher._command(CHAT, "/tasks", "")
    check("0 9 * * *" in tg.last(), "أمر: /tasks بيعرض cron")

    await dispatcher._command(CHAT, "/cron", "bad expr")
    check("الصيغة" in tg.last() or "غلط" in tg.last(), "أمر: cron غلط")

    await dispatcher._command(CHAT, "/tools", "")
    check("read_file" in tg.last() and "shell" in tg.last(), "أمر: /tools")

    await dispatcher._command(CHAT, "/recall", "شغلي")
    check("مفيش عندي" in tg.last(), "أمر: /recall فاضي")

    memory.save_fact(
        CHAT, "الشغل", "شركة بيانات", "test", scalar=True,
        dimension="identity.organization", quote="بشتغل في شركة بيانات", session_id="s1",
    )
    await dispatcher._command(CHAT, "/recall", "شغلي")
    check("شركة بيانات" in tg.last(), "أمر: /recall لقى المعلومة")

    await dispatcher._command(CHAT, "/profile", "")
    check("بروفايلك" in tg.last(), "أمر: /profile")
    profile = Path("data") / "profiles" / f"{CHAT}.md"
    check(profile.exists(), "أمر: ملف البروفايل اتكتب")
    profile.unlink(missing_ok=True)

    await dispatcher._command(CHAT, "/rules", "")
    check("مفيش قواعد" in tg.last(), "أمر: /rules فاضي")

    personal = agent.personal
    personal.handle(CHAT, "من دلوقتي ردودك تكون مختصرة")
    await dispatcher._command(CHAT, "/rules", "")
    check("ردودك" in tg.last(), "أمر: /rules بعد التعلم")
    rule_id = personal.rules(CHAT)[0]["id"]
    await dispatcher._command(CHAT, "/forget_rule", str(rule_id))
    check("تم مسح" in tg.last(), "أمر: /forget_rule")

    await dispatcher._command(CHAT, "/skills", "")
    check("morning" in tg.last() and "Markdown" in tg.last(), "أمر: /skills فيها Markdown")

    await dispatcher._command(CHAT, "/consolidate", "")
    check("تنظيف الذاكرة" in tg.last(), "أمر: /consolidate")

    await dispatcher._command(CHAT, "/new", "")
    check("بدأنا من جديد" in tg.last(), "أمر: /new")

    (Path("data") / "profiles" / f"{CHAT}.md").unlink(missing_ok=True)

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
    raise SystemExit(asyncio.run(main()))
