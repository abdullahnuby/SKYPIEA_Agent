"""أدوات الملفات — كل المسارات محصورة في مساحة العمل افتراضيًا."""

from __future__ import annotations

from pathlib import Path

from ..runtime import rt
from . import tool

MAX_READ = 40_000


def _resolve(raw: str | None) -> Path:
    cfg = rt.require_cfg()
    p = Path(raw or ".").expanduser()
    if not p.is_absolute():
        p = cfg.workspace / p
    return p.resolve()


def _describe(path: Path) -> str:
    try:
        size = path.stat().st_size
    except OSError:
        size = -1
    return f"{path} ({size} بايت)" if size >= 0 else str(path)


@tool(
    "read_file",
    "قراءة محتوى ملف نصي.",
    {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "مسار الملف (نسبي لمساحة العمل)."}},
        "required": ["path"],
    },
    cacheable=True,
)
def read_file(path: str) -> str:
    target = _resolve(path)
    if not target.is_file():
        return f"الملف غير موجود: {target}"
    if target.stat().st_size > 2_000_000:
        return f"الملف كبير جدًا ({target.stat().st_size} بايت). استخدم shell لقراءة جزء منه."
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"خطأ في القراءة: {exc}"
    if len(text) > MAX_READ:
        return text[:MAX_READ] + f"\n... [باقي الملف {len(text) - MAX_READ} حرف]"
    return text or "(ملف فاضي)"


@tool(
    "write_file",
    "كتابة/إنشاء ملف نصي (يستبدل المحتوى بالكامل).",
    {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "مسار الملف."},
            "content": {"type": "string", "description": "المحتوى الكامل."},
        },
        "required": ["path", "content"],
    },
    side_effect=True,
)
def write_file(path: str, content: str) -> str:
    target = _resolve(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    except OSError as exc:
        return f"خطأ في الكتابة: {exc}"
    return f"تمت الكتابة: {_describe(target)}"


@tool(
    "list_dir",
    "سرد محتويات مجلد.",
    {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "المجلد (افتراضي: جذر مساحة العمل)."}},
    },
    cacheable=True,
)
def list_dir(path: str = ".") -> str:
    target = _resolve(path)
    if not target.is_dir():
        return f"المجلد غير موجود: {target}"
    lines = []
    for entry in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
        if entry.is_dir():
            lines.append(f"[مجلد] {entry.name}/")
        else:
            try:
                size = entry.stat().st_size
            except OSError:
                size = 0
            lines.append(f"[ملف]  {entry.name}  ({size} بايت)")
    return "\n".join(lines) or "(مجلد فاضي)"


@tool(
    "find_files",
    "البحث عن ملفات بالاسم أو النمط (glob) داخل مجلد.",
    {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "نمط مثل *.py أو **/*.md"},
            "root": {"type": "string", "description": "المجلد اللي نبدأ منه."},
            "limit": {"type": "integer", "description": "أقصى عدد نتائج (افتراضي 100)."},
        },
        "required": ["pattern"],
    },
    cacheable=True,
)
def find_files(pattern: str, root: str = ".", limit: int = 100) -> str:
    base = _resolve(root)
    if not base.is_dir():
        return f"المجلد غير موجود: {base}"
    results = []
    for match in base.glob(pattern):
        results.append(str(match.relative_to(base)))
        if len(results) >= max(1, min(int(limit or 100), 500)):
            break
    return "\n".join(results) if results else "مفيش نتائج."


@tool(
    "delete_file",
    "حذف ملف أو مجلد (بيحتاج موافقة).",
    {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "المسار المطلوب حذفه."}},
        "required": ["path"],
    },
    side_effect=True,
)
def delete_file(path: str) -> str:
    target = _resolve(path)
    if not target.exists():
        return f"غير موجود: {target}"
    try:
        if target.is_dir():
            # حذف متكرر يدوي — مفيش shutil.rmtree على مسار خارج المساحة
            for child in sorted(target.rglob("*"), key=lambda p: len(p.parts), reverse=True):
                if child.is_file() or child.is_symlink():
                    child.unlink(missing_ok=True)
                elif child.is_dir():
                    child.rmdir()
            target.rmdir()
        else:
            target.unlink()
    except OSError as exc:
        return f"فشل الحذف: {exc}"
    return f"تم الحذف: {target}"
