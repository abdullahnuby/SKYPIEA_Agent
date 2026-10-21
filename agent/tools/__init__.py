"""سجل الأدوات (Tools) — أي ملف هنا بيسجّل أدواته تلقائيًا."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from typing import Any, Callable

MAX_RESULT_CHARS = 8000


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    handler: Callable[..., str]
    # بيانات وصفية مستوحاة من Ethan: بتساعدنا نعرف الأداة خطيرة ولا لأ،
    # ونتيجة هل تتقصّر ولا لأ.
    side_effect: bool = False
    cacheable: bool = False
    fast_path: bool = True
    no_compress: bool = False


TOOLS: dict[str, Tool] = {}


def tool(
    name: str,
    description: str,
    parameters: dict,
    *,
    side_effect: bool = False,
    cacheable: bool = False,
    fast_path: bool = True,
    no_compress: bool = False,
) -> Callable:
    """ديكوراتور لتسجيل أداة + بياناتها الوصفية."""

    def decorator(fn: Callable[..., str]) -> Callable[..., str]:
        TOOLS[name] = Tool(
            name=name,
            description=description,
            parameters=parameters,
            handler=fn,
            side_effect=side_effect,
            cacheable=cacheable,
            fast_path=fast_path,
            no_compress=no_compress,
        )
        return fn

    return decorator


def definitions() -> list[dict[str, Any]]:
    """الصيغة اللي الموديل بيفهمها."""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in TOOLS.values()
    ]


def available() -> list[str]:
    return sorted(TOOLS)


def describe() -> list[dict[str, Any]]:
    """وصف مختصر لكل أداة — لـ /tools وللسياق."""
    return [
        {
            "name": item.name,
            "description": item.description,
            "side_effect": item.side_effect,
            "cacheable": item.cacheable,
        }
        for item in TOOLS.values()
    ]


def truncate(text: str, limit: int = MAX_RESULT_CHARS) -> str:
    """ضغط النتيجة: أول 75% + آخر 20% بدل ما نقطع الذيل كله."""
    text = text or ""
    if len(text) <= limit:
        return text
    head = max(1, int(limit * 0.75))
    tail = max(1, int(limit * 0.20))
    omitted = len(text) - head - tail
    return (
        text[:head]
        + f"\n... [اتقص {omitted} حرف من النص الأصلي] ...\n"
        + text[-tail:]
    )


def _cast(value: Any, annotation: Any) -> Any:
    """تحويل بسيط: الموديلات بتبعت أرقام كنصوص أحيانًا."""
    if annotation is inspect.Parameter.empty:
        return value
    target = annotation if not isinstance(annotation, str) else annotation
    try:
        if target in (int, "int"):
            return int(value)
        if target in (float, "float"):
            return float(value)
        if target in (bool, "bool"):
            if isinstance(value, str):
                return value.strip().lower() in {"1", "true", "yes", "on"}
            return bool(value)
        if target in (str, "str"):
            return str(value)
    except (TypeError, ValueError):
        return value
    return value


async def run(name: str, args: dict[str, Any]) -> str:
    entry = TOOLS.get(name)
    if entry is None:
        return f"خطأ: أداة غير معروفة اسمها {name}. المتاح: {', '.join(available())}"

    kwargs: dict[str, Any] = {}
    try:
        for param_name, param in inspect.signature(entry.handler).parameters.items():
            if param_name in args:
                kwargs[param_name] = _cast(args[param_name], param.annotation)
    except (TypeError, ValueError) as exc:
        return f"خطأ في معاملات {name}: {exc}"

    try:
        result = await asyncio.to_thread(entry.handler, **kwargs)
        return truncate(str(result))
    except TypeError as exc:
        return f"خطأ في استدعاء {name}: {exc}"
    except Exception as exc:  # noqa: BLE001 — نرجّع الخطأ للموديل بدل ما نكسر الجلسة
        return f"خطأ أثناء تنفيذ {name}: {type(exc).__name__}: {exc}"


# تسجيل الأدوات عند الاستيراد
from . import browser, email, files, shell, system, web  # noqa: E402,F401
