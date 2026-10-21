"""مهام مجدولة — الـ agent يشتغل لوحده كل فترة ويبعتلك النتيجة."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from .core import Agent
from .cron import next_run
from .memory import Memory
from .telegram import Telegram, esc

log = logging.getLogger("scheduler")


async def _run_task(agent: Agent, tg: Telegram, task: dict[str, Any]) -> None:
    chat_id = int(task["chat_id"])
    try:
        await tg.send(
            chat_id,
            f"⏰ <b>مهمة مجدولة #{task['id']}</b>\n{esc(task['prompt'])}",
        )
        await agent.handle(
            chat_id,
            f"[مهمة مجدولة تلقائيًا #{task['id']}] {task['prompt']}\n"
            "نفّذها لوحدك باستخدام الأدوات الآمنة، ولخّص النتيجة في النهاية.",
            autonomous=True,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("scheduled task failed")
        try:
            await tg.send(chat_id, f"⚠️ فشلت المهمة #{task['id']}: {esc(exc)}")
        except Exception:  # noqa: BLE001
            pass


async def scheduler_loop(
    agent: Agent,
    memory: Memory,
    tg: Telegram,
    stop: asyncio.Event,
    interval: int = 15,
) -> None:
    log.info("scheduler started")
    last_consolidation = 0.0
    while not stop.is_set():
        try:
            for task in memory.due_tasks():
                nxt = None
                cron_expr = str(task.get("cron_expr") or "")
                if cron_expr:
                    try:
                        nxt = next_run(cron_expr)
                    except ValueError:
                        log.warning("cron غير صالح للمهمة #%s: %s", task["id"], cron_expr)
                memory.mark_task_run(int(task["id"]), int(task["interval_sec"]), next_run=nxt)
                asyncio.create_task(_run_task(agent, tg, task))

            # تنظيف الذاكرة اليومي: ترقية المرصود + تقادم القديم + تصدير البروفايل
            if asyncio.get_running_loop().time() - last_consolidation > 3600:
                last_consolidation = asyncio.get_running_loop().time()
                try:
                    result = await asyncio.to_thread(agent.personal.consolidate_all)
                    if any(result.values()):
                        log.info("memory consolidation: %s", result)
                except Exception:  # noqa: BLE001
                    log.exception("memory consolidation failed")
        except Exception:  # noqa: BLE001
            log.exception("scheduler tick failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
    log.info("scheduler stopped")
