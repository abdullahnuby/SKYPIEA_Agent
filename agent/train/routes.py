"""توجيه نوايا الموديل إلى أدوات فعلية."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from ..aliases import resolve
from ..commands import BATTERY_CMD, DISK_CMD, IP_CMD, LOCK_CMD, PROCS_CMD, RAM_CMD
from ..text import clean_phrase, normalize, strip_trailing

AR_DAYS = ("الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد")

OPEN_VERBS = r"(?:افتحلي|افتح\s+لي|افتح|شغلي|شغل|تفتحلي|تفتح|تشغلي|تشغل|تقدر\s+تفتح|open)"
SEARCH_VERBS = r"(?:ابحث|بحث|دور|تدور|تبحث|سيرش|search)"
READ_VERBS = r"(?:اقرا|تقرا|اقرا\s+لي|read)"

HELP_TEXT = (
    "🧠 بعرف أعمل حاجات كتير:\n"
    "• افتح برنامج أو موقع\n"
    "• ابحث في الويب\n"
    "• اقرا/اكتب ملفات\n"
    "• مساحة الديسك، الرام، العمليات، البطارية، الـ IP\n"
    "• سكرين شوت، قفل الجهاز\n"
    "• حساب، أخبار\n\n"
    "علّمني أي حاجة جديدة بـ /learn"
)

# حارس أمان: الموديل لو توقّع نية خطيرة من غير كلماتها الحقيقية، نرفض
GUARDS: dict[str, re.Pattern[str]] = {
    "lock": re.compile(r"(اقفل|قفل|lock)", re.IGNORECASE),
    "disk": re.compile(r"(مساح|ديسك|هارد|هارت|قرص|disk|space)", re.IGNORECASE),
    "ram": re.compile(r"(رام|ذاكر|memory|\bram\b)", re.IGNORECASE),
    "procs": re.compile(r"(عمليات|بروسيس|شغال|process)", re.IGNORECASE),
    "battery": re.compile(r"(بطار|شحن|battery)", re.IGNORECASE),
    "ip": re.compile(r"(\bip\b|اي\s*بي|شبك|واي\s*فاي|network)", re.IGNORECASE),
    "screenshot": re.compile(r"(سكرين|شاشه|screenshot)", re.IGNORECASE),
    "news": re.compile(
        r"^(?:ايه|قولي|هات|وريني|عايز|ممكن)?\s*(?:الاخبار|اخبار اليوم)"
        r"(?:\s+(?:النهارده|دلوقتي|بسرعة|حالا))?$",
        re.IGNORECASE,
    ),
}


def _clean(text: str) -> str:
    return clean_phrase(normalize(text)).strip(" .؟!")


def _strip(text: str, verbs: str) -> str:
    cleaned = _clean(text)
    without = re.sub(r"^" + verbs + r"\s*", "", cleaned, flags=re.IGNORECASE)
    without = re.sub(r"^(عن|على|علي|لي|لى|كمان|كذلك)\s+", "", without, flags=re.IGNORECASE)
    return clean_phrase(without).strip(" .؟!")


def build(label: str, text: str) -> dict[str, Any] | None:
    """يرجّع Action كـ dict جاهز، أو None لو مش قادر يستخرج المعاملات."""
    guard = GUARDS.get(label)
    if guard is not None and not guard.search(_clean(text)):
        return None

    if label == "greet":
        return {"reply": "أهلاً 👋 اسألني أي حاجة أو اكتب /help."}
    if label == "who":
        return {
            "reply": (
                "أنا agent شغّال على جهازك، وعقلي موديل صغير اتدرّب على أوامرك "
                "➕ مكتبة مهارات بتتعلم منك."
            )
        }
    if label == "help":
        return {"reply": HELP_TEXT}
    if label == "time":
        return {"reply": f"🕐 {datetime.now().strftime('%H:%M')} — {AR_DAYS[datetime.now().weekday()]}"}
    if label == "date":
        return {"reply": f"📅 {datetime.now().strftime('%Y-%m-%d')} — {AR_DAYS[datetime.now().weekday()]}"}
    if label == "lock":
        return {"tool": "shell", "args": {"command": LOCK_CMD}}
    if label == "disk":
        return {"tool": "shell", "args": {"command": DISK_CMD}}
    if label == "ram":
        return {"tool": "shell", "args": {"command": RAM_CMD}}
    if label == "procs":
        return {"tool": "shell", "args": {"command": PROCS_CMD}}
    if label == "battery":
        return {"tool": "shell", "args": {"command": BATTERY_CMD}}
    if label == "ip":
        return {"tool": "shell", "args": {"command": IP_CMD}}
    if label == "news":
        return {"tool": "search_web", "args": {"query": "أخبار اليوم", "limit": 5}}
    if label == "screenshot":
        return {"tool": "screenshot", "args": {"name": datetime.now().strftime("shot_%H%M%S")}}

    if label == "open":
        target = _strip(text, OPEN_VERBS)
        target = re.sub(r"^(برنامج|تطبيق|موقع|صفحة)\s+", "", target).strip()
        if not target:
            return None
        target = resolve(target)
        return {"tool": "open_target", "args": {"target": target}}

    if label == "search":
        query = _strip(text, SEARCH_VERBS)
        query = re.sub(r"^(?:لي|لى)\s+", "", query, flags=re.IGNORECASE)
        query = re.sub(r"^(?:عن|على|علي)\s+", "", query, flags=re.IGNORECASE)
        query = clean_phrase(query)
        return {"tool": "search_web", "args": {"query": query}} if query else None

    if label == "read":
        path = _clean(text)
        path = re.sub(r"^" + READ_VERBS + r"\s*", "", path, flags=re.IGNORECASE)
        path = re.sub(r"^(?:لي|لى|ملف)\s+", "", path).strip()
        path = clean_phrase(path)
        return {"tool": "read_file", "args": {"path": path}} if path else None

    if label == "calc":
        from ..brain import safe_calc

        expression = re.sub(
            r"^(?:احسب|احسبلي|احسب\s+لي|تحسب|تحسبلي|كم\s+يساوي|كام\s+يساوي|كام|كم)\s*",
            "",
            _clean(text),
            flags=re.IGNORECASE,
        )
        expression = re.sub(r"^(?:لي|لى)\s+", "", expression)
        expression = strip_trailing(expression)
        return {"reply": safe_calc(expression)} if expression else None

    return None
