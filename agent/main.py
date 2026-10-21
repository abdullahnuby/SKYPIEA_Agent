"""نقطة التشغيل: بوت تيليجرام + المجدول."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from logging.handlers import RotatingFileHandler
from typing import Any

from . import tools
from .brain import Action
from .config import Config
from .core import Agent
from .llm import LLM, LLMError
from .memory import Memory
from .runtime import rt
from .scheduler import scheduler_loop
from .skills import SKILLS
from .telegram import Telegram, TelegramError, esc

log = logging.getLogger("agent")

HELP = """🤖 <b>الأوامر</b>

/new — محادثة جديدة من الصفر
/status — حالة الـ agent
/pause — إيقاف مؤقت
/resume — رجوع للشغل
/skills — المهارات الجاهزة + مهارات Markdown + اللي علّمتها
/facts — اللي فاكره عنك (ذاكرتك)
/recall &lt;موضوع&gt; — استرجاع ذكي عن موضوع
/forget_fact &lt;رقم&gt; — امسح معلومة من ذاكرتي
/profile — يصدّر بروفايلك كملف Markdown
/rules — قواعد السلوك اللي اتعلمتها منك
/forget_rule &lt;رقم&gt; — امسح قاعدة
/consolidate — تنظيف الذاكرة دلوقتي
/tools — الأدوات المتاحة
/train — يدرّب موديل النوايا على أوامرك (ثواني)
/audit — آخر العمليات
/task &lt;ثواني&gt; &lt;المطلوب&gt; — مهمة مجدولة
/cron &lt;تعبير&gt; &lt;المطلوب&gt; — مهمة بجدول cron (مثال: 0 9 * * *)
/tasks — المهام المجدولة
/del &lt;رقم&gt; — حذف مهمة
/id — رقم المحادثة بتاعك
/help — الرسالة دي

<b>تعلّمني أمر جديد:</b>
<code>/learn الجملة => أمر PowerShell</code>
مثال:
<code>/learn افتح الشغل => start "" "C:\\Work"</code>
<code>/learn قولي حالتك => رد: تمام</code>

أو ابعت طلب عادي زي: <i>افتح يوتيوب</i> — <i>مساحة الديسك</i> — <i>صور الشاشة</i>

<b>عشان أفتكرك:</b>
<code>اسمي عبدالله</code> — <code>بحب القهوة السادة</code> — <code>افتكر إن شغلي بيبدأ 9</code>
واسألني بعدها: <i>انت فاكر ايه عني؟</i>

<b>مسح ومتابعة:</b>
<code>انسى المدينة</code> — <code>كرر</code> — <code>افتحه تاني</code> — <code>وافتح كمان جوجل</code>

<b>قواعد وسلوك:</b>
<code>من دلوقتي ردودك تكون مختصرة</code> — <code>متعملش كذا</code> — <code>المفروض تقولي الأول</code>

