"""كائن مشترك يحمل الإعدادات والذاكرة لبقية الوحدات بدون circular imports."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from .config import Config


class Runtime:
    cfg: "Config | None" = None
    memory: Any = None
    telegram: Any = None

    def require_cfg(self) -> "Config":
        if self.cfg is None:
            raise RuntimeError("Runtime غير مهيأ — نادِ runtime.cfg قبل استخدام الأدوات.")
        return self.cfg


rt = Runtime()
