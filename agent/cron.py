"""محلل cron بسيط (5 حقول) — مستوحى من ethan/scheduler/cron.py بدون APScheduler.

الصيغة: ``دقيقة ساعة يوم-الشهر شهر يوم-الأسبوع``

مدعوم:
- ``*``
- ``*/5``
- ``1-30`` و ``1-30/5``
- قوائم ``1,15,30``
- أسماء الشهور/الأيام الإنجليزية (mon, jan...)

يوم الأسبوع: 0 أو 7 = الأحد، 1 = الاثنين ... 6 = السبت.
لو يوم الشهر ويوم الأسبوع الاتنين متحددين، بيتطابق أي واحد فيهم (زي cron).
"""

from __future__ import annotations

import time
from datetime import datetime

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_DAYS = {
    "sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6,
}

_FIELDS = (
    ("minute", 0, 59),
    ("hour", 0, 23),
    ("day", 1, 31),
    ("month", 1, 12),
    ("weekday", 0, 7),
)


def _parse_value(token: str, names: dict[str, int] | None = None) -> int:
    token = token.strip().lower()
    if names and token in names:
        return names[token]
    return int(token)


def _parse_field(raw: str, low: int, high: int, names: dict[str, int] | None = None) -> tuple[set[int], bool]:
    """يرجّع (القيم المسموحة، هل الحقل متحدد مش *)."""
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("حقل cron فاضي")
    values: set[int] = set()
    restricted = raw != "*"
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        step = 1
        if "/" in part:
            base, _, step_raw = part.partition("/")
            step = int(step_raw)
            if step <= 0:
                raise ValueError("خطوة cron لازم تكون أكبر من صفر")
        else:
            base = part
        if base == "*":
            start, end = low, high
        elif "-" in base:
            start_raw, _, end_raw = base.partition("-")
            start = _parse_value(start_raw, names)
            end = _parse_value(end_raw, names)
        else:
            start = _parse_value(base, names)
            end = start
        if start > end:
            start, end = end, start
        if start < low or end > high:
            raise ValueError(f"قيمة cron خارج المدى {low}-{high}: {part}")
        values.update(range(start, end + 1, step))
    if not values:
        raise ValueError("حقل cron مافيهوش قيم")
    return values, restricted


class CronSpec:
    def __init__(self, expression: str) -> None:
        parts = (expression or "").split()
        if len(parts) != 5:
            raise ValueError("cron لازم يكون 5 حقول: دقيقة ساعة يوم شهر يوم-الأسبوع")
        self.expression = " ".join(parts)
        self.minutes, _ = _parse_field(parts[0], 0, 59)
        self.hours, _ = _parse_field(parts[1], 0, 23)
        self.days, self.day_restricted = _parse_field(parts[2], 1, 31)
        self.months, _ = _parse_field(parts[3], 1, 12, _MONTHS)
        self.weekdays, self.weekday_restricted = _parse_field(parts[4], 0, 7, _DAYS)
        # 7 = الأحد كمان
        if 7 in self.weekdays:
            self.weekdays.add(0)

    def matches(self, moment: datetime) -> bool:
        if moment.minute not in self.minutes:
            return False
        if moment.hour not in self.hours:
            return False
        if moment.month not in self.months:
            return False
        # Python: Monday=0 ... Sunday=6 → cron: Sunday=0 ... Saturday=6
        cron_dow = (moment.weekday() + 1) % 7
        day_ok = moment.day in self.days
        dow_ok = cron_dow in self.weekdays
        if self.day_restricted and self.weekday_restricted:
            if not (day_ok or dow_ok):
                return False
        elif self.day_restricted:
            if not day_ok:
                return False
        elif self.weekday_restricted:
            if not dow_ok:
                return False
        return True

    def next_run(self, after: float | None = None) -> float:
        """أول دقيقة مطابقة بعد الوقت المحدد (أو الآن)."""
        after = time.time() if after is None else float(after)
        # نبدأ من أول دقيقة كاملة بعد after
        start = datetime.fromtimestamp(after).replace(second=0, microsecond=0)
        start = datetime.fromtimestamp((int(start.timestamp()) // 60 + 1) * 60)
        for offset in range(0, 366 * 24 * 60 + 1):
            moment = datetime.fromtimestamp(start.timestamp() + offset * 60)
            if self.matches(moment):
                return moment.timestamp()
        raise ValueError("مفيش تشغيل مطابق خلال سنة — راجع تعبير cron")


def next_run(expression: str, after: float | None = None) -> float:
    return CronSpec(expression).next_run(after)


def validate(expression: str) -> str:
    """يرجّع التعبير المنظّم أو يرفع ValueError."""
    return CronSpec(expression).expression
