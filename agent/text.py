"""تطبيع النص العربي — مشترك بين العقل والموديل."""

from __future__ import annotations

import re

_TASHKEEL = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u0640]")
# علامات الترقيم العربية بتتشال قبل التطبيع لأنها كانت بتكسر أواخر الأنماط
_AR_PUNCT = re.compile(r"[؟،؛…«»٪]+")
_PUNCT = re.compile(r"[^\w\s\u0600-\u06FF._/\\:+\-*%^()]+", re.UNICODE)
_SPACES = re.compile(r"\s+")

FILLERS = (
    "ممكن ",
    "لو سمحت ",
    "لو تكرمت ",
    "من فضلك ",
    "بعد اذنك ",
    "بعد إذنك ",
    "عايز ",
    "عاوز ",
    "أريد ",
    "اريد ",
    "يا زكي ",
    "يا بوت ",
    "بليز ",
    "please ",
)

TRAILING = (
    "بسرعة",
    "حالا",
    "دلوقتي",
    "لو سمحت",
    "لو تكرمت",
    "من فضلك",
    "بليز",
    "please",
    "يا زكي",
)


def normalize(text: str, *, lower: bool = False) -> str:
    """توحيد الهمزات والتاء المربوطة والتشكيل، وحذف العلامات الغريبة."""
    text = text or ""
    text = _TASHKEEL.sub("", text)
    text = _AR_PUNCT.sub(" ", text)
    for src, dst in (
        ("أ", "ا"),
        ("إ", "ا"),
        ("آ", "ا"),
        ("ٱ", "ا"),
        ("ى", "ي"),
        ("ئ", "ي"),
        ("ؤ", "و"),
        ("ة", "ه"),
    ):
        text = text.replace(src, dst)
    text = _PUNCT.sub(" ", text)
    text = _SPACES.sub(" ", text).strip()
    return text.lower() if lower else text


def strip_fillers(text: str) -> str:
    """حذف الكلمات الزائدة من أول الجملة (ممكن، لو سمحت...)."""
    result = text
    changed = True
    while changed:
        changed = False
        lowered = result.lower()
        for filler in FILLERS:
            if lowered.startswith(filler.lower()):
                result = result[len(filler) :].lstrip()
                changed = True
                break
    return result


def strip_trailing(text: str) -> str:
    """حذف اللواحق الزائدة (بسرعة، حالا، من فضلك...)."""
    result = (text or "").strip()
    changed = True
    while changed:
        changed = False
        trimmed = result.rstrip(" .!؟،,")
        # المقارنة بالتطبيع لأن النص الداخل غالبًا متطبّع (بسرعة → بسرعه)
        lowered = normalize(trimmed, lower=True)
        for word in TRAILING:
            if lowered.endswith(normalize(word, lower=True)):
                result = trimmed[: -len(word)].rstrip(" .!؟،,")
                changed = True
                break
        else:
            result = trimmed
    return result


def clean_phrase(text: str) -> str:
    """تنظيف جملة مستخدم: بادئات + لواحق + مسافات."""
    return strip_trailing(strip_fillers((text or "").strip())).strip()
