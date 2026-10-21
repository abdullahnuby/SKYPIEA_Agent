"""حلقة الـ Agent: موديل ← أدوات ← نتيجة ← موديل."""

from __future__ import annotations

import asyncio
import json
import platform
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any

from . import tools
from .brain import Action, Brain
from .config import Config
from .llm import LLM, LLMError
from .loop_control import LoopGuard, finalize_suffix, reflection_message
from .memory import Memory
from .personal import Personal
from .policy import Decision, Policy
from .telegram import Telegram, esc


def build_system_prompt(cfg: Config) -> str:
    today = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""أنت {cfg.agent_name}، مساعد ذكي شغّال مباشرة على جهاز المستخدم.

بيئة التشغيل:
- نظام التشغيل: {platform.system()} {platform.release()}
- مجلد العمل: {cfg.workspace}
- التاريخ: {today}
- الأدوات المتاحة: {', '.join(tools.available())}

قواعد صارمة:
1. استخدم الأدوات لتنفيذ أي شيء فعلي. ممنوع تقول إنك عملت حاجة من غير استدعاء أداة فعلية.
2. مسارات الملفات نسبية لمجلد العمل إلا لو المستخدم حدد مسار مطلق.
3. لو أداة رجّعت خطأ، اقرأ الخطأ وحاول تصلحه (مرة أو مرتين) قبل ما تستسلم.
4. أي عملية خطيرة بيطلبها النظام تلقائيًا — اشرح باختصار إيه اللي هتعمله قبلها.
5. متخترعش نتائج أو معلومات. لو مش متأكد، دوّر (search_web / fetch_url) أو اسأل المستخدم.
6. الردود قصيرة وواضحة، بنفس لغة المستخدم (عربي افتراضيًا)، وبتنسيق تيليجرام.
7. لو المهمة طويلة، قسّمها خطوات ونفّذها بالترتيب.
8. الإيميلات والرسائل: متبعتش أي حاجة من غير طلب صريح من المستخدم."""


class Agent:
    def __init__(self, cfg: Config, llm: LLM | None, tg: Telegram, memory: Memory) -> None:
        self.cfg = cfg
        self.llm = llm
        self.tg = tg
        self.memory = memory
        self.personal = Personal(memory)
        self.personal.backfill_dimensions()
        self.brain = Brain(memory, cfg.intent_model)
        self.mode = cfg.mode
        self.policy = Policy(cfg.workspace, cfg.approval_mode)
        self._locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._pending: dict[str, tuple[asyncio.Future, int]] = {}
        self.paused = False

    # ------------------------------------------------------------
    # الواجهة
    # ------------------------------------------------------------
    async def handle(self, chat_id: int, text: str, autonomous: bool = False) -> None:
        async with self._locks[chat_id]:
            try:
                if self.mode == "rules":
                    await self._handle_rules(chat_id, text)
                else:
                    await self._run(chat_id, text, autonomous)
            except LLMError as exc:
                await self.tg.send(chat_id, f"⚠️ مشكلة في الموديل:\n<code>{esc(exc)}</code>")
            except Exception as exc:  # noqa: BLE001
                await self.tg.send(chat_id, f"⚠️ خطأ غير متوقع: <code>{esc(type(exc).__name__)}: {esc(exc)}</code>")

    def resolve_approval(self, token: str, approved: bool, chat_id: int) -> bool:
        item = self._pending.get(token)
        if not item:
            return False
        future, owner = item
        if owner != chat_id:
            return False
        if not future.done():
            future.set_result(approved)
        return True

    # ------------------------------------------------------------
    # الحلقة الأساسية
    # ------------------------------------------------------------
    async def _run(self, chat_id: int, text: str, autonomous: bool) -> None:
        if self.paused:
            await self.tg.send(chat_id, "⏸ متوقف مؤقتًا. ابعت /resume عشان نكمل.")
            return

        self.memory.add_message(chat_id, {"role": "user", "content": text})
        self.personal.observe(chat_id, text)
        system_prompt = build_system_prompt(self.cfg)
        facts_block = self.personal.prompt_block(chat_id, query=text)
        if facts_block:
            system_prompt += "\n\n" + facts_block
        learned = self.brain.learned(chat_id)[:15]
        if learned:
            lines = "\n".join(f"- «{row['phrase']}» → {json.dumps(row['action'], ensure_ascii=False)}" for row in learned)
            system_prompt += f"\n\nأوامر علّمها المستخدم (نفّذها عند مطابقة الطلب):\n{lines}"
        history: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt}
        ] + self.memory.history(chat_id, self.cfg.max_history)

        await self.tg.typing(chat_id)
        guard = LoopGuard()

        for step in range(self.cfg.max_steps):
            if self.paused:
                await self.tg.send(chat_id, "⏸ اتوقفنا بناءً على طلبك.")
                return

            message = await self.llm.chat(history, tools.definitions())
            content = (message.get("content") or "").strip()
            calls = message.get("tool_calls") or []

            if content:
                await self.tg.send(chat_id, content)

            self.memory.add_message(chat_id, message)
            history.append(message)

            if not calls:
                return

            results: list[str] = []
            for call in calls:
                name = (call.get("function") or {}).get("name", "")
                raw_args = (call.get("function") or {}).get("arguments") or "{}"
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
                except (ValueError, TypeError):
                    args = {}

                result = await self._execute(chat_id, name, args, autonomous)
                results.append(result)
                tool_message = {
                    "role": "tool",
                    "tool_call_id": call.get("id", ""),
                    "content": result,
                }
                self.memory.add_message(chat_id, tool_message)
                history.append(tool_message)

            guard.record(calls, results)
            if guard.stuck():
                if guard.exhausted():
                    history.append({"role": "system", "content": finalize_suffix()})
                    final = await self.llm.chat(history, tools=None)
                    text_out = (final.get("content") or "").strip()
                    if text_out:
                        await self.tg.send(chat_id, self.personal.personalize(chat_id, text_out))
                        self.memory.add_message(
                            chat_id, {"role": "assistant", "content": text_out}
                        )
                    return
                guard.mark_reflected()
                history.append(
                    {
                        "role": "system",
                        "content": reflection_message(guard, results[-1] if results else ""),
                    }
                )
            await self.tg.typing(chat_id)

        await self.tg.send(
            chat_id,
            f"⚠️ وصلت للحد الأقصى ({self.cfg.max_steps} خطوة). ابعت «كمل» عشان نكمل من مكاننا.",
        )

    async def _execute(self, chat_id: int, name: str, args: dict, autonomous: bool) -> str:
        verdict = self.policy.check(name, args)
        approved = True
        note = ""

        if verdict.decision is Decision.DENY:
            approved = False
            note = f"مرفوض تلقائيًا: {verdict.reason}"
        elif verdict.decision is Decision.ASK:
            if autonomous:
                approved = False
                note = "مرفوض: المهمة المجدولة مش مسموح لها تنفّذ عملية محتاجة موافقة."
            else:
                approved = await self._ask_approval(chat_id, name, args, verdict.reason)
                note = "" if approved else "المستخدم رفض التنفيذ."

        if not approved:
            result = f"⛔ {note}"
        else:
            result = await tools.run(name, args)

        self.memory.audit(chat_id, name, args, verdict.decision.value + ("/ok" if approved else "/blocked"), result)
        return result

    # ------------------------------------------------------------
    # وضع القواعد (بدون LLM)
    # ------------------------------------------------------------
    async def _handle_rules(self, chat_id: int, text: str) -> None:
        if self.paused:
            await self.tg.send(chat_id, "⏸ متوقف مؤقتًا. ابعت /resume عشان نكمل.")
            return

        self.memory.add_message(chat_id, {"role": "user", "content": text})

        # سياق قصير المدى: «كرر»، «افتحه تاني»، «وافتح كمان ...»
        text, followup = self.personal.plan(chat_id, text)
        if followup is not None:
            action = Action.from_dict(followup)
        else:
            action = self.brain.think(chat_id, text)

        # الذاكرة الشخصية: حفظ/استرجاع معلومات المستخدم
        personal_reply = self.personal.handle(chat_id, text, is_command=action is not None)
        if personal_reply:
            await self.tg.send(chat_id, personal_reply)
            self.memory.add_message(chat_id, {"role": "assistant", "content": personal_reply})
            return

        if action is None:
            self.memory.add_message(chat_id, {"role": "assistant", "content": "(مش فاهم)"})
            await self.tg.send(
                chat_id,
                "🤔 مش فاهم الطلب ده.\n\n"
                "• <b>/skills</b> — اللي بعرفه\n"
                '• <b>/learn</b> الجملة => الأمر — علّمني حاجة جديدة\n'
                "• <b>افتكر إن ...</b> — خزّن معلومة عنك\n"
                "مثال:\n<code>/learn افتح الشغل => start \"\" \"C:\\Work\"</code>",
            )
            return

        if action.reply:
            action.reply = self.personal.personalize(chat_id, action.reply)

        await self._run_action(chat_id, action)

    async def _run_action(self, chat_id: int, action: Any) -> None:
        if action.tool or action.reply:
            self.personal.remember_action(chat_id, action.to_dict())

        if action.reply:
            await self.tg.send(chat_id, action.reply)
            self.memory.add_message(chat_id, {"role": "assistant", "content": action.reply})

        if not action.tool:
            return

        result = await self._execute(chat_id, action.tool, action.args, autonomous=False)

        if action.tool == "screenshot" and result.startswith("تم الحفظ:"):
            path = result.split(":", 1)[1].strip()
            if await self.tg.send_photo(chat_id, path, "📸 الشاشة"):
                self.memory.add_message(chat_id, {"role": "assistant", "content": f"(صورة شاشة: {path})"})
                return

        await self.tg.send(chat_id, f"<pre>{esc(result)}</pre>")

    # ------------------------------------------------------------
    # الموافقات
    # ------------------------------------------------------------
    async def _ask_approval(self, chat_id: int, name: str, args: dict, reason: str) -> bool:
        token = uuid.uuid4().hex[:10]
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[token] = (future, chat_id)

        preview = json.dumps(args, ensure_ascii=False, indent=2)
        if len(preview) > 1200:
            preview = preview[:1200] + "\n..."

        text = (
            "⚠️ <b>موافقة مطلوبة</b>\n"
            f"الأداة: <code>{esc(name)}</code>\n"
            f"السبب: {esc(reason)}\n\n"
            f"<pre>{esc(preview)}</pre>"
        )
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "✅ تنفيذ", "callback_data": f"ok:{token}"},
                    {"text": "❌ إلغاء", "callback_data": f"no:{token}"},
                ]
            ]
        }

        try:
            await self.tg.send(chat_id, text, keyboard)
            return await asyncio.wait_for(future, timeout=self.cfg.approval_timeout)
        except asyncio.TimeoutError:
            await self.tg.send(chat_id, "⌛ انتهت مدة الموافقة — اتلغت العملية.")
            return False
        finally:
            self._pending.pop(token, None)

    # ------------------------------------------------------------
    # حالة
    # ------------------------------------------------------------
    def status(self, chat_id: int | None = None) -> str:
        learned = len(self.brain.learned(chat_id)) if chat_id is not None else 0
        facts = self.memory.count_facts(chat_id) if chat_id is not None else 0
        rules = len(self.personal.rules(chat_id)) if chat_id is not None else 0
        md_skills = len(self.brain.md_skills.all())
        name = self.personal.name(chat_id) if chat_id is not None else None
        brain = "🤖 موديل LLM" if self.mode == "llm" else "🧠 قواعد + تعلم"
        return (
            f"🤖 <b>{esc(self.cfg.agent_name)}</b>\n"
            f"العقل: {brain}\n"
            f"الموديل: <code>{esc(self.cfg.llm_model)}</code>\n"
            f"مجلد العمل: <code>{esc(self.cfg.workspace)}</code>\n"
            f"وضع الموافقة: <code>{esc(self.cfg.approval_mode)}</code>\n"
            f"أوامر متعلَّمة: {learned}\n"
            f"قواعد سلوك: {rules} — مهارات Markdown: {md_skills}\n"
            f"موديل النوايا: {'✅ مدرَّب' if self.brain.model else '— مش موجود'}\n"
            f"الذاكرة: {facts} معلومة" + (f" — بيعرفك كـ {esc(name)}" if name else "") + "\n"
            f"الحالة: {'⏸ متوقف' if self.paused else '▶️ شغّال'}\n"
            f"أدوات: {len(tools.TOOLS)}"
        )
