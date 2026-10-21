"""عقل القواعد: فهم أوامر عربية بدون LLM + تعلم أوامر جديدة.

الفكرة:
1. تطبيع النص العربي (تشكيل، همزات، تاء مربوطة...).
2. مطابقة مع الأوامر المتعلَّمة (exact ثم تشابه).
3. مطابقة مع مكتبة المهارات الجاهزة (regex).
4. لو مفيش → نطلب من المستخدم يعلّمه.
"""

from __future__ import annotations

import ast
import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .memory import Memory
from .text import normalize, strip_fillers  # noqa: F401 — normalize معاد تصديره للاختبارات

# ------------------------------------------------------------------
# الأفعال
# ------------------------------------------------------------------
@dataclass
class Action:
    """حاجة واحدة ينفّذها العقل: رد، أو استدعاء أداة."""

    reply: str | None = None
    tool: str | None = None
    args: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {}
        if self.reply:
            data["reply"] = self.reply
        if self.tool:
            data["tool"] = self.tool
            data["args"] = self.args
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Action":
        return cls(
            reply=data.get("reply"),
            tool=data.get("tool"),
            args=dict(data.get("args") or {}),
        )


# ------------------------------------------------------------------
# الحاسبة الآمنة
# ------------------------------------------------------------------
_ALLOWED_NODES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Mod,
    ast.Pow,
    ast.USub,
    ast.UAdd,
    ast.Constant,
)


def safe_calc(expression: str) -> str:
    expression = expression.replace("×", "*").replace("÷", "/").replace("^", "**")
    if not re.fullmatch(r"[0-9\s\.\+\-\*\/\(\)%]+", expression):
        return "مش عارف أحسب ده — أرقام وعمليات بس (+ - * / %)."
    if len(expression) > 60:
        return "التعبير طويل أوي."
    try:
        tree = ast.parse(expression, mode="eval")
        for node in ast.walk(tree):
            if not isinstance(node, _ALLOWED_NODES):
                return "التعبير فيه حاجة مش مسموحة."
            if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
                if abs(node.value) > 10**12:
                    return "الرقم كبير أوي."
        value = eval(compile(tree, "<calc>", "eval"), {"__builtins__": {}}, {})
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        return f"= {value}"
    except ZeroDivisionError:
        return "القسمة على صفر مرفوضة."
    except Exception:  # noqa: BLE001
        return "مش قادر أحسب التعبير ده."


# ------------------------------------------------------------------
# المهارات الجاهزة
# ------------------------------------------------------------------
@dataclass(frozen=True)
class Skill:
    name: str
    patterns: tuple[str, ...]
    build: Callable[[re.Match], Action]
    description: str = ""


SKILLS: list[Skill] = []


def skill(name: str, patterns: tuple[str, ...], description: str = "") -> Callable:
    def decorator(fn: Callable[[re.Match], Action]) -> Callable[[re.Match], Action]:
        SKILLS.append(Skill(name=name, patterns=patterns, build=fn, description=description))
        return fn

    return decorator


from . import skills as _skills  # noqa: E402,F401  — يسجّل المهارات


# ------------------------------------------------------------------
# الذكاء
# ------------------------------------------------------------------
class Brain:
    SIMILARITY_THRESHOLD = 0.78
    MODEL_THRESHOLD = 0.15
    # الأفعال الخطيرة: لازم فرق واضح عن التصنيف التاني
    MODEL_MARGIN = 0.30
    # ردود كلامية بسيطة: التسامح أعلى لأن أسوأ حالة رد غلط مش عملية على الجهاز
    SAFE_MARGIN = 0.15
    SAFE_LABELS = frozenset({"greet", "who", "time", "date", "help"})

    def __init__(self, memory: Memory, model_path: Path | None = None) -> None:
        self.memory = memory
        self.model = self._load_model(model_path)
        from .skills_md import MarkdownSkills

        self.md_skills = MarkdownSkills()

    @staticmethod
    def _load_model(model_path: Path | None):
        if model_path is None:
            return None
        try:
            from .train.model import IntentModel

            return IntentModel.load(model_path)
        except Exception:  # noqa: BLE001 — numpy مش مثبت أو موديل تالف
            return None

    def think(self, chat_id: int, text: str) -> Action | None:
        # «من فضلك»/«ممكن»/«عايز» بتتشال قبل المطابقة عشان المهارات تشتغل
        light = strip_fillers(normalize(text))
        key = light.lower()
        if not key:
            return None

        # 1) أمر متعلَّم — تطابق تام
        row = self.memory.get_intent(chat_id, key)
        if row:
            self.memory.bump_intent(int(row["id"]))
            return Action.from_dict(row["action"])

        # 2) مهارات Markdown اللي المستخدم ضافها بنفسه
        md_action = self.md_skills.match(light)
        if md_action is not None:
            return md_action

        # 3) مكتبة المهارات
        for entry in SKILLS:
            for pattern in entry.patterns:
                match = re.search(pattern, light, re.IGNORECASE)
                if match:
                    return entry.build(match)

        # 4) أمر متعلَّم — تشابه (لو المستخدم صاغه بشكل مختلف)
        best: tuple[float, dict[str, Any]] | None = None
        for row in self.memory.all_intents(chat_id):
            score = _similarity(key, row["norm"])
            if best is None or score > best[0]:
                best = (score, row)
        if best and best[0] >= self.SIMILARITY_THRESHOLD:
            self.memory.bump_intent(int(best[1]["id"]))
            return Action.from_dict(best[1]["action"])

        # 5) موديل النوايا المتدرّب
        if self.model is not None:
            label, confidence, margin = self.model.predict(text)
            required = self.SAFE_MARGIN if label in self.SAFE_LABELS else self.MODEL_MARGIN
            if label != "unknown" and confidence >= self.MODEL_THRESHOLD and margin >= required:
                from .train.routes import build

                spec = build(label, text)
                if spec:
                    return Action.from_dict(spec)

        return None

    def learn(self, chat_id: int, phrase: str, action: Action) -> int:
        norm = strip_fillers(normalize(phrase)).lower()
        return self.memory.save_intent(chat_id, phrase, norm, action.to_dict())

    def forget(self, chat_id: int, intent_id: int) -> bool:
        return self.memory.delete_intent(chat_id, intent_id)

    def learned(self, chat_id: int) -> list[dict[str, Any]]:
        return self.memory.all_intents(chat_id)


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    ta, tb = set(a.split()), set(b.split())
    # لو كل كلمات الأمر المتعلَّم موجودة في طلب المستخدم (أو العكس)
    if ta and ta <= tb:
        return 1.0
    if tb and tb <= ta:
        return 0.95
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    jaccard = len(ta & tb) / max(1, len(ta | tb))
    return max(ratio, jaccard * 0.95)
