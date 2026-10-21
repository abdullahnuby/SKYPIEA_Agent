"""أدوات النظام: فتح تطبيقات/روابط + سكرين شوت."""

from __future__ import annotations

import re
import subprocess
import webbrowser
from pathlib import Path

from ..aliases import resolve
from ..runtime import rt
from . import tool


@tool(
    "open_target",
    "فتح رابط في المتصفح، أو برنامج، أو ملف، أو مجلد على الجهاز.",
    {
        "type": "object",
        "properties": {
            "target": {"type": "string", "description": "رابط https أو اسم برنامج أو مسار ملف/مجلد."}
        },
        "required": ["target"],
    },
    side_effect=True,
)
def open_target(target: str) -> str:
    target = resolve((target or "").strip().strip('"').strip("'"))
    if not target:
        return "محتاج حاجة أفتحها."

    if target.startswith(("http://", "https://")):
        webbrowser.open(target)
        return f"تم فتح الرابط: {target}"

    cfg = rt.require_cfg()
    candidate = Path(target).expanduser()
    if not candidate.is_absolute():
        candidate = (cfg.workspace / candidate).resolve()

    try:
        if candidate.exists():
            subprocess.Popen(["cmd", "/c", "start", "", str(candidate)])
            return f"تم فتح: {candidate}"
        subprocess.Popen(["cmd", "/c", "start", "", target])
        return f"تم إرسال أمر فتح: {target}"
    except OSError as exc:
        return f"مش قادر أفتح {target}: {exc}"


def _safe_name(name: str) -> str:
    name = re.sub(r"[^\w\-]+", "_", (name or "shot").strip(), flags=re.UNICODE)
    return name[:60] or "shot"


@tool(
    "screenshot",
    "أخذ صورة للشاشة وحفظها في مجلد screenshots.",
    {
        "type": "object",
        "properties": {"name": {"type": "string", "description": "اسم الملف بدون امتداد."}},
    },
    side_effect=True,
)
def screenshot(name: str = "shot") -> str:
    cfg = rt.require_cfg()
    target = cfg.workspace / "screenshots" / f"{_safe_name(name)}.png"
    target.parent.mkdir(parents=True, exist_ok=True)

    script = (
        "Add-Type -AssemblyName System.Windows.Forms,System.Drawing; "
        "$b=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds; "
        "$bmp=New-Object System.Drawing.Bitmap $b.Width,$b.Height; "
        "$g=[System.Drawing.Graphics]::FromImage($bmp); "
        "$g.CopyFromScreen($b.Location,[System.Drawing.Point]::Empty,$b.Size); "
        f"$bmp.Save('{str(target).replace(chr(39), chr(39) * 2)}'); "
        "$g.Dispose(); $bmp.Dispose()"
    )

    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        return "السكرين شوت خد وقت أطول من اللازم."

    if target.exists() and target.stat().st_size > 0:
        return f"تم الحفظ: {target}"
    return f"فشل أخذ السكرين شوت. {proc.stderr.strip()[:300]}"
