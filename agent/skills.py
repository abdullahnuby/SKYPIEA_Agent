"""مكتبة المهارات الجاهزة — أوامر عربية مربوطة بأدوات حقيقية."""

from __future__ import annotations

import re
from datetime import datetime

from .brain import SKILLS, Action, safe_calc, skill
from .text import clean_phrase

AR_DAYS = ("الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد")


def _clean(raw: str) -> str:
    """تنظيف اسم هدف/استعلام جاي من نص متطبع."""
    text = clean_phrase((raw or "").strip())
    text = re.sub(r"^(?:لي|لى)\s+", "", text)
    text = re.sub(r"^(?:كمان|كذلك|برضه|برضو)\s+", "", text)
    return text.strip('"\' ').strip()


def _query(raw: str) -> str:
    text = (raw or "").strip()
    text = re.sub(r"^(?:لي|لى)\s+", "", text)
    text = re.sub(r"^(?:عن|على|علي)\s+", "", text)
    return _clean(text)


@skill("greet", (r"^(السلام عليكم|سلام عليكم|سلام|اهلا|اهلاً|هاي|هلا|مرحبا|صباح الخير|مساء الخير)(\s|$)",), "تحية")
def _greet(match: re.Match) -> Action:
    return Action(reply="أهلاً 👋 أنا شغّال وجاهز. اكتب /skills تشوف اللي بعرفه، أو /help.")


@skill("who", (r"(انت مين|مين انت|اسمك ايه|who are you)",), "تعريف بالنفس")
def _who(match: re.Match) -> Action:
    return Action(
        reply=(
            "أنا agent شغّال على جهازك 🖥\n"
            "عقلي مكتبة مهارات بتتعلم منك — مش موديل لغوي.\n"
            "أوامري: ملفات، أوامر PowerShell، مواقع، إيميل، متصفح، سكرين شوت."
        )
    )


@skill(
    "time",
    (
        r"^(?:الساعه|الوقت)(?:\s*(?:كام|الان|دلوقتي|بكام|ايه|دلوقت))*$",
        r"^كم\s+(?:الساعه|الوقت)$",
    ),
    "الساعة",
)
def _time(match: re.Match) -> Action:
    now = datetime.now()
    return Action(reply=f"🕐 {now.strftime('%H:%M')} — {AR_DAYS[now.weekday()]}")


@skill(
    "date",
    (
        r"^(?:تاريخ\s+(?:النهارده|اليوم)|التاريخ|النهارده\s+كام|تاريخ\s+كام|تاريخ\s+اليوم\s+ايه|تاريخ\s+اليوم)$",
    ),
    "التاريخ",
)
def _date(match: re.Match) -> Action:
    now = datetime.now()
    return Action(reply=f"📅 {now.strftime('%Y-%m-%d')} — {AR_DAYS[now.weekday()]}")


@skill("help", (r"^(مساعده|مساعدة|help|بتعرف تعمل ايه|تقدر تعمل ايه)$",), "المساعدة")
def _help(match: re.Match) -> Action:
    return Action(
        reply=(
            "🧠 <b>اللي بعرفه</b>\n"
            "• افتح [رابط/برنامج/مجلد]\n"
            "• ابحث عن [حاجة]\n"
            "• اقرا ملف [مسار] / اكتب ملف [مسار] فيه [محتوى]\n"
            "• ايه الملفات في [مجلد] / دور على ملف [نمط]\n"
            "• اعمل مجلد [اسم]\n"
            "• صور الشاشة\n"
            "• اقفل الجهاز\n"
            "• مساحة الديسك / الرام / العمليات / البطارية / الـ IP\n"
            "• الاخبار / احسب [تعبير]\n\n"
            "🎓 علّمني حاجة جديدة:\n"
            "<code>/learn افتح الشغل => start \"\" \"C:\\Work\"</code>"
        )
    )


