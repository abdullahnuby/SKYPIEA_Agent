"""اختبار حلقة الـ Agent بموديل وهمي — بدون شبكة."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.config import Config  # noqa: E402
from agent.core import Agent  # noqa: E402
from agent.memory import Memory  # noqa: E402
from agent.policy import Decision, Policy  # noqa: E402
from agent.runtime import rt  # noqa: E402


class FakeLLM:
    """بيرد بخطوتين: استدعاء أداة، وبعدها تأكيد."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.calls = 0

    async def chat(self, messages, tools=None, timeout=180):
        self.calls += 1
        if self.calls == 1:
            return {
                "role": "assistant",
                "content": "هكتب الملف.",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "write_file",
                            "arguments": f'{{"path": "{self.path}", "content": "مرحبا"}}',
                        },
                    }
                ],
            }
        tool_msgs = [m for m in messages if m.get("role") == "tool"]
        return {
            "role": "assistant",
            "content": "خلصت. نتيجة الأداة: " + (tool_msgs[-1]["content"] if tool_msgs else "لا شيء"),
        }


class FakeTelegram:
    """بيسجّل الرسايل، وبيوافق تلقائيًا على أي طلب موافقة."""

    def __init__(self) -> None:
        self.sent: list[str] = []
        self.approvals = 0
        self.agent: Agent | None = None

    async def send(self, chat_id, text, keyboard=None):
        self.sent.append(text)
        if keyboard and self.agent is not None:
            token = keyboard["inline_keyboard"][0][0]["callback_data"].split(":", 1)[1]
            self.approvals += 1
            self.agent.resolve_approval(token, True, chat_id)

    async def typing(self, chat_id):
        pass


async def scenario(tmp: Path, mode: str, filename: str) -> tuple[FakeTelegram, FakeLLM, Memory, list[dict]]:
    cfg = Config.load()
    object.__setattr__(cfg, "workspace", tmp)
    object.__setattr__(cfg, "db_path", tmp / "agent.db")
    object.__setattr__(cfg, "approval_mode", mode)
    object.__setattr__(cfg, "agent_mode", "llm")
    object.__setattr__(cfg, "max_steps", 5)
    rt.cfg = cfg

    memory = Memory(tmp / "agent.db")
    tg = FakeTelegram()
    llm = FakeLLM(f"out/{filename}")
    agent = Agent(cfg, llm, tg, memory)
    tg.agent = agent

    await asyncio.wait_for(agent.handle(42, "اعمل ملف"), timeout=20)
    history = memory.history(42)
    audit = memory.recent_audit(5)
    return tg, llm, memory, [{"history": history, "audit": audit}]


async def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="agent-loop-"))
    checks: list[tuple[bool, str]] = []

    # 1) وضع ask: لازم يطلب موافقة
    tg, llm, memory, _ = await scenario(tmp, "ask", "a.txt")
    checks += [
        ((tmp / "out" / "a.txt").read_text(encoding="utf-8") == "مرحبا", "وضع ask: الملف اتكتب"),
        (tg.approvals == 1, "وضع ask: طلب موافقة واحدة"),
        (llm.calls == 2, "الموديل اتنادى مرتين (أداة + خلاص)"),
        (any("خلصت" in s for s in tg.sent), "الرد النهائي اتشر"),
        (any(m.get("role") == "tool" for m in memory.history(42)), "نتيجة الأداة اتخزنت"),
    ]

    # 2) وضع auto: من غير موافقة
    tg2, _, memory2, _ = await scenario(tmp, "auto", "b.txt")
    checks += [
        ((tmp / "out" / "b.txt").exists(), "وضع auto: الملف اتكتب"),
        (tg2.approvals == 0, "وضع auto: مفيش موافقات"),
    ]

    # 3) الرفض المطلق شغال حتى في auto
    policy = Policy(tmp, "auto")
    checks.append(
        (policy.check("shell", {"command": "format c:"}).decision is Decision.DENY, "auto: format مرفوض")
    )
    checks.append(
        (policy.check("shell", {"command": "npm install"}).decision is Decision.ALLOW, "auto: npm مسموح")
    )

    memory.close()
    memory2.close()

    failed = 0
    for ok, label in checks:
        print(("✅ " if ok else "❌ ") + label)
        failed += 0 if ok else 1

    print()
    print("كل الاختبارات نجحت ✅" if not failed else f"فشل {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
