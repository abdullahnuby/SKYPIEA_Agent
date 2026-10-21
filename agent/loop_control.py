"""كشف الدوران في مكانه في وضع الـ LLM — مستوحى من ethan/core/loop_control.py.

الفكرة: لو الموديل كرر نفس استدعاء الأداة بنفس المعاملات 3 مرات، أو كرر نفس
الخطأ مرتين، بنحقن رسالة تشخيص إجبارية. لو لسه بيكرر بعد محاولتين، بنقفل
الأدوات ونطلب منه يلخّص اللي حصل بدل ما يلف لحد آخر خطوة.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass
class LoopGuard:
    stuck_window: int = 3
    error_window: int = 2
    max_reflections: int = 2
    _signatures: list[str] = field(default_factory=list)
    _errored: list[bool] = field(default_factory=list)
    reflections_used: int = 0

    def record(self, tool_calls: list[dict], results: list[str]) -> None:
        parts = []
        for call in tool_calls:
            name = (call.get("function") or {}).get("name", "")
            args = (call.get("function") or {}).get("arguments") or "{}"
            if not isinstance(args, str):
                args = json.dumps(args, sort_keys=True, ensure_ascii=False)
            parts.append(f"{name}|{args}")
        self._signatures.append("\n".join(sorted(parts)))
        self._errored.append(
            any(str(r).startswith("⛔") or str(r).startswith("خطأ") for r in results)
        )

    def stuck(self) -> bool:
        sigs = self._signatures
        if len(sigs) >= self.error_window:
            tail = sigs[-self.error_window :]
            if len(set(tail)) == 1 and all(self._errored[-self.error_window :]):
                return True
        if len(sigs) >= self.stuck_window:
            tail = sigs[-self.stuck_window :]
            if len(set(tail)) == 1:
                return True
        return False

    def mark_reflected(self) -> None:
        self.reflections_used += 1

    def exhausted(self) -> bool:
        return self.reflections_used >= self.max_reflections

    def last_signature(self, limit: int = 240) -> str:
        if not self._signatures:
            return ""
        value = self._signatures[-1]
        return value[:limit] + ("…" if len(value) > limit else "")


def reflection_message(guard: LoopGuard, last_result: str = "") -> str:
    hint = f"\nآخر نتيجة (مختصرة): {last_result[:240]}" if last_result else ""
    return (
        "⚠️ تحذير: أنت بتكرر نفس الخطوة من غير تقدم.\n"
        f"الاستدعاء المتكرر: {guard.last_signature()}{hint}\n"
        "قبل ما تكمل، اعمل تشخيص سريع:\n"
        "1. إيه اللي بتحاول تحله؟\n"
        "2. ليه نفس المحاولة مش بتنجح؟\n"
        "3. إيه طريقين مختلفين لسه ما جربتهمش؟\n"
        "4. هتختار أنهي واحد دلوقتي وليه؟\n"
        "ممنوع تعيد نفس الأداة بنفس المعاملات. غيّر الأسلوب أو اطلب من المستخدم توضيح."
    )


def finalize_suffix() -> str:
    return (
        "\n\n[نظام: توقفت عن استخدام الأدوات. لخّص للمستخدم باختصار: "
        "① إيه اللي اتعمل فعلًا، ② إيه اللي فاضل، ③ إيه اللي محتاج منه عشان تكمل. "
        "ممنوع تستدعي أي أداة في الرد ده.]"
    )