@skill("open", (r"^(افتح|افتحلي|تفتحلي|تفتح|شغل|شغلي(?!\s+في(?:\s|$))|تشغلي|تشغل|open)\s+(.+)",), "فتح رابط/برنامج")
def _open(match: re.Match) -> Action:
    return Action(tool="open_target", args={"target": _clean(match.group(2))})


@skill(
    "find",
    (r"^(?:دور|ابحث)\s+علي?\s+ملف\s+(.+)", r"^(?:فين|هات)\s+ملف\s+(.+)"),
    "البحث عن ملف",
)
def _find(match: re.Match) -> Action:
    return Action(tool="find_files", args={"pattern": _clean(match.group(1))})


@skill("search", (r"^(ابحثلي|ابحث|تبحثلي|تبحث|دور|تدور|بحث|سيرش|search)\s+(عن\s+|علي\s+)?(.+)",), "بحث في الويب")
def _search(match: re.Match) -> Action:
    raw = match.group(3)
    # «ابحثلي عن X» / «بحث لي عن X»: الفعل نفسه فيه لي
    raw = re.sub(r"^(?:لي|لى)\s+", "", raw)
    return Action(tool="search_web", args={"query": _query(raw)})


@skill("list", (r"^(ايه|اعرض|وريني)\s+(الملفات|محتويات)\s+(في\s+)?(.+)",), "سرد ملفات")
def _list(match: re.Match) -> Action:
    path = re.sub(r"^(?:المجلد|مجلد|فولدر)\s+", "", match.group(4).strip())
    return Action(tool="list_dir", args={"path": _clean(path) or "."})


@skill("read", (r"^(اقرا|اقرأ)\s+(ملف\s+)?(.+)",), "قراءة ملف")
def _read(match: re.Match) -> Action:
    path = match.group(3).strip()
    return Action(tool="read_file", args={"path": _clean(re.sub(r"^(?:لي|لى)\s+", "", path))})


@skill(
    "write",
    (r"^(اكتب|انشئ|انشي|اعمل)\s+ملف\s+(.+?)\s+(فيه|بمحتوي|بمحتوى|محتواه)\s+(.+)",),
    "كتابة ملف",
)
def _write(match: re.Match) -> Action:
    return Action(
        tool="write_file",
        args={"path": _clean(match.group(2)), "content": match.group(4).strip()},
    )


@skill("mkdir", (r"^(اعمل|انشئ|انشي|انشأ)\s+(مجلد|فولدر)\s+(.+)",), "إنشاء مجلد")
def _mkdir(match: re.Match) -> Action:
    name = _clean(match.group(3))
    return Action(
        tool="shell",
        args={"command": f'New-Item -ItemType Directory -Force -Path "{name}" | Out-Null; "تم إنشاء: {name}"'},
    )


@skill("screenshot", (r"^(صور|خد)\s*(سكرين شوت|سكرين|الشاشه|شاشه)$", r"^سكرين شوت$"), "سكرين شوت")
def _screenshot(match: re.Match) -> Action:
    return Action(tool="screenshot", args={"name": datetime.now().strftime("shot_%H%M%S")})


@skill("lock", (r"^(اقفل|قفل)\s+(الجهاز|الشاشه|الكمبيوتر)$",), "قفل الجهاز")
def _lock(match: re.Match) -> Action:
    return Action(
        tool="shell",
        args={"command": 'rundll32.exe user32.dll,LockWorkStation; "تم قفل الجهاز"'},
    )


@skill(
    "disk",
    (r"^(?:مساحة|مساحه)\s+(?:القرص|الديسك|الهارت|الهارد)$", r"^المساحه الفاضيه$"),
    "مساحة القرص",
)
def _disk(match: re.Match) -> Action:
    return Action(
        tool="shell",
        args={
            "command": (
                "Get-PSDrive -PSProvider FileSystem | "
                "Select-Object Name,"
                "@{n='FreeGB';e={[math]::Round($_.Free/1GB,1)}},"
                "@{n='UsedGB';e={[math]::Round($_.Used/1GB,1)}} | "
                "Format-Table -AutoSize"
            )
        },
    )


