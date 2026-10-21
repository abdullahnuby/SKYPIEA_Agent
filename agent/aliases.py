"""أسماء عربية شائعة → روابط/برامج/مجلدات حقيقية.

المشكلة اللي بيحلها: «افتح اليوتيوب» أو «افتح الفيس بوك» كان بيدوّر على
ملف بالاسم ده على الجهاز ويفشل. دلوقتي الاسم بيتحوّل لرابط قبل الفتح.
"""

from __future__ import annotations

import re
from pathlib import Path

from .text import normalize

HOME = Path.home()

ALIASES: dict[str, str] = {
    # مواقع
    "يوتيوب": "https://youtube.com",
    "يوتيوب ميوزك": "https://music.youtube.com",
    "جوجل": "https://google.com",
    "فيسبوك": "https://facebook.com",
    "فيس بوك": "https://facebook.com",
    "فيسوك": "https://facebook.com",
    "انستجرام": "https://instagram.com",
    "انستقرام": "https://instagram.com",
    "انستا": "https://instagram.com",
    "تويتر": "https://x.com",
    "اكس": "https://x.com",
    "تيك توك": "https://tiktok.com",
    "تيكتوك": "https://tiktok.com",
    "واتساب": "https://web.whatsapp.com",
    "واتس اب": "https://web.whatsapp.com",
    "لينكدان": "https://linkedin.com",
    "لينكد ان": "https://linkedin.com",
    "نتفليكس": "https://netflix.com",
    "سبوتيفاي": "https://open.spotify.com",
    "جيميل": "https://mail.google.com",
    "خرايط": "https://maps.google.com",
    "جوجل ماب": "https://maps.google.com",
    "درايف": "https://drive.google.com",
    "جوجل درايف": "https://drive.google.com",
    "ريديت": "https://reddit.com",
    "امازون": "https://amazon.com",
    "نون": "https://noon.com",
    "بينترست": "https://pinterest.com",
    "جوجل ترانسليت": "https://translate.google.com",
    # برامج
    "كروم": "chrome",
    "جوجل كروم": "chrome",
    "فايرفوكس": "firefox",
    "ايدج": "msedge",
    "حاسبه": "calc.exe",
    "اله حاسبه": "calc.exe",
    "نوته": "notepad.exe",
    "نوت باد": "notepad.exe",
    "نوتباد": "notepad.exe",
    "رسام": "mspaint.exe",
    "كاميرا": "microsoft.windows.camera:",
    "اعدادات": "ms-settings:",
    "مدير المهام": "taskmgr.exe",
    "وورد": "winword.exe",
    "اكسل": "excel.exe",
    "باوربوينت": "powerpnt.exe",
    "تليجرام": "https://web.telegram.org",
    # أسماء إنجليزية
    "youtube": "https://youtube.com",
    "google": "https://google.com",
    "facebook": "https://facebook.com",
    "instagram": "https://instagram.com",
    "twitter": "https://x.com",
    "tiktok": "https://tiktok.com",
    "whatsapp": "https://web.whatsapp.com",
    "linkedin": "https://linkedin.com",
    "netflix": "https://netflix.com",
    "spotify": "https://spotify.com",
    "gmail": "https://mail.google.com",
    "reddit": "https://reddit.com",
    "amazon": "https://amazon.com",
    "pinterest": "https://pinterest.com",
    "chatgpt": "https://chatgpt.com",
    "notepad": "notepad.exe",
    "chrome": "chrome.exe",
    # مجلدات
    "الداونلودز": str(HOME / "Downloads"),
    "التحميلات": str(HOME / "Downloads"),
    "التنزيلات": str(HOME / "Downloads"),
    "الديسكتوب": str(HOME / "Desktop"),
    "سطح المكتب": str(HOME / "Desktop"),
    "المستندات": str(HOME / "Documents"),
    "الصور": str(HOME / "Pictures"),
    "الفيديوهات": str(HOME / "Videos"),
    "الموسيقى": str(HOME / "Music"),
}

_SPACES = re.compile(r"\s+")


def _key(text: str) -> str:
    return _SPACES.sub("", normalize(text, lower=True))


def _build() -> dict[str, str]:
    table: dict[str, str] = {}
    for name, target in ALIASES.items():
        key = _key(name)
        table[key] = target
        if key.startswith("ال") and len(key) > 3:
            table.setdefault(key[2:], target)
    return table


_TABLE = _build()


def resolve(target: str) -> str:
    """يرجّع الرابط/البرنامج لو الاسم معروف، وإلا يرجّع الاسم زي ما هو."""
    clean = (target or "").strip().strip('"').strip("'")
    if not clean or clean.startswith(("http://", "https://")):
        return clean
    key = _key(clean)
    if key in _TABLE:
        return _TABLE[key]
    if key.startswith("ال") and key[2:] in _TABLE:
        return _TABLE[key[2:]]
    return clean
