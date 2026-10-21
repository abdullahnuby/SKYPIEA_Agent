"""أداة تنفيذ أوامر PowerShell مع مهلة وحد أعلى للمخرجات."""

from __future__ import annotations

import subprocess
from pathlib import Path

from ..runtime import rt
from . import tool, truncate

PARAMS = {
    "type": "object",
    "properties": {
        "command": {
            "type": "string",
            "description": "أمر PowerShell كامل. استخدمه للأوامر والتثبيت فقط، وليس لقراءة الملفات (فيه أدوات مخصصة).",
        },
        "cwd": {
            "type": "string",
            "description": "مجلد التنفيذ داخل مساحة العمل (افتراضي: جذر مساحة العمل).",
        },
        "timeout": {
            "type": "integer",
            "description": "المهلة بالثواني (5 إلى 600).",
        },
    },
    "required": ["command"],
}


@tool(
    "shell",
    "تنفيذ أمر PowerShell على الجهاز. بيرجع stdout و stderr ورمز الخروج.",
    PARAMS,
    side_effect=True,
)
def shell(command: str, cwd: str = ".", timeout: int = 120) -> str:
    cfg = rt.require_cfg()

    raw = Path(cwd or ".")
    workdir = raw if raw.is_absolute() else (cfg.workspace / raw)
    workdir = workdir.resolve()
    if not workdir.is_dir():
        workdir = cfg.workspace

    limit = max(5, min(int(timeout or cfg.shell_timeout), 600))
    # تأكيد إن مخرجات PowerShell تطلع UTF-8 (عشان العربي مايتلخبطش)
    script = (
        "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;"
        "$OutputEncoding=[System.Text.Encoding]::UTF8;"
        + command
    )

    try:
        proc = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            cwd=str(workdir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=limit,
        )
    except subprocess.TimeoutExpired:
        return f"انتهت المهلة ({limit} ثانية) — الأمر لسه شغال واتوقف."
    except FileNotFoundError:
        return "خطأ: PowerShell غير موجود في PATH."

    parts = []
    if proc.stdout and proc.stdout.strip():
        parts.append(proc.stdout.strip())
    if proc.stderr and proc.stderr.strip():
        parts.append("[stderr]\n" + proc.stderr.strip())
    parts.append(f"[exit code: {proc.returncode}]")

    return truncate("\n".join(parts))