@skill("ram", (r"(الرام|الرامات|(?<![\w])رام(?![\w])|الذاكره العشواييه|\bram\b|\bmemory\b)",), "الذاكرة")
def _ram(match: re.Match) -> Action:
    return Action(
        tool="shell",
        args={
            "command": (
                "$os=Get-CimInstance Win32_OperatingSystem; "
                "'RAM كلية: {0:N1} GB | مستخدمة: {1:N1} GB | متاحة: {2:N1} GB' -f "
                "($os.TotalVisibleMemorySize/1MB), "
                "(($os.TotalVisibleMemorySize-$os.FreePhysicalMemory)/1MB), "
                "($os.FreePhysicalMemory/1MB)"
            )
        },
    )


@skill("procs", (r"(العمليات|البروسيس|التطبيقات الشغاله)", r"^ايه شغال$"), "العمليات")
def _procs(match: re.Match) -> Action:
    return Action(
        tool="shell",
        args={
            "command": (
                "Get-Process | Sort-Object CPU -Descending | Select-Object -First 8 "
                "Name,CPU,@{n='RAM_MB';e={[math]::Round($_.WorkingSet64/1MB)}} | "
                "Format-Table -AutoSize"
            )
        },
    )


@skill("battery", (r"(البطاريه|نسبه الشحن|نسبة الشحن|الشحن كام|\bbattery\b)",), "البطارية")
def _battery(match: re.Match) -> Action:
    return Action(
        tool="shell",
        args={
            "command": (
                "Get-CimInstance Win32_Battery | "
                "Select-Object EstimatedChargeRemaining,BatteryStatus | Format-List"
            )
        },
    )


@skill(
    "ip",
    (
        r"^(?:ايه|كام|قولي|هات)?\s*(?:ال\s*)?(?:اي\s*بي|ip)(?:\s+بتاعي)?$",
        r"^عنوان\s+(?:ال)?(?:اي\s*بي|ip|الشبكه)$",
        r"^(?:الواي\s*فاي|الشبكه|النت)$",
        r"^الواي\s*فاي\s+(?:شغال|شغاله|واصل|فيه)$",
    ),
    "عنوان الشبكة",
)
def _ip(match: re.Match) -> Action:
    return Action(
        tool="shell",
        args={
            "command": (
                "Get-NetIPAddress -AddressFamily IPv4 | "
                "Where-Object {$_.IPAddress -ne '127.0.0.1'} | "
                "Select-Object IPAddress,InterfaceAlias | Format-Table -AutoSize"
            )
        },
    )


@skill(
    "news",
    (r"^(?:ايه|قولي|هات|وريني)?\s*(?:الاخبار|اخبار اليوم)$",),
    "الأخبار",
)
def _news(match: re.Match) -> Action:
    return Action(tool="search_web", args={"query": "أخبار اليوم", "limit": 5})


@skill(
    "calc",
    (
        r"^(?:ممكن\s+)?(?:احسبلي|احسب\s+لي|احسب|تحسبلي|تحسب|كم\s+يساوي|كام\s+يساوي|كام|كم)\s+(.+)$",
    ),
    "حساب",
)
def _calc(match: re.Match) -> Action:
    expression = match.group(1).strip()
    expression = re.sub(r"^(?:لي|لى)\s+", "", expression)
    return Action(reply=safe_calc(clean_phrase(expression)))


# ترتيب المطابقة: الأكثر تحديدًا الأول
_ORDER = [
    "greet", "who", "time", "date", "help", "find", "search", "write", "mkdir",
    "screenshot", "lock", "disk", "ram", "procs", "battery", "ip", "news",
    "calc", "list", "read", "open",
]
SKILLS.sort(key=lambda s: _ORDER.index(s.name) if s.name in _ORDER else 99)
