"""الذاكرة الشخصية: تستخرج معلومات المستخدم من كلامه، تحفظها، وترجّعها.

الفكرة: الموديل بيتوقع النية، والذاكرة بتخلي الرد شخصي. الاتنين مكمّلين لبعض —
موديل لغوي لوحده مابيفتكركش، والذاكرة لوحدها مابتفهمش الصياغة.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .config import BASE_DIR
from .memory import Memory
from .text import normalize

# مفاتيح قيمة واحدة (بتتحدّث مش بتتكرر)
SCALAR_KEYS = frozenset(
    {
        "الاسم", "المدينة", "الشغل", "الوظيفة", "الموبايل", "عيد الميلاد",
        "الجهاز", "اللغة", "التوقيت", "التواصل", "الروتين", "التعليم",
    }
)

# مفاتيح "قوية" تكسب على أي أمر اتنفّذ بالغلط من الموديل
STRONG_KEYS = SCALAR_KEYS | {"مشروع", "هدف", "ملاحظة", "قرار", "موعد_نهائي"}

LABELS = {
    "الاسم": "الاسم",
    "المدينة": "المدينة",
    "الشغل": "الشغل",
    "الوظيفة": "الوظيفة",
    "الموبايل": "الموبايل",
    "عيد الميلاد": "عيد الميلاد",
    "الجهاز": "الجهاز",
    "اللغة": "اللغة",
    "التوقيت": "التوقيت",
    "التواصل": "أسلوب التواصل",
    "الروتين": "الروتين",
    "التعليم": "التعليم",
    "بحب": "بيحب",
    "مش_بحب": "مش بيحب",
    "بستخدم": "بيستخدم",
    "اهتمام": "مهتم بـ",
    "مشروع": "مشروع",
    "هدف": "هدفه",
    "قرار": "قرار",
    "واقف_في": "واقف في",
    "موعد_نهائي": "آخر ميعاد",
    "علاقة": "علاقة",
    "طريقة": "طريقة شغله",
    "ملاحظة": "ملاحظة",
}

# المفتاح → (البُعد المنظّم، الأهمية). الأبعاد مستوحاة من ethan-agent:
# identity / preference / activity / decision / relationship / methodology.
KEY_META: dict[str, tuple[str, float]] = {
    "الاسم": ("identity.preferred_name", 1.0),
    "المدينة": ("identity.location", 1.0),
    "الشغل": ("identity.organization", 1.0),
    "الوظيفة": ("identity.occupation", 1.0),
    "الموبايل": ("identity.contact", 0.9),
    "عيد الميلاد": ("identity.birthday", 0.9),
    "الجهاز": ("identity.device", 0.7),
    "اللغة": ("identity.language", 0.9),
    "التوقيت": ("identity.timezone", 0.8),
    "التعليم": ("identity.education", 0.8),
    "هدف": ("identity.long_term_goal", 1.0),
    "بحب": ("preference.likes", 0.8),
    "مش_بحب": ("preference.negative", 0.9),
    "بستخدم": ("preference.tools", 0.8),
    "اهتمام": ("preference.interest", 0.6),
    "التواصل": ("preference.communication", 0.9),
    "الروتين": ("preference.work_habits", 0.7),
    "مشروع": ("activity.project", 0.9),
    "واقف_في": ("activity.blocker", 0.8),
    "موعد_نهائي": ("activity.deadline", 0.9),
    "قرار": ("decision.chosen", 0.9),
    "علاقة": ("relationship.role", 0.8),
    "طريقة": ("methodology.workflow", 0.8),
    "ملاحظة": ("custom.note", 0.6),
}

TYPE_LABELS = {
    "identity": "الهوية",
    "preference": "التفضيلات",
    "activity": "الشغل والاهتمامات",
    "decision": "القرارات",
    "relationship": "العلاقات",
    "methodology": "طريقة العمل",
    "custom": "ملاحظات",
    "task_context": "ملاحظات",
}

TYPE_ORDER = ["identity", "preference", "activity", "decision", "relationship", "methodology", "custom", "task_context"]

# مفاتيح بتتعلّم بالملاحظة (observed) مش بالتصريح — بتفضل pending لحد ما تتكرر.
WEAK_KEYS: frozenset[str] = frozenset({"اهتمام"})

ORDER = list(LABELS)

# إشارات إن المستخدم بيصحّح معلومة قديمة.
CORRECTION_START = re.compile(r"^(?:لأ|لا|مش|غلط|تصحيح|بالمناسبه|بالمناسبة)\b")

STOP_VALUES = {
    "ايه",
    "إيه",
    "كام",
    "مين",
    "فين",
    "ليه",
    "ازاي",
    "إزاي",
    "امتى",
    "ده",
    "دي",
    "كده",
    "هو",
    "هي",
    "ولا",
    "لا",
    "إن",
    "ان",
    "أن",
    "هروح",
    "هعمل",
    "هذاكر",
    "هسافر",
}

SECRET_MARKERS = (
    "باسورد",
    "كلمة السر",
    "كلمه السر",
    "password",
    "passwd",
    "otp",
    "رمز التحقق",
    "رمز الدخول",
    "pin code",
    "cvv",
    "بطاقة",
)

# (المفتاح، النمط، قيمة واحدة؟)
PATTERNS: list[tuple[str, re.Pattern[str], bool]] = [
    (
        "الاسم",
        re.compile(
            r"(?<![\w])(?:اسمي|أسمي|إسمي|اسمى|إسمى|ناديني|ينادوني)\s*[:=]?\s*([^\n.!؟]{2,40})"
        ),
        True,
    ),
    (
        "المدينة",
        re.compile(
            r"(?<![\w])(?:أنا\s+من|انا\s+من|ساكن(?:ة|ه)?\s+(?:في|فى|ب)|"
            r"مقيم(?:ة|ه)?\s+(?:في|فى)|بعيش\s+(?:في|فى)|عايش(?:ة|ه)?\s+(?:في|فى))\s+"
            r"([^\n.!؟]{2,40})"
        ),
        True,
    ),
    (
        "الشغل",
        re.compile(
            r"(?<![\w])(?:بشتغل|أشتغل|اشتغل|شغلي|شغلتي|وظيفتي)\s+(?:في|فى|بـ|ب)\s+"
            r"([^\n.!؟]{2,60})"
        ),
        True,
    ),
    (
        "الوظيفة",
        re.compile(
            r"(?<![\w])(?:أنا|انا)\s+(مهندس|مبرمج|طالب|دكتور|معلم|محاسب|مصمم|صيدلي|محامي|"
            r"ممرض|صحفي|باحث|موظف|فنان)(?![\w])"
        ),
        True,
    ),
    (
        "الوظيفة",
        re.compile(
            r"(?<![\w])(?:شغلتي|وظيفتي|مهنتي)\s+(?:هي\s+)?(مهندس|مبرمج|طالب|دكتور|معلم|محاسب|"
            r"مصمم|صيدلي|محامي|ممرض|صحفي|باحث|موظف|فنان)(?![\w])"
        ),
        True,
    ),
    (
        "الموبايل",
        re.compile(
            r"(?<![\w])(?:رقمي|موبايلي|تليفوني|واتسابي|رقم\s+الواتس|رقم\s+الموبايل)\s*[:=]?\s*"
            r"(\+?[\d\s\-]{7,20})"
        ),
        True,
    ),
    (
        "عيد الميلاد",
        re.compile(r"(?<![\w])(?:عيد\s+ميلادي|ميلادي|اتولدت)\s+(?:في\s+)?([^\n.!؟]{2,40})"),
        True,
    ),
    (
        "الجهاز",
        re.compile(
            r"(?<![\w])(?:جهازي|اللابتوب\s+بتاعي|الكمبيوتر\s+بتاعي)\s+(?:هو\s+)?([^\n.!؟]{2,60})"
        ),
        True,
    ),
    (
        "بحب",
        re.compile(
            r"(?<!مش )(?<!ما)(?<![\w])(?:بحب|أحب|احب|بيعجبني|بتعجبني|بعشق|بموت\s+في)\s+"
            r"([^\n.!؟]{2,60})"
        ),
        False,
    ),
    (
        "مش_بحب",
        re.compile(
            r"(?<![\w])(?:مش\s+بحب|مش\s+أحب|مش\s+احب|مابحبش|بكره|أكره|اكره)\s+"
            r"([^\n.!؟]{2,60})"
        ),
        False,
    ),
    (
        "بستخدم",
        re.compile(
            r"(?<![\w])(?:بستخدم|أستخدم|استخدم|بستعمل|أستعمل|استعمل)\s+([^\n.!؟]{2,40})"
        ),
        False,
    ),
    (
        # إشارة غير مباشرة: بتتسجل observed وتستنى تتكرر في جلسة تانية.
        "اهتمام",
        re.compile(
            r"(?<![\w])(?:مهتم\s+ب|بعشق|بتابع)\s*([^\n.!؟]{2,60})"
        ),
        False,
    ),
    (
        "مشروع",
        re.compile(
            r"(?<![\w])(?:مشروعي|المشروع\s+بتاعي|بطور|بشتغل\s+على)\s+([^\n.!؟]{2,60})"
        ),
        False,
    ),
    (
        "هدف",
        re.compile(
            r"(?<![\w])(?:هدفي|نفسي|عايز\s+أوصل|عايز\s+اوصل|حابب\s+أوصل)\s+([^\n.!؟]{2,80})"
        ),
        False,
    ),
    (
        "اللغة",
        re.compile(
            r"(?<![\w])(?:لغتي|اللغة\s+اللي\s+بتكلم\s+بها|بتكلم\s+ب(?:ـ|\s))\s*"
            r"([^\n.!؟]{2,30})"
        ),
        True,
    ),
    (
        "التوقيت",
        re.compile(
            r"(?<![\w])(?:توقيتي|أنا\s+في\s+توقيت|المنطقة\s+الزمنية\s+بتاعتي)\s+"
            r"([^\n.!؟]{2,40})"
        ),
        True,
    ),
    (
        "التعليم",
        re.compile(
            r"(?<![\w])(?:درست|خريج|شهادتي|اتعلمت)\s+([^\n.!؟]{2,60})"
        ),
        True,
    ),
    (
        "التواصل",
        re.compile(
            r"(?<![\w])(?:عايز\s+ردودك|عاوز\s+ردودك|ردودك\s+تكون|كلمني\s+ب|"
            r"أسلوبك\s+يكون|اسلوبك\s+يكون)\s+([^\n.!؟]{2,60})"
        ),
        True,
    ),
    (
        "الروتين",
        re.compile(
            r"(?<![\w])(?:روتيني|عادة\s+بصحى|بصحى\s+كل\s+يوم|بشتغل\s+أحسن|بشتغل\s+احسن)\s+"
            r"([^\n.!؟]{2,60})"
        ),
        True,
    ),
    (
        "قرار",
        re.compile(
            r"(?<![\w])(?:قررت|اخترت|استقريت\s+على|وافقت\s+على)\s+(?:إن\s+|ان\s+)?"
            r"([^\n.!؟]{2,80})"
        ),
        False,
    ),
    (
        "واقف_في",
        re.compile(
            r"(?<![\w])(?:واقف\s+في|متعطل\s+في|مش\s+عارف\s+أكمل|مش\s+عارف\s+اكمل)\s+"
            r"([^\n.!؟]{2,80})"
        ),
        False,
    ),
    (
        "موعد_نهائي",
        re.compile(
            r"(?<![\w])(?:لازم\s+أخلص|لازم\s+اخلص|آخر\s+ميعاد|اخر\s+ميعاد|"
            r"الديدلاين|ميعاد\s+التسليم)\s+(?:من\s+)?([^\n.!؟]{2,60})"
        ),
        False,
    ),
    (
        "علاقة",
        re.compile(
            r"(?<![\w])(?:صاحبي|أخويا|اخويا|زميلي|مديري|مراتي|جوزي)\s+"
            r"([^\n.!؟]{2,50})"
        ),
        False,
    ),
    (
        "طريقة",
        re.compile(
            r"(?<![\w])(?:طريقتي|بطريقتي|أسلوبي|اسلوبي|بشتغل\s+كده)\s+(?:في\s+)?"
            r"([^\n.!؟]{2,80})"
        ),
        False,
    ),
]

# قواعد سلوكية صريحة: «من دلوقتي ...» / «المفروض ...» / «متعملش ...»
RULE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"^(?:من\s+دلوقتي|من\s+الان|من\s+الآن|دايما|دائما|دايماً|دائماً|"
        r"خلي\s+بالك|خد\s+بالك|اتعلم|تعلم)\s+(?:إن|ان|أن)?\s*(.+)$"
    ),
    re.compile(
        r"^(?:لأ|لا|مش\s+كده|غلط|بلاش)\s*[،, ]*(?:المفروض|الافضل|الأفضل|"
        r"خليك|اعمل|استخدم|قول)\s+(.+)$"
    ),
    re.compile(r"^(متعملش|متبعتش|متقولش|متحطش|متفتحش)\s+(.+)$"),
)

NOTE_PREFIX = re.compile(
    r"^(?:يا\s+\S+\s+)?(?:افتكر|أفتكر|احفظ|خد\s+بالك|خلي\s+بالك|سجل)(?:\s+|[:：]\s*)"
    r"(?:إن|ان|أن)?\s*(.+)$",
    re.IGNORECASE,
)

FORGET_PREFIX = re.compile(
    r"^(?:انسي|أنسى|انس|امسح|احذف|شيل|ازال)\s+(?:معلومة\s+|حقيقة\s+|كل\s+)?(.+?)"
    r"(?:\s+من\s+ذاكرتك)?$",
    re.IGNORECASE,
)

FORGET_MAP: list[tuple[str, tuple[str, ...]]] = [
    ("الاسم", ("الاسم", "اسمي")),
    ("المدينة", ("المدينة", "مدينتي", "سكني")),
    ("الشغل", ("الشغل", "شغلي", "شغلتي")),
    ("الوظيفة", ("الوظيفة", "وظيفتي", "مهنتي")),
    ("الموبايل", ("الموبايل", "رقمي", "تليفوني")),
    ("عيد الميلاد", ("عيد ميلادي", "ميلادي")),
    ("مشروع", ("المشروع", "مشروعي")),
    ("هدف", ("الهدف", "هدفي")),
    ("بحب", ("بحب", "تفضيلاتي")),
    ("مش_بحب", ("مش_بحب", "بكره")),
    ("بستخدم", ("بستخدم", "استخداماتي")),
    ("ملاحظة", ("الملاحظات", "ملاحظاتي", "الملاحظة")),
]

RECALL = re.compile(
    r"(?:انت\s+)?فاكر\s+(?:ايه\s+|حاجه\s+)?(?:عني|عليا)"
    r"|(?:انت\s+)?عارف\s+(?:عني|عليا)\s*(?:ايه|حاجه)?"
    r"|(?:بتعرف|تعرف)\s+(?:عني|عليا)\s*(?:ايه|حاجه)?"
    r"|ايه\s+(?:اللي\s+)?(?:فاكره|تعرفه|انت\s+فاكره)\s+(?:عني|عليا)"
    r"|(?:ايه\s+)?ذاكرتك\s+(?:عني|عليا)"
    r"|قولي\s+(?:اللي\s+)?(?:تعرفه|فاكره|معلوماتك)\s+(?:عني|عليا)"
    r"|مين\s+انا|انا\s+مين"
    r"|عرفني\s+بنفسي|البروفايل\s+بتاعي|بياناتي"
    r"|افتكرك\s+ايه|فاكرني"
)

NAME_QUESTION = re.compile(
    r"^(?:انت\s+)?(?:فاكر\s+)?اسمي\s*(?:ايه|مين)?$"
    r"|^انت\s+عارف\s+اسمي"
    r"|^فاكر\s+اسمي"
)

KEY_RECALL: list[tuple[str, re.Pattern[str]]] = [
    ("city", re.compile(r"فاكر\s+(?:انا\s+)?(?:من\s+فين|مدينتي|سكني)|(?:انا\s+)?من\s+فين|ساكن\s+فين|مدينتي\s+ايه")),
    ("work", re.compile(r"فاكر\s+(?:شغلي|شغلتي|وظيفتي)|(?:بشتغل|شغلي|وظيفتي)\s+(?:في\s+ايه|ايه)")),
    ("likes", re.compile(r"فاكر\s+(?:بحب|تفضيلاتي)|(?:بحب|باحب)\s+ايه")),
    ("project", re.compile(r"فاكر\s+مشروعي|مشروعي\s+ايه")),
    ("goal", re.compile(r"فاكر\s+هدفي|هدفي\s+ايه")),
]

TOPIC_RECALL = re.compile(
    r"كنا\s+بنتكلم\s+عن"
    r"|اخر\s+حاجه\s+(?:قلتها|قلتهالي|قلتهالك|اتكلمنا\s+عنها)"
    r"|فاكر\s+اخر\s+حاجه"
    r"|احنا\s+اتكلمنا\s+عن\s+ايه"
    r"|اخر\s+محادثه"
    r"|قولي\s+اخر\s+حاجه"
)

# سؤال عن موضوع معيّن: «فاكر ايه عن شغلي؟» / «قولي اللي تعرفه عن مشروعي»
TOPIC_QUERY = re.compile(
    r"(?:انت\s+)?فاكر\s+(?:ايه|إيه|حاجه|حاجة)\s+عن\s+(.+)"
    r"|(?:قولي|هات|وريني)\s+(?:كل\s+)?(?:اللي\s+)?(?:فاكره|تعرفه|معلوماتك)\s+عن\s+(.+)"
    r"|(?:افتكر|فكرني)\s+ب(?:ـ|\s)\s*(.+)"
)

# تصنيف نية السؤال — بيوجّه الاسترجاع لنوع الذاكرة المناسب (زي Ethan).
INTENT_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "identity",
        (
            "مين انا", "اسمي", "مدينتي", "ساكن", "شغلي", "وظيفتي", "لغتي",
            "توقيتي", "جهازي", "هدفي", "تعليمي", "درست", "شهادتي", "رقمي",
            "عيد ميلادي", "معلوماتي",
        ),
    ),
    (
        "preference",
        (
            "بحب", "مش بحب", "بكره", "تفضيل", "بستخدم", "ردودك", "أسلوبك",
            "اسلوبك", "روتيني", "بتكلم", "أكلمك", "اكلمك",
        ),
    ),
    (
        "activity",
        (
            "مشروعي", "شغال على", "بطور", "واقف في", "متعطل", "موعد",
            "ديدلاين", "مشغول في", "بشتغل على",
        ),
    ),
    (
        "decision",
        ("قررت", "اخترت", "استقريت", "ليه اخترت", "قرار", "وافقت"),
    ),
    (
        "methodology",
        ("طريقتي", "بطريقتي", "أسلوبي", "اسلوبي", "بشتغل كده", "خطوات"),
    ),
    (
        "relationship",
        ("صاحبي", "أخويا", "اخويا", "زميلي", "مديري", "مراتي", "جوزي"),
    ),
)

_STOP_WORDS = frozenset(
    {
        "عن", "من", "في", "على", "علي", "ايه", "إيه", "اللي", "انا", "أنا",
        "انت", "أنت", "هو", "هي", "يا", "قولي", "فاكر", "فاكره", "تعرف",
        "معلوماتك", "كل", "حاجه", "حاجة", "ال", "بتاع", "بتاعي", "عني",
        "عليا", "مين", "كام", "فين", "ليه", "ازاي", "إزاي",
    }
)

REPEAT = re.compile(
    r"^(?:كرر|كررها|كرره|تاني|تاني\s+مره|نفس\s+الحاجه|اعملها\s+تاني|كمان\s+مره)$"
)

OPEN_IT = re.compile(r"^(?:افتحه|شغله|افتحها|شغلها|افتحهولي|شغلهولي)(?:\s+تاني)?$")

LEADING_W = re.compile(
    r"^(?:و|ثم)\s*(?=(?:افتح|شغل|ابحث|دور|اقرا|اكتب|اعمل|انشئ|صور|اقفل|احسب|مساحة|الرام|"
    r"الاخبار|الساعه|الوقت|تاريخ))"
)


def _esc(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _ws(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _clean_value(value: str) -> str:
    value = value.strip().strip(" .،,؛;:!-ـ؟")
    value = re.sub(r"\s+", " ", value)
    return value[:120].strip()


def _valid_value(value: str) -> bool:
    if not value or len(value) < 2:
        return False
    if value in STOP_VALUES or value.split()[0] in STOP_VALUES:
        return False
    if "؟" in value or "?" in value or "=>" in value:
        return False
    return True


def looks_secret(text: str) -> bool:
    low = (text or "").lower()
    return any(marker in low for marker in SECRET_MARKERS)


def dimension_of(key: str) -> str:
    return KEY_META.get(key, (f"custom.{normalize(key, lower=True).replace(' ', '_')}", 0.5))[0]


def importance_of(key: str) -> float:
    return KEY_META.get(key, ("", 0.5))[1]


def type_of_dimension(dimension: str) -> str:
    return (dimension or "").split(".", 1)[0] or "task_context"


def classify_intent(text: str) -> str:
    """تصنيف سؤال المستخدم لنوع الذاكرة المطلوبة (قواعد، بدون LLM)."""
    norm = normalize(text or "", lower=True)
    for intent, keywords in INTENT_RULES:
        if any(normalize(k, lower=True) in norm for k in keywords):
            return intent
    return "unknown"


def _tokens(text: str) -> list[str]:
    norm = normalize(text or "", lower=True)
    return [
        token
        for token in re.split(r"\s+", norm)
        if len(token) > 2 and token not in _STOP_WORDS
    ]


def _decay_factor(fact: dict[str, Any], now: float | None = None) -> float:
    """عامل تقادم للترتيب فقط — الهوية والتفضيلات والعلاقات معفاة."""
    dim = str(fact.get("dimension") or "")
    if not dim or type_of_dimension(dim) in {"identity", "preference", "relationship"}:
        return 1.0
    half_life = 3.0 if str(fact.get("evidence") or "") == "tentative" else 30.0
    now = now or datetime.now().timestamp()
    anchor = max(
        float(fact.get("updated_at") or 0.0),
        float(fact.get("created_at") or 0.0),
        float(fact.get("last_recalled_at") or 0.0),
    )
    days = max(0.0, (now - anchor) / 86400.0)
    return 0.5 ** (days / half_life)


class Personal:
    """طبقة الذاكرة الشخصية فوق قاعدة البيانات."""

    def __init__(self, memory: Memory) -> None:
        self.memory = memory

    def backfill_dimensions(self) -> int:
        """يربط حقائق الإصدار القديم بأبعادها عشان تظهر في البروفايل والاسترجاع."""
        return self.memory.backfill_dimensions(
            {key: meta[0] for key, meta in KEY_META.items()}
        )

    # ---------- الجلسات ----------
    def session_id(self, chat_id: int) -> str:
        """جلسة مستقلة لكل يوم — عشان التكرار في يومين مختلفين يرقّي المعلومة."""
        today = date.today().isoformat()
        prefix = f"{chat_id}:{today}"
        current = self.memory.get_state(chat_id, "session_id")
        if not current or not str(current).startswith(prefix):
            current = f"{prefix}:{uuid.uuid4().hex[:8]}"
            self.memory.set_state(chat_id, "session_id", current)
        return str(current)

    def rotate_session(self, chat_id: int) -> str:
        current = f"{chat_id}:{date.today().isoformat()}:{uuid.uuid4().hex[:8]}"
        self.memory.set_state(chat_id, "session_id", current)
        return current

    # ---------- استخراج ----------
    def observe(
        self,
        chat_id: int,
        text: str,
        source: str = "msg",
        *,
        strong_only: bool = False,
    ) -> list[dict[str, Any]]:
        """يستخرج أي معلومات عن المستخدم من الرسالة ويحفظها بصمت."""
        text = _ws(text)
        if not text or text.startswith("/") or looks_secret(text):
            return []

        session = self.session_id(chat_id)
        correcting = bool(CORRECTION_START.search(normalize(text, lower=True)))
        found: list[dict[str, Any]] = []
        for key, pattern, scalar in PATTERNS:
            if strong_only and key not in STRONG_KEYS:
                continue
            match = pattern.search(text)
            if not match:
                continue
            value = _clean_value(match.group(1))
            if not _valid_value(value):
                continue
            evidence = "observed" if key in WEAK_KEYS else "explicit"
            status = "active" if evidence in {"explicit", "corrected"} else "pending"
            confidence = 0.5 if status == "pending" else 0.95
            if correcting:
                old = self.memory.get_facts(chat_id, key)
                if old and any(str(row["value"]).strip() != value for row in old):
                    evidence, status, confidence = "corrected", "active", 1.0
            fact_id = self.memory.save_fact(
                chat_id,
                key,
                value,
                source,
                scalar=scalar,
                dimension=dimension_of(key),
                evidence=evidence,
                confidence=confidence,
                quote=text[:500],
                session_id=session,
                status=status,
            )
            found.append(
                {
                    "id": fact_id,
                    "key": key,
                    "value": value,
                    "dimension": dimension_of(key),
                    "evidence": evidence,
                }
            )
        return found

    # ---------- أوامر الذاكرة ----------
    def handle(self, chat_id: int, text: str, *, is_command: bool = False) -> str | None:
        """لو الرسالة عن الذاكرة نفسها، يرجّع الرد. غير كده None."""
        raw = _ws(text)
        if not raw:
            return None

        norm = normalize(raw, lower=True)

        # الملاحظات الصريحة أولًا: «خد بالك إن ...» مش قاعدة سلوك.
        note = NOTE_PREFIX.match(raw)
        if note:
            content = _clean_value(re.sub(r"^(?:إن|ان|أن)\s+", "", note.group(1)))
            if looks_secret(content):
                return "🔒 مش هحفظ كلمات السر أو أرقام البطاقات. استخدم مدير باسورد."
            if not _valid_value(content):
                return "🤔 اكتب المعلومة بعد «افتكر إن» — مثال: افتكر إن بحب القهوة السادة."
            fact_id = self.memory.save_fact(
                chat_id,
                "ملاحظة",
                content,
                "explicit",
                dimension="custom.note",
                quote=raw[:500],
                session_id=self.session_id(chat_id),
            )
            return f"📝 تمام، حفظت: <b>{_esc(content)}</b> <code>#{fact_id}</code>"

        # قواعد سلوكية: «من دلوقتي ...» / «المفروض ...» / «متعملش ...»
        rule_reply = self._learn_rule(chat_id, norm)
        if rule_reply:
            return rule_reply

        forget_reply = self._forget(chat_id, raw)
        if forget_reply:
            return forget_reply

        if TOPIC_RECALL.search(norm):
            return self.topic_recall(chat_id)

        topic = TOPIC_QUERY.search(norm)
        if topic:
            query = next((g for g in topic.groups() if g), "")
            return self.recall_reply(chat_id, query)

        if NAME_QUESTION.search(norm):
            name = self.name(chat_id)
            if name:
                return f"اسمك <b>{_esc(name)}</b> — فاكره ✅"
            return "لسه متعرفتش باسمك. قولي: <code>اسمي ...</code> وأنا هفتكرها."

        for kind, pattern in KEY_RECALL:
            if pattern.search(norm):
                return self._recall_key(chat_id, kind)

        if RECALL.search(norm):
            return self.render_profile(chat_id)

        found = self.observe(chat_id, raw, strong_only=is_command)

        if found and (not is_command or any(f["key"] in STRONG_KEYS for f in found)):
            weak = [fact for fact in found if fact.get("evidence") == "observed"]
            solid = [fact for fact in found if fact.get("evidence") != "observed"]
            if solid:
                lines = [
                    f"• {LABELS.get(fact['key'], fact['key'])}: <b>{_esc(fact['value'])}</b>"
                    for fact in solid
                ]
                return (
                    "📝 <b>حفظت عنك</b>\n"
                    + "\n".join(lines)
                    + "\n\nاسألني في أي وقت: «انت فاكر ايه عني؟»"
                )
            lines = [
                f"• {LABELS.get(fact['key'], fact['key'])}: <b>{_esc(fact['value'])}</b>"
                for fact in weak
            ]
            return (
                "👀 <b>سجلت ملاحظة</b>\n"
                + "\n".join(lines)
                + "\n\nهثبّتها في ذاكرتي لما تتكرر تاني."
            )

        return None

    # ---------- المسح ----------
    def _forget(self, chat_id: int, raw: str) -> str | None:
        norm = normalize(raw, lower=True)
        match = FORGET_PREFIX.match(norm)
        if not match:
            return None

        target = match.group(1).strip()
        if target in {"كل حاجه", "كل حاجة", "كل معلوماتي", "ذاكرتي", "كل حاجه عني"}:
            count = self.memory.delete_all_facts(chat_id)
            return f"🗑 مسحت {count} معلومة من ذاكرتي." if count else "الذاكرة فاضية أصلًا."

        key: str | None = None
        rest = ""
        for candidate, words in FORGET_MAP:
            for word in words:
                norm_word = normalize(word, lower=True)
                if norm_word in target:
                    key = candidate
                    rest = target.split(norm_word, 1)[1].strip()
                    break
            if key:
                break

        if key:
            if key in {"بحب", "مش_بحب", "بستخدم"} and rest:
                count = self.memory.delete_facts(chat_id, key, rest)
                if not count:
                    count = self.memory.delete_facts(chat_id, key)
            else:
                count = self.memory.delete_facts(chat_id, key)
            if count:
                return f"🗑 تم مسح {LABELS.get(key, key)} ({count})."
            return f"مفيش حاجة محفوظة عن {LABELS.get(key, key)}."

        # مفيش مفتاح واضح — ندوّر في القيم نفسها
        words = [w for w in target.split() if len(w) > 2]
        removed = 0
        for fact in self.memory.all_facts(chat_id):
            value = normalize(str(fact["value"]), lower=True)
            if any(w in value for w in words):
                removed += int(self.memory.delete_fact(chat_id, int(fact["id"])))
        if removed:
            return f"🗑 مسحت {removed} معلومة."
        return "مفيش معلومة بالوصف ده. جرب: <code>امسح الاسم</code> أو <code>/facts</code>."

    # ---------- قواعد السلوك ----------
    def _learn_rule(self, chat_id: int, norm: str) -> str | None:
        for pattern in RULE_PATTERNS:
            match = pattern.match(norm)
            if not match:
                continue
            if len(match.groups()) == 2:
                rule = f"{match.group(1)} {match.group(2)}".strip()
            else:
                rule = match.group(1).strip()
            rule = _clean_value(rule)
            if len(rule) < 3:
                continue
            procedure_id = self.memory.save_procedure(chat_id, rule, context="user_correction")
            return (
                f"🧭 تمام، اتعلمت قاعدة #{procedure_id}: <b>{_esc(rule)}</b>\n"
                "هطبّقها من دلوقتي. شوفها بـ <code>/rules</code>."
            )
        return None

    def learn_rule(self, chat_id: int, rule: str, context: str = "manual") -> int:
        return self.memory.save_procedure(chat_id, rule, context=context)

    def rules(self, chat_id: int) -> list[dict[str, Any]]:
        return self.memory.all_procedures(chat_id)

    def forget_rule(self, chat_id: int, procedure_id: int) -> bool:
        return self.memory.delete_procedure(chat_id, procedure_id)

    def apply_rules(self, chat_id: int, reply: str) -> str:
        """تطبيق بسيط للقواعد اللي المستخدم صحّح بها سلوك الرد."""
        if not reply:
            return reply
        rules = normalize(" ".join(str(p["rule"]) for p in self.rules(chat_id)), lower=True)
        if any(word in rules for word in ("مختصر", "قصير", "اختصر", "مطولش")):
            if len(reply) > 500:
                reply = reply[:500].rstrip() + "…"
        if any(word in rules for word in ("بدون ايموجي", "مفيش ايموجي", "بلاش ايموجي", "من غير ايموجي")):
            reply = re.sub(
                "[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]+", "", reply
            ).strip()
        return reply

    # ---------- استرجاع ذكي ----------
    def recall(self, chat_id: int, query: str = "", limit: int = 8) -> list[dict[str, Any]]:
        """يرجّع أنسب الحقائق للسؤال، بترتيب ثقة + تطابق + حداثة."""
        facts = self.memory.all_facts(chat_id)
        if not facts:
            return []
        intent = classify_intent(query)
        tokens = _tokens(query)
        now = datetime.now().timestamp()
        scored: list[tuple[float, dict[str, Any]]] = []
        for fact in facts:
            dim = str(fact.get("dimension") or dimension_of(str(fact["key"])))
            haystack = normalize(
                f"{fact['key']} {fact['value']} {dim}", lower=True
            )
            overlap = sum(1 for token in tokens if token in haystack)
            if tokens and not overlap and not (intent and dim.startswith(intent)):
                continue
            score = overlap * 1.5
            score += float(fact.get("confidence") or 0.5) * 0.6
            score += min(int(fact.get("recall_count") or 0), 5) * 0.05
            if intent != "unknown" and dim.startswith(intent):
                score += 1.2
            score *= _decay_factor(fact, now)
            scored.append((score, fact))
        scored.sort(
            key=lambda item: (
                -item[0],
                -float(item[1].get("confidence") or 0.0),
                -float(item[1].get("updated_at") or 0.0),
            )
        )
        top = [fact for _, fact in scored[:limit]]
        self.memory.mark_recalled([int(fact["id"]) for fact in top])
        return top

    def recall_reply(self, chat_id: int, query: str) -> str:
        topic = _clean_value(query)
        facts = self.recall(chat_id, query, limit=8)
        if not facts:
            return (
                f"🤔 مفيش عندي حاجة عن «{_esc(topic)}» لسه.\n"
                "علّمني: <code>افتكر إن ...</code>"
            )
        lines = []
        for fact in facts:
            label = LABELS.get(str(fact["key"]), str(fact["key"]))
            conf = float(fact.get("confidence") or 1.0)
            mark = "" if conf >= 0.9 else f" <i>(ثقة {conf:.0%})</i>"
            lines.append(f"• {label}: <b>{_esc(fact['value'])}</b>{mark}")
        return f"🧠 <b>اللي فاكره عن {_esc(topic)}</b>\n" + "\n".join(lines)

    # ---------- قراءة ----------
    def name(self, chat_id: int) -> str | None:
        facts = self.memory.get_facts(chat_id, "الاسم")
        return facts[-1]["value"] if facts else None

    def _recall_key(self, chat_id: int, kind: str) -> str:
        facts = self.memory.all_facts(chat_id)

        def values(*keys: str) -> list[str]:
            return [f["value"] for f in facts if f["key"] in keys]

        if kind == "city":
            found = values("المدينة")
            return f"انت من <b>{_esc(found[-1])}</b> 🏙" if found else "لسه متعرفش انت من فين — قولي: <code>أنا من ...</code>"
        if kind == "work":
            found = values("الوظيفة", "الشغل")
            return f"شغلك: <b>{_esc(' — '.join(dict.fromkeys(found)))}</b> 💼" if found else "لسه متعرفش شغلك — قولي: <code>بشتغل في ...</code>"
        if kind == "likes":
            found = values("بحب")
            return "بتحب: <b>" + _esc("، ".join(found)) + "</b> ❤️" if found else "لسه متعرفش تفضيلاتك — قولي: <code>بحب ...</code>"
        if kind == "project":
            found = values("مشروع")
            return "مشروعك: <b>" + _esc("، ".join(found)) + "</b> 🚀" if found else "لسه متعرفش مشروعك — قولي: <code>مشروعي ...</code>"
        if kind == "goal":
            found = values("هدف")
            return "هدفك: <b>" + _esc("، ".join(found)) + "</b> 🎯" if found else "لسه متعرفش هدفك — قولي: <code>هدفي ...</code>"
        return self.render_profile(chat_id)

    def render_profile(self, chat_id: int) -> str:
        facts = self.memory.all_facts(chat_id)
        if not facts:
            return (
                "🧠 <b>ذاكرتي فاضية عنك لسه</b>\n\n"
                "علّمني بـ:\n"
                "• <code>اسمي عبدالله</code>\n"
                "• <code>بحب القهوة السادة</code>\n"
                "• <code>افتكر إن شغلي بيبدأ 9 الصبح</code>\n\n"
                "وبعدها اسألني: «انت فاكر ايه عني؟»"
            )

        grouped: dict[str, list[dict[str, Any]]] = {}
        for fact in facts:
            dim = str(fact.get("dimension") or dimension_of(str(fact["key"])))
            grouped.setdefault(type_of_dimension(dim), []).append(fact)

        lines: list[str] = []
        for type_name in TYPE_ORDER:
            group = grouped.get(type_name)
            if not group:
                continue
            lines.append(f"\n<b>{TYPE_LABELS.get(type_name, type_name)}</b>")
            for fact in group:
                label = LABELS.get(str(fact["key"]), str(fact["key"]))
                conf = float(fact.get("confidence") or 1.0)
                mark = "" if conf >= 0.9 else f" <i>({conf:.0%})</i>"
                lines.append(
                    f"• {label}: <b>{_esc(fact['value'])}</b>{mark} <code>#{fact['id']}</code>"
                )

        suffix = ""
        flat = [line for line in lines if line.startswith("•")]
        if len(flat) > 30:
            suffix = f"\n… وفيه {len(flat) - 30} معلومة كمان (شوف /facts)."
            lines = lines[: lines.index(flat[30])] if flat[30] in lines else lines

        return (
            f"🧠 <b>اللي فاكره عنك</b> ({len(facts)})\n"
            + "\n".join(lines).strip()
            + suffix
            + "\n\nعلّمني المزيد: <code>افتكر إن ...</code>\n"
            "امسح معلومة: <code>/forget_fact 12</code>"
        )

    def topic_recall(self, chat_id: int) -> str:
        messages = self.memory.recent_user_messages(chat_id, 40)
        messages = [m for m in messages if len(m) > 2][-5:]
        if not messages:
            return "🗂 لسه مفيش محادثات محفوظة بينّا."
        lines = [f"• {_esc(m[:140])}" for m in reversed(messages)]
        return "🗂 <b>آخر اللي قلتهولي</b>\n" + "\n".join(lines)

    def prompt_block(self, chat_id: int, query: str = "") -> str:
        """نص جاهز يتحقن في system prompt لوضع الـ LLM."""
        facts = self.recall(chat_id, query, limit=12) if query else self.memory.all_facts(chat_id)[:40]
        parts: list[str] = []
        if facts:
            lines = [
                f"- [{type_of_dimension(str(fact.get('dimension') or dimension_of(str(fact['key']))))}] "
                f"{LABELS.get(str(fact['key']), str(fact['key']))}: {fact['value']}"
                for fact in facts
            ]
            parts.append("معلومات ثابتة عن المستخدم (افتكرها واستخدمها):\n" + "\n".join(lines))
        rules = self.rules(chat_id)
        if rules:
            parts.append(
                "قواعد سلوكية اتعلمتها من المستخدم (التزم بها):\n"
                + "\n".join(f"- {row['rule']}" for row in rules[:20])
            )
        return "\n\n".join(parts)

    def personalize(self, chat_id: int, reply: str) -> str:
        name = self.name(chat_id)
        if name and reply.startswith("أهلاً"):
            reply = f"أهلاً يا {name} 👋"
        return self.apply_rules(chat_id, reply)

    # ---------- تصدير البروفايل والتنظيف الدوري ----------
    def export_profile(self, chat_id: int) -> Path:
        """يكتب user_profile.md — نفس فكرة Ethan، ملف تقرأه وتعدّله بنفسك."""
        facts = self.memory.all_facts(chat_id)
        rules = self.rules(chat_id)
        out_dir = BASE_DIR / "data" / "profiles"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{chat_id}.md"

        lines = [f"# بروفايل المستخدم — {chat_id}", ""]
        grouped: dict[str, list[dict[str, Any]]] = {}
        for fact in facts:
            dim = str(fact.get("dimension") or dimension_of(str(fact["key"])))
            grouped.setdefault(type_of_dimension(dim), []).append(fact)
        for type_name in TYPE_ORDER:
            group = grouped.get(type_name)
            if not group:
                continue
            lines.append(f"## {TYPE_LABELS.get(type_name, type_name)}")
            for fact in group:
                lines.append(
                    f"- **{LABELS.get(str(fact['key']), str(fact['key']))}**: "
                    f"{fact['value']} _(ثقة {float(fact.get('confidence') or 1):.0%})_"
                )
            lines.append("")
        if rules:
            lines.append("## قواعد السلوك")
            lines.extend(f"- {row['rule']}" for row in rules)
            lines.append("")
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def consolidate_all(self) -> dict[str, int]:
        """ترقية المرصود + تقادم القديم + تصدير البروفايل — مرة كل يوم."""
        today = date.today().isoformat()
        totals = {"promoted": 0, "dormant": 0, "forgotten": 0, "profiles": 0}
        for chat_id in self.memory.all_chat_ids():
            if self.memory.get_state(chat_id, "last_consolidation") == today:
                continue
            result = self.memory.consolidate(chat_id)
            for key in ("promoted", "dormant", "forgotten"):
                totals[key] += int(result.get(key, 0))
            try:
                self.export_profile(chat_id)
                totals["profiles"] += 1
            except OSError:
                pass
            self.memory.set_state(chat_id, "last_consolidation", today)
        return totals

    def forget(self, chat_id: int, fact_id: int) -> bool:
        return self.memory.delete_fact(chat_id, fact_id)

    # ---------- سياق قصير المدى (متابعة الأوامر) ----------
    def strip_address(self, chat_id: int, text: str) -> str:
        """يشيل «يا <اسم المستخدم>» من أول الرسالة."""
        name = self.name(chat_id)
        if not name:
            return text
        return re.sub(rf"^يا\s+{re.escape(name)}\s+", "", text, flags=re.IGNORECASE)

    def remember_action(self, chat_id: int, action: dict[str, Any]) -> None:
        if action:
            self.memory.set_state(
                chat_id, "last_action", json.dumps(action, ensure_ascii=False)
            )

    def last_action(self, chat_id: int) -> dict[str, Any] | None:
        raw = self.memory.get_state(chat_id, "last_action")
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return None
        return data if isinstance(data, dict) else None

    def plan(self, chat_id: int, text: str) -> tuple[str, dict[str, Any] | None]:
        """يفهم أوامر المتابعة («كرر»، «افتحه تاني»، «وافتح كمان جوجل»).

        يرجّع (النص المُنظّف، أمر جاهز أو None).
        """
        prepared = self.strip_address(chat_id, text)
        norm = normalize(prepared, lower=True).strip()

        if REPEAT.match(norm):
            last = self.last_action(chat_id)
            if last:
                return prepared, last

        if OPEN_IT.match(norm):
            last = self.last_action(chat_id)
            if last and last.get("tool") == "open_target":
                return prepared, last

        prepared = LEADING_W.sub("", prepared)
        prepared = re.sub(r"^كمان\s+", "", prepared)
        return prepared, None