<b>مهارات Markdown:</b>
ضيف مجلد في <code>skills/</code> فيه <code>SKILL.md</code> — هيتحمّل تلقائيًا."""


def setup_logging(cfg: Config) -> None:
    cfg.log_path.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    logging.getLogger("httpx").setLevel(logging.WARNING)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)

    file_handler = RotatingFileHandler(
        cfg.log_path, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)


def _duration(seconds: float) -> str:
    seconds = int(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}س {minutes}د"
    if minutes:
        return f"{minutes}د {secs}ث"
    return f"{secs}ث"


class Dispatcher:
    def __init__(self, cfg: Config, agent: Agent, tg: Telegram, memory: Memory) -> None:
        self.cfg = cfg
        self.agent = agent
        self.tg = tg
        self.memory = memory
        self.started_at = time.time()
        self.bot_username = ""

    async def dispatch(self, update: dict[str, Any]) -> None:
        if "callback_query" in update:
            await self._callback(update["callback_query"])
        elif "message" in update:
            await self._message(update["message"])

    async def _callback(self, cq: dict[str, Any]) -> None:
        chat_id = int((cq.get("message") or {}).get("chat", {}).get("id", 0))
        user_id = int((cq.get("from") or {}).get("id", 0))
        if chat_id not in self.cfg.allowed_chat_ids and user_id not in self.cfg.allowed_chat_ids:
            await self.tg.answer_callback(cq.get("id", ""), "غير مصرح")
            return

        action, _, token = str(cq.get("data", "")).partition(":")
        approved = action == "ok"
        ok = self.agent.resolve_approval(token, approved, chat_id)
        await self.tg.answer_callback(cq.get("id", ""), "تم التنفيذ ✅" if approved else "اتلغى ❌")
        if not ok:
            await self.tg.send(chat_id, "الطلب ده انتهت صلاحيته.")

    async def _message(self, message: dict[str, Any]) -> None:
        chat = message.get("chat") or {}
        chat_id = int(chat.get("id", 0))
        text = (message.get("text") or "").strip()

        if chat_id not in self.cfg.allowed_chat_ids:
            log.warning("رفض رسالة من chat_id=%s (%s)", chat_id, chat.get("username"))
            await self.tg.send(chat_id, f"⛔ غير مصرح.\nرقم المحادثة: <code>{chat_id}</code>")
            return

        # أول مرة: خزّن الاسم اللي في تيليجرام عشان يعرفك من غير ما تسأله
        sender = message.get("from") or {}
        first_name = str(sender.get("first_name") or "").strip()
        if first_name and not self.agent.personal.name(chat_id):
            self.memory.save_fact(
                chat_id,
                "الاسم",
                first_name,
                "telegram",
                scalar=True,
                dimension="identity.preferred_name",
                quote=first_name,
                session_id=self.agent.personal.session_id(chat_id),
            )

        if not text:
            await self.tg.send(chat_id, "أنا بفهم النصوص بس دلوقتي (مفيش صوت/صور).")
            return

        if text.startswith("/"):
            command, _, rest = text.partition(" ")
            command = command.split("@")[0].lower()
            rest = rest.strip()
            if await self._command(chat_id, command, rest):
                return

        await self.tg.typing(chat_id)
        asyncio.create_task(self.agent.handle(chat_id, text))

    async def _command(self, chat_id: int, command: str, rest: str) -> bool:
        if command in {"/start", "/help"}:
            name = self.agent.personal.name(chat_id)
            greeting = f"أهلاً يا {name} 👋\n\n" if name else "أهلاً 👋\n\n"
            await self.tg.send(chat_id, greeting + HELP)
        elif command == "/new":
            removed = self.memory.reset(chat_id)
            self.agent.personal.rotate_session(chat_id)
            await self.tg.send(chat_id, f"🧹 بدأنا من جديد (مسحت {removed} رسالة من السياق).")
        elif command == "/status":
            await self.tg.send(
                chat_id,
                self.agent.status(chat_id)
                + f"\nشغّال من: {_duration(time.time() - self.started_at)}"
                + f"\nمهام مجدولة: {len(self.memory.list_tasks(chat_id))}",
            )
        elif command == "/pause":
            self.agent.paused = True
            await self.tg.send(chat_id, "⏸ متوقف. /resume عشان نكمل.")
        elif command == "/resume":
            self.agent.paused = False
            await self.tg.send(chat_id, "▶️ رجعنا للشغل.")
        elif command == "/audit":
            rows = self.memory.recent_audit(10)
            if not rows:
                await self.tg.send(chat_id, "مفيش عمليات لسه.")
            else:
                lines = [
                    f"• {esc(r['tool'])} → {esc(r['decision'])} ({time.strftime('%H:%M', time.localtime(r['created_at']))})"
                    for r in rows
                ]
                await self.tg.send(chat_id, "🧾 <b>آخر العمليات</b>\n" + "\n".join(lines))
        elif command == "/id":
            await self.tg.send(chat_id, f"رقم المحادثة: <code>{chat_id}</code>")
        elif command == "/task":
            parts = rest.split(maxsplit=1)
            if len(parts) < 2 or not parts[0].isdigit():
                await self.tg.send(chat_id, "الصيغة: <code>/task 3600 راجع الإيميل</code>")
            else:
                interval = max(60, int(parts[0]))
                task_id = self.memory.add_task(chat_id, parts[1], interval)
                await self.tg.send(
                    chat_id,
                    f"✅ مهمة #{task_id} اتجدولت كل {_duration(interval)}.\n{esc(parts[1])}",
                )
        elif command == "/cron":
            parts = rest.split(maxsplit=5)
            if len(parts) < 6:
                await self.tg.send(
                    chat_id,
                    "الصيغة: <code>/cron 0 9 * * * راجع الإيميل</code>\n"
                    "الخمسة حقول: دقيقة ساعة يوم-الشهر شهر يوم-الأسبوع",
                )
            else:
                expr = " ".join(parts[:5])
                prompt = parts[5]
                try:
                    from .cron import next_run

                    first = next_run(expr)
                except ValueError as exc:
                    await self.tg.send(chat_id, f"⚠️ تعبير cron غلط: <code>{esc(exc)}</code>")
                else:
                    task_id = self.memory.add_task(
                        chat_id, prompt, 60, cron_expr=expr, next_run=first
                    )
                    await self.tg.send(
                        chat_id,
                        f"✅ مهمة #{task_id} اتجدولت: <code>{esc(expr)}</code>\n"
                        f"أول تشغيل: {time.strftime('%Y-%m-%d %H:%M', time.localtime(first))}\n"
                        f"{esc(prompt)}",
                    )
        elif command == "/tasks":
            tasks = self.memory.list_tasks(chat_id)
            if not tasks:
                await self.tg.send(chat_id, "مفيش مهام مجدولة.")
            else:
                lines = []
                for task in tasks:
                    schedule = (
                        f"<code>{esc(task['cron_expr'])}</code>"
                        if task.get("cron_expr")
                        else f"كل {_duration(task['interval_sec'])}"
                    )
                    lines.append(
                        f"#{task['id']} {schedule} — {esc(task['prompt'][:80])}"
                    )
                await self.tg.send(chat_id, "⏰ <b>المهام</b>\n" + "\n".join(lines))
        elif command == "/del":
            if not rest.isdigit():
                await self.tg.send(chat_id, "الصيغة: <code>/del 3</code>")
            else:
                ok = self.memory.delete_task(chat_id, int(rest))
                await self.tg.send(chat_id, "تم الحذف." if ok else "مفيش مهمة بالرقم ده.")
        elif command == "/whoami":
            await self.tg.send(chat_id, self.agent.status(chat_id))
        elif command in {"/facts", "/عني", "/ذاكرة"}:
            await self.tg.send(chat_id, self.agent.personal.render_profile(chat_id))
        elif command in {"/recall", "/استرجع"}:
            if not rest:
                await self.tg.send(chat_id, "الصيغة: <code>/recall شغلي</code>")
            else:
                await self.tg.send(chat_id, self.agent.personal.recall_reply(chat_id, rest))
        elif command in {"/profile", "/بروفايل"}:
            try:
                path = self.agent.personal.export_profile(chat_id)
                await self.tg.send(
                    chat_id,
                    f"📄 اتكتب بروفايلك هنا:\n<code>{esc(str(path))}</code>",
                )
            except OSError as exc:
                await self.tg.send(chat_id, f"⚠️ مش قادر أكتب الملف: <code>{esc(exc)}</code>")
        elif command in {"/rules", "/قواعد"}:
            rules = self.agent.personal.rules(chat_id)
            if not rules:
                await self.tg.send(
                    chat_id,
                    "🧭 مفيش قواعد لسه.\n"
                    "علّمني: <code>من دلوقتي ردودك تكون مختصرة</code>\n"
                    "أو: <code>متعملش تفتح ملفات من غير إذن</code>",
                )
            else:
                lines = [
                    f"#{row['id']} {esc(row['rule'])} <i>({row['hits']} مرة)</i>"
                    for row in rules
                ]
                await self.tg.send(chat_id, "🧭 <b>قواعد السلوك</b>\n" + "\n".join(lines))
        elif command in {"/forget_rule", "/امسح_قاعدة"}:
            if not rest.isdigit():
                await self.tg.send(chat_id, "الصيغة: <code>/forget_rule 3</code>")
            else:
                ok = self.agent.personal.forget_rule(chat_id, int(rest))
                await self.tg.send(chat_id, "تم مسح القاعدة 🗑" if ok else "مفيش قاعدة بالرقم ده.")
        elif command in {"/consolidate", "/نظف"}:
            result = self.agent.personal.consolidate_all()
            await self.tg.send(
                chat_id,
                "🧹 <b>تنظيف الذاكرة</b>\n"
                f"ترقية: {result['promoted']} — نوم: {result['dormant']} — نسيان: {result['forgotten']}\n"
                f"بروفايلات: {result['profiles']}",
            )
        elif command in {"/tools", "/أدوات"}:
            rows = tools.describe()
            lines = [
                f"• <code>{esc(row['name'])}</code> — {esc(row['description'][:90])}"
                + (" ⚠️" if row["side_effect"] else "")
                for row in rows
            ]
            await self.tg.send(chat_id, f"🛠 <b>الأدوات</b> ({len(rows)})\n" + "\n".join(lines))
        elif command in {"/forget_fact", "/انسى_معلومة"}:
            if not rest.isdigit():
                await self.tg.send(chat_id, "الصيغة: <code>/forget_fact 12</code>")
            else:
                ok = self.agent.personal.forget(chat_id, int(rest))
                await self.tg.send(chat_id, "تم مسح المعلومة 🗑" if ok else "مفيش معلومة بالرقم ده.")
        elif command in {"/learn", "/تعلم"}:
            await self._learn(chat_id, rest)
        elif command in {"/train", "/درب"}:
            await self._train(chat_id)
        elif command in {"/skills", "/مهارات"}:
            await self._skills(chat_id)
        elif command in {"/forget", "/انسى"}:
            if not rest.isdigit():
                await self.tg.send(chat_id, "الصيغة: <code>/forget 3</code>")
            else:
                ok = self.agent.brain.forget(chat_id, int(rest))
                await self.tg.send(chat_id, "تم النسيان 🗑" if ok else "مفيش أمر بالرقم ده.")
        else:
            return False
        return True

    async def _learn(self, chat_id: int, rest: str) -> None:
        if "=>" not in rest:
            await self.tg.send(
                chat_id,
                "🎓 <b>علّمني أمر</b>\n"
                "<code>/learn الجملة => أمر PowerShell</code>\n"
                "أو رد ثابت:\n"
                "<code>/learn الجملة => رد: النص</code>\n\n"
                "مثال:\n"
                '<code>/learn افتح الشغل => start "" "C:\\Work"</code>\n\n'
                "بعد كده لو قلت «افتح الشغل» هينفّذ الأمر فورًا.",
            )
            return

        phrase, _, raw = rest.partition("=>")
        phrase, raw = phrase.strip(), raw.strip()
        if not phrase or not raw:
            await self.tg.send(chat_id, "محتاج جملة وأمر. مثال: <code>/learn افتح الشغل => start \"\" \"C:\\Work\"</code>")
            return

        lowered = raw.lower()
        if lowered.startswith(("رد:", "رد :")):
            action = Action(reply=raw.split(":", 1)[1].strip() or "تمام")
        else:
            action = Action(tool="shell", args={"command": raw})

        intent_id = self.agent.brain.learn(chat_id, phrase, action)
        await self.tg.send(
            chat_id,
            f"✅ اتعلمت الأمر #{intent_id}\n«{esc(phrase)}» → "
            + ("رد ثابت" if action.reply else f"<code>{esc(raw)}</code>")
            + f"\n\nجرّبه: {esc(phrase)}",
        )

    async def _train(self, chat_id: int) -> None:
        await self.tg.send(chat_id, "⏳ بتدريب موديل النوايا على أوامرك...")
        try:
            from .train.train import train_and_save

            model, report = await asyncio.to_thread(train_and_save, self.cfg.intent_model)
        except ImportError:
            await self.tg.send(
                chat_id,
                "❌ محتاج numpy للتدريب:\n"
                "<code>.venv\\Scripts\\pip install numpy</code>",
            )
            return
        except Exception as exc:  # noqa: BLE001
            await self.tg.send(chat_id, f"❌ فشل التدريب: <code>{esc(exc)}</code>")
            return

        self.agent.brain.model = model
        await self.tg.send(
            chat_id,
            "✅ <b>الموديل اتدرب</b>\n"
            f"أمثلة تدريب: {int(report['train_size'])}\n"
            f"دقة الاختبار: {report['test_accuracy']:.1%}\n"
            f"التصنيفات: {int(report['classes'])}\n\n"
            "جرّب صيغة جديدة: «ممكن تفتحلي يوتيوب؟»",
        )

    async def _skills(self, chat_id: int) -> None:
        learned = self.agent.brain.learned(chat_id)
        ready = "، ".join(s.name for s in SKILLS)
        lines = [f"🧠 <b>جاهزة</b>\n{ready}"]
        md_skills = self.agent.brain.md_skills.all()
        if md_skills:
            lines.append("\n📄 <b>مهارات Markdown</b>")
            for skill in md_skills:
                lines.append(
                    f"• <code>{esc(skill.name)}</code> — {esc(skill.description or skill.triggers[0])}"
                )
        if learned:
            lines.append("\n🎓 <b>متعلَّمة</b>")
            for row in learned:
                action = row["action"]
                target = action.get("reply") or (action.get("args") or {}).get("command") or action.get("tool", "")
                lines.append(f"#{row['id']} «{esc(row['phrase'])}» → {esc(str(target)[:60])}")
        else:
            lines.append("\n🎓 لسه متعلّمش حاجة — استخدم /learn")
        lines.append("\n💡 اطلب بالعربي عادي: «صور الشاشة»، «مساحة الديسك»، «افتح يوتيوب»")
        await self.tg.send(chat_id, "\n".join(lines))

    async def run(self) -> None:
        me = await self.tg.get_me()
        self.bot_username = me.get("username", "")
        log.info("البوت شغّال: @%s | الموديل: %s", self.bot_username, self.cfg.llm_model)
        log.info(
            "العقل: %s | موديل النوايا: %s | مجلد العمل: %s",
            self.agent.mode,
            "مدرَّب ✅" if self.agent.brain.model else "مش موجود",
            self.cfg.workspace,
        )

        stop = asyncio.Event()
        scheduler = asyncio.create_task(
            scheduler_loop(self.agent, self.memory, self.tg, stop)
        )

        offset = 0
        try:
            while True:
                try:
                    updates = await self.tg.get_updates(offset)
                except TelegramError as exc:
                    log.warning("getUpdates: %s", exc)
                    await asyncio.sleep(5)
                    continue
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    log.warning("خطأ غير متوقع في الاستقبال: %s", exc)
                    await asyncio.sleep(5)
                    continue

                for update in updates:
                    offset = int(update["update_id"]) + 1
                    try:
                        await self.dispatch(update)
                    except Exception:  # noqa: BLE001
                        log.exception("فشل معالجة update")
        finally:
            stop.set()
            scheduler.cancel()
            try:
                await scheduler
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            tools.browser.shutdown()
            await self.tg.close()


async def doctor(cfg: Config) -> int:
    """فحص سريع للإعدادات قبل التشغيل."""
    ok = True

    def line(status: bool, label: str, detail: str = "") -> None:
        nonlocal ok
        ok = ok and status
        mark = "✅" if status else "❌"
        print(f"{mark} {label}" + (f" — {detail}" if detail else ""))

    print("=" * 60)
    print(f"فحص إعدادات {cfg.agent_name}")
    print("=" * 60)
    line(True, "مجلد العمل", str(cfg.workspace))
    try:
        cfg.workspace.mkdir(parents=True, exist_ok=True)
        probe = cfg.workspace / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        line(True, "الكتابة في مجلد العمل")
    except OSError as exc:
        line(False, "الكتابة في مجلد العمل", str(exc))

    line(bool(cfg.telegram_token), "توكن تيليجرام", cfg.telegram_token[:10] + "…" if cfg.telegram_token else "ناقص")
    line(bool(cfg.allowed_chat_ids), "قائمة المحادثات المسموحة", str(cfg.allowed_chat_ids))

    if cfg.telegram_token:
        tg = Telegram(cfg.telegram_token)
        try:
            me = await tg.get_me()
            line(True, "الاتصال بتيليجرام", f"@{me.get('username')}")
        except TelegramError as exc:
            line(False, "الاتصال بتيليجرام", str(exc))
        finally:
            await tg.close()

    llm = LLM(cfg)
    if cfg.mode == "llm":
        try:
            reply = await llm.ping()
            line(True, "الموديل", f"{cfg.llm_model} → {reply[:40]!r}")
        except LLMError as exc:
            line(False, "الموديل", str(exc)[:200])
    else:
        line(True, "العقل", "rules — قواعد + تعلم (مش محتاج موديل)")

    try:
        import playwright  # noqa: F401

        line(True, "Playwright مثبّت", "فعّله بـ BROWSER_ENABLED=true")
    except ImportError:
        line(True, "Playwright (اختياري)", "مش مثبّت — المتصفح مش هيشتغل")

    if cfg.email_enabled:
        line(True, "الإيميل (اختياري)", "متظبط")
    else:
        print("➖ الإيميل (اختياري) — مش متظبط (مش مشكلة)")

    print("=" * 60)
    print("النتيجة: جاهز للتشغيل ✅" if ok else "النتيجة: فيه مشاكل لازم تتصلح ❌")
    return 0 if ok else 1


async def serve(cfg: Config) -> None:
    setup_logging(cfg)
    cfg.workspace.mkdir(parents=True, exist_ok=True)

    memory = Memory(cfg.db_path)
    llm = LLM(cfg) if cfg.mode == "llm" else None
    tg = Telegram(cfg.telegram_token)
    agent = Agent(cfg, llm, tg, memory)

    rt.cfg = cfg
    rt.memory = memory
    rt.telegram = tg

    dispatcher = Dispatcher(cfg, agent, tg, memory)
    try:
        await dispatcher.run()
    finally:
        memory.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Agent محلي بيتحكم من تيليجرام")
    parser.add_argument("--check", action="store_true", help="فحص الإعدادات والخروج")
    args = parser.parse_args()

    cfg = Config.load()
    if args.check:
        return asyncio.run(doctor(cfg))

    errors = cfg.validate()
    if errors:
        print("⛔ الإعدادات ناقصة:\n")
        for error in errors:
            print(f"  • {error}")
        print("\nانسخ .env.example إلى .env وعدّل القيم، وبعدها جرّب:  py -m agent.main --check")
        return 1

    try:
        asyncio.run(serve(cfg))
    except KeyboardInterrupt:
        print("\nتم الإيقاف.")
    except TelegramError as exc:
        print(f"⛔ تيليجرام رفض الاتصال: {exc}")
        print("   اتأكد من TELEGRAM_BOT_TOKEN، وإن البوت مش متوقف من BotFather.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
