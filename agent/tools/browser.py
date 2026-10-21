"""تحكم في متصفح حقيقي عبر Playwright (اختياري).

كل عمليات المتصفح بتتنفذ في thread واحد مخصص، لأن Playwright
بيرفض استخدام الكائنات من thread غير اللي أنشأها.
"""

from __future__ import annotations

import concurrent.futures
import queue
import threading
import time
from typing import Any, Callable

from ..runtime import rt
from . import tool

_state: dict[str, Any] = {}
_queue: "queue.Queue[tuple[Callable[[], Any] | None, concurrent.futures.Future]]" = queue.Queue()
_thread: threading.Thread | None = None
_start_lock = threading.Lock()


def _worker_loop() -> None:
    while True:
        fn, future = _queue.get()
        if fn is None:
            return
        try:
            future.set_result(fn())
        except BaseException as exc:  # noqa: BLE001
            future.set_exception(exc)


def _ensure_thread() -> None:
    global _thread
    with _start_lock:
        if _thread is not None and _thread.is_alive():
            return
        _thread = threading.Thread(target=_worker_loop, name="playwright", daemon=True)
        _thread.start()


def _call(fn: Callable[[], Any], timeout: float = 90) -> Any:
    _ensure_thread()
    future: concurrent.futures.Future = concurrent.futures.Future()
    _queue.put((fn, future))
    return future.result(timeout=timeout)


def _page():
    cfg = rt.require_cfg()
    if not cfg.browser_enabled:
        raise RuntimeError(
            "المتصفح متوقف. فعّله بـ BROWSER_ENABLED=true في .env وثبّت: "
            "py -m pip install playwright && py -m playwright install chromium"
        )
    if _state.get("page") is not None:
        return _state["page"]
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright مش مثبّت: py -m pip install playwright && py -m playwright install chromium"
        ) from exc

    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=cfg.browser_headless)
    context = browser.new_context(
        viewport={"width": 1366, "height": 900},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
    )
    page = context.new_page()
    page.set_default_timeout(25_000)
    _state.update(pw=pw, browser=browser, context=context, page=page)
    return page


def _safe(fn: Callable[[], Any]) -> str:
    try:
        return str(_call(fn))
    except Exception as exc:  # noqa: BLE001
        return f"خطأ في المتصفح: {type(exc).__name__}: {exc}"


@tool(
    "browser_open",
    "فتح رابط في متصفح حقيقي (Chromium) والرجوع لعنوان الصفحة.",
    {
        "type": "object",
        "properties": {"url": {"type": "string", "description": "الرابط."}},
        "required": ["url"],
    },
    side_effect=True,
)
def browser_open(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        return "خطأ: الرابط لازم يبدأ بـ http:// أو https://"

    def action() -> str:
        page = _page()
        page.goto(url, wait_until="domcontentloaded")
        return f"تم فتح: {page.title()}\n{page.url}"

    return _safe(action)


@tool(
    "browser_text",
    "قراءة نص الصفحة الحالية أو عنصر معيّن فيها (CSS selector).",
    {
        "type": "object",
        "properties": {
            "selector": {"type": "string", "description": "CSS selector (افتراضي body)."},
            "max_chars": {"type": "integer", "description": "أقصى طول."},
        },
    },
    cacheable=True,
)
def browser_text(selector: str = "body", max_chars: int = 8000) -> str:
    limit = max(500, min(int(max_chars or 8000), 20000))

    return _safe(lambda: (_page().inner_text(selector) or "")[:limit])


@tool(
    "browser_click",
    "الضغط على عنصر في الصفحة.",
    {
        "type": "object",
        "properties": {"selector": {"type": "string", "description": "CSS selector للعنصر."}},
        "required": ["selector"],
    },
    side_effect=True,
)
def browser_click(selector: str) -> str:
    def action() -> str:
        page = _page()
        page.click(selector)
        time.sleep(0.5)
        return f"تم الضغط على {selector} — العنوان الحالي: {page.title()}"

    return _safe(action)


@tool(
    "browser_fill",
    "كتابة نص في حقل إدخال.",
    {
        "type": "object",
        "properties": {
            "selector": {"type": "string", "description": "CSS selector للحقل."},
            "value": {"type": "string", "description": "النص."},
            "submit": {"type": "boolean", "description": "اضغط Enter بعد الكتابة."},
        },
        "required": ["selector", "value"],
    },
    side_effect=True,
)
def browser_fill(selector: str, value: str, submit: bool = False) -> str:
    def action() -> str:
        page = _page()
        page.fill(selector, value)
        if submit:
            page.press(selector, "Enter")
            page.wait_for_load_state("domcontentloaded")
        return f"تمت الكتابة في {selector}."

    return _safe(action)


@tool(
    "browser_screenshot",
    "أخذ سكرين شوت للصفحة وحفظها في مجلد screenshots.",
    {
        "type": "object",
        "properties": {"name": {"type": "string", "description": "اسم الملف بدون امتداد."}},
    },
    side_effect=True,
)
def browser_screenshot(name: str = "shot") -> str:
    cfg = rt.require_cfg()
    target = cfg.workspace / "screenshots" / f"{name or 'shot'}.png"

    def action() -> str:
        target.parent.mkdir(parents=True, exist_ok=True)
        _page().screenshot(path=str(target), full_page=True)
        return f"تم الحفظ: {target}"

    return _safe(action)


@tool(
    "browser_eval",
    "تنفيذ JavaScript في الصفحة الحالية (بيحتاج موافقة).",
    {
        "type": "object",
        "properties": {"script": {"type": "string", "description": "كود JS."}},
        "required": ["script"],
    },
    side_effect=True,
)
def browser_eval(script: str) -> str:
    return _safe(lambda: _page().evaluate(script))


def shutdown() -> None:
    """إغلاق المتصفح بأمان."""
    if _state.get("browser") is None:
        return

    def action() -> str:
        try:
            _state["browser"].close()
            _state["pw"].stop()
        finally:
            _state.clear()
        return "تم إغلاق المتصفح."

    try:
        _call(action, timeout=20)
    except Exception:  # noqa: BLE001
        pass
