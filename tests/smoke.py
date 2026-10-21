"""اختبار سريع بدون شبكة: الأدوات + السياسة + الذاكرة."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import tools  # noqa: E402
from agent.config import Config  # noqa: E402
from agent.memory import Memory  # noqa: E402
from agent.policy import Decision, Policy  # noqa: E402
from agent.runtime import rt  # noqa: E402


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="agent-test-"))
    cfg = Config.load()
    object.__setattr__(cfg, "workspace", tmp)
    object.__setattr__(cfg, "db_path", tmp / "test.db")
    rt.cfg = cfg

    failures: list[str] = []

    def check(condition: bool, label: str) -> None:
        print(("✅ " if condition else "❌ ") + label)
        if not condition:
            failures.append(label)

    # الأدوات مسجلة
    check(len(tools.available()) >= 12, f"عدد الأدوات = {len(tools.available())}")

    # الملفات
    import asyncio

    out = asyncio.run(tools.run("write_file", {"path": "notes/test.txt", "content": "مرحبا"}))
    check("تمت الكتابة" in out, "write_file")
    out = asyncio.run(tools.run("read_file", {"path": "notes/test.txt"}))
    check(out == "مرحبا", "read_file")
    out = asyncio.run(tools.run("list_dir", {"path": "notes"}))
    check("test.txt" in out, "list_dir")
    out = asyncio.run(tools.run("find_files", {"pattern": "**/*.txt"}))
    check("notes" in out, "find_files")

    # shell
    out = asyncio.run(tools.run("shell", {"command": "Write-Output hi"}))
    check("hi" in out, "shell")

    # السياسة
    policy = Policy(tmp, "ask")
    check(policy.check("shell", {"command": "dir"}).decision is Decision.ALLOW, "سياسة: dir مسموح")
    check(policy.check("shell", {"command": "npm install"}).decision is Decision.ASK, "سياسة: npm يسأل")
    check(
        policy.check("shell", {"command": "format c:"}).decision is Decision.DENY,
        "سياسة: format مرفوض",
    )
    check(
        policy.check("write_file", {"path": "C:/Windows/x.txt"}).decision is Decision.ASK,
        "سياسة: الكتابة خارج المجلد تسأل",
    )
    check(
        policy.check("read_file", {"path": "notes/test.txt"}).decision is Decision.ALLOW,
        "سياسة: قراءة داخل المجلد مسموحة",
    )

    # الذاكرة
    mem = Memory(tmp / "test.db")
    mem.add_message(1, {"role": "user", "content": "أهلا"})
    mem.add_message(1, {"role": "assistant", "content": "أهلاً بيك"})
    history = mem.history(1)
    check(len(history) == 2 and history[1]["content"] == "أهلاً بيك", "history")
    task_id = mem.add_task(1, "اختبر", 60)
    check(len(mem.list_tasks(1)) == 1, "add_task")
    check(mem.delete_task(1, task_id), "delete_task")
    mem.close()

    print()
    if failures:
        print(f"فشل {len(failures)} اختبار")
        return 1
    print("كل الاختبارات نجحت ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
