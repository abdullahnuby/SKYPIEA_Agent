from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.brain import Brain
from agent.memory import Memory
from agent.text import normalize

b = Brain(Memory(Path(":memory:")))

CASES = [
    "انشئ مجلد testdir",
    "اعمل مجلد newfolder",
    "انشئ ملف a.txt بمحتوى hello",
    "اكتب ملف test.txt فيه مرحبا",
    "فين ملف notes.txt",
    "الذاكرة العشوائية",
    "ال IP",
    "الاي بي",
    "الساعة كام؟",
    "ممكن تحسب 7+8",
    "احسب 2^10",
    "شغلي في شركة بيانات",
    "هدفي أفتح شركة",
    "افتح لي جوجل",
    "شغل تيك توك حالا",
    "أفتح  فيس بوك؟",
    "open تويتر",
    "Open YouTube",
    "ابحث لي عن اخبار التكنولوجيا",
    "من فضلك ابحث اخبار التكنولوجيا",
    "اعرض محتويات المجلد .",
    "كام رام مستخدم",
    "نسبة الشحن",
]

for text in CASES:
    print("=" * 70)
    print("TEXT:", text)
    print("NORM:", normalize(text))
    action = b.think(1, text)
    print("ACTION:", action)
