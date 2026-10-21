"""تخزين المحادثات والمهام وسجل التدقيق في SQLite."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     INTEGER NOT NULL,
    role        TEXT NOT NULL,
    payload     TEXT NOT NULL,
    created_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id, id);

CREATE TABLE IF NOT EXISTS audit (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     INTEGER,
    tool        TEXT NOT NULL,
    args        TEXT,
    decision    TEXT,
    result      TEXT,
    created_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id       INTEGER NOT NULL,
    prompt        TEXT NOT NULL,
    interval_sec  INTEGER NOT NULL,
    next_run      REAL NOT NULL,
    enabled       INTEGER NOT NULL DEFAULT 1,
    created_at    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS intents (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     INTEGER NOT NULL,
    phrase      TEXT NOT NULL,
    norm        TEXT NOT NULL,
    action      TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT 'learned',
    hits        INTEGER NOT NULL DEFAULT 0,
    created_at  REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_intents_unique ON intents(chat_id, norm);

CREATE TABLE IF NOT EXISTS facts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     INTEGER NOT NULL,
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT '',
    hits        INTEGER NOT NULL DEFAULT 0,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL,
    dimension   TEXT NOT NULL DEFAULT '',
    evidence    TEXT NOT NULL DEFAULT 'explicit',
    confidence  REAL NOT NULL DEFAULT 1.0,
    status      TEXT NOT NULL DEFAULT 'active',
    scope       TEXT NOT NULL DEFAULT 'user',
    quote       TEXT NOT NULL DEFAULT '',
    session_id  TEXT NOT NULL DEFAULT '',
    valid_until REAL,
    superseded_by INTEGER,
    last_recalled_at REAL,
    recall_count INTEGER NOT NULL DEFAULT 0,
    structured  TEXT NOT NULL DEFAULT '{}'
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_facts_unique ON facts(chat_id, key, value);
CREATE INDEX IF NOT EXISTS idx_facts_chat ON facts(chat_id, id);

CREATE TABLE IF NOT EXISTS memory_evidence (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     INTEGER NOT NULL,
    fact_id     INTEGER NOT NULL,
    session_id  TEXT NOT NULL,
    evidence    TEXT NOT NULL DEFAULT 'explicit',
    quote       TEXT NOT NULL DEFAULT '',
    created_at  REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_evidence_unique
    ON memory_evidence(fact_id, session_id, quote);
CREATE INDEX IF NOT EXISTS idx_evidence_fact ON memory_evidence(fact_id);

CREATE TABLE IF NOT EXISTS procedures (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     INTEGER NOT NULL,
    rule        TEXT NOT NULL,
    context     TEXT NOT NULL DEFAULT '',
    hits        INTEGER NOT NULL DEFAULT 0,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_procedures_unique ON procedures(chat_id, rule);

CREATE TABLE IF NOT EXISTS state (
    chat_id     INTEGER NOT NULL,
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,
    updated_at  REAL NOT NULL,
    PRIMARY KEY (chat_id, key)
);
"""

# أعمدة اتضافت بعد أول إصدار — بنضيفها للقواعد القديمة بدون ما نمسح البيانات.
_FACT_MIGRATIONS = {
    "dimension": "TEXT NOT NULL DEFAULT ''",
    "evidence": "TEXT NOT NULL DEFAULT 'explicit'",
    "confidence": "REAL NOT NULL DEFAULT 1.0",
    "status": "TEXT NOT NULL DEFAULT 'active'",
    "scope": "TEXT NOT NULL DEFAULT 'user'",
    "quote": "TEXT NOT NULL DEFAULT ''",
    "session_id": "TEXT NOT NULL DEFAULT ''",
    "valid_until": "REAL",
    "superseded_by": "INTEGER",
    "last_recalled_at": "REAL",
    "recall_count": "INTEGER NOT NULL DEFAULT 0",
    "structured": "TEXT NOT NULL DEFAULT '{}'",
}

_TASK_MIGRATIONS = {
    "cron_expr": "TEXT NOT NULL DEFAULT ''",
}

KEEP_FIELDS = ("role", "content", "name", "tool_calls", "tool_call_id")


def _clean(message: dict) -> dict:
    return {k: v for k, v in message.items() if k in KEEP_FIELDS and v is not None}


class Memory:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(SCHEMA)
            self._migrate()
            self._db.commit()

    def _migrate(self) -> None:
        """ترقية قواعد البيانات القديمة (إضافة أعمدة ناقصة فقط)."""
        for table, additions in (("facts", _FACT_MIGRATIONS), ("tasks", _TASK_MIGRATIONS)):
            cols = {str(row["name"]) for row in self._db.execute(f"PRAGMA table_info({table})")}
            for name, ddl in additions.items():
                if name not in cols:
                    self._db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
        # الفهرس ده بيعتمد على عمود status اللي بيتضاف فوق للقواعد القديمة.
        self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_facts_status ON facts(chat_id, status)"
        )

    # ---------- المحادثات ----------
    def add_message(self, chat_id: int, message: dict) -> None:
        payload = json.dumps(_clean(message), ensure_ascii=False)
        with self._lock:
            self._db.execute(
                "INSERT INTO messages (chat_id, role, payload, created_at) VALUES (?,?,?,?)",
                (chat_id, message.get("role", "unknown"), payload, time.time()),
            )
            self._db.commit()

    def history(self, chat_id: int, limit: int = 40) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT payload FROM messages WHERE chat_id=? ORDER BY id DESC LIMIT ?",
                (chat_id, limit),
            ).fetchall()
        return [json.loads(r["payload"]) for r in reversed(rows)]

    def reset(self, chat_id: int) -> int:
        with self._lock:
            cur = self._db.execute("DELETE FROM messages WHERE chat_id=?", (chat_id,))
            self._db.commit()
        return cur.rowcount

    # ---------- التدقيق ----------
    def audit(
        self,
        chat_id: int | None,
        tool: str,
        args: dict,
        decision: str,
        result: str,
    ) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO audit (chat_id, tool, args, decision, result, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (
                    chat_id,
                    tool,
                    json.dumps(args, ensure_ascii=False)[:2000],
                    decision,
                    (result or "")[:2000],
                    time.time(),
                ),
            )
            self._db.commit()

    def recent_audit(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ---------- المهام المجدولة ----------
    def add_task(
        self,
        chat_id: int,
        prompt: str,
        interval_sec: int,
        *,
        cron_expr: str = "",
        next_run: float | None = None,
    ) -> int:
        now = time.time()
        first_run = now + interval_sec if next_run is None else next_run
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO tasks (chat_id, prompt, interval_sec, next_run, enabled, created_at, cron_expr) "
                "VALUES (?,?,?,?,1,?,?)",
                (chat_id, prompt, interval_sec, first_run, now, cron_expr),
            )
            self._db.commit()
        return int(cur.lastrowid)

    def due_tasks(self, now: float | None = None) -> list[dict[str, Any]]:
        now = now or time.time()
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM tasks WHERE enabled=1 AND next_run<=? ORDER BY next_run",
                (now,),
            ).fetchall()
        return [dict(r) for r in rows]

    def mark_task_run(self, task_id: int, interval_sec: int, *, next_run: float | None = None) -> None:
        target = time.time() + max(60, interval_sec) if next_run is None else next_run
        with self._lock:
            self._db.execute(
                "UPDATE tasks SET next_run=? WHERE id=?", (target, task_id)
            )
            self._db.commit()

    def list_tasks(self, chat_id: int) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM tasks WHERE chat_id=? AND enabled=1 ORDER BY id",
                (chat_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_task(self, chat_id: int, task_id: int) -> bool:
        with self._lock:
            cur = self._db.execute(
                "DELETE FROM tasks WHERE id=? AND chat_id=?", (task_id, chat_id)
            )
            self._db.commit()
        return cur.rowcount > 0

    # ---------- الأوامر المتعلَّمة ----------
    def save_intent(
        self,
        chat_id: int,
        phrase: str,
        norm: str,
        action: dict[str, Any],
        source: str = "learned",
    ) -> int:
        payload = json.dumps(action, ensure_ascii=False)
        with self._lock:
            row = self._db.execute(
                "SELECT id FROM intents WHERE chat_id=? AND norm=?", (chat_id, norm)
            ).fetchone()
            if row:
                self._db.execute(
                    "UPDATE intents SET phrase=?, action=?, source=? WHERE id=?",
                    (phrase, payload, source, row["id"]),
                )
                self._db.commit()
                return int(row["id"])
            cur = self._db.execute(
                "INSERT INTO intents (chat_id, phrase, norm, action, source, hits, created_at) "
                "VALUES (?,?,?,?,?,0,?)",
                (chat_id, phrase, norm, payload, source, time.time()),
            )
            self._db.commit()
        return int(cur.lastrowid)

    def get_intent(self, chat_id: int, norm: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM intents WHERE chat_id=? AND norm=?", (chat_id, norm)
            ).fetchone()
        return _intent_row(row) if row else None

    def all_intents(self, chat_id: int) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM intents WHERE chat_id=? ORDER BY hits DESC, id", (chat_id,)
            ).fetchall()
        return [_intent_row(r) for r in rows]

    def bump_intent(self, intent_id: int) -> None:
        with self._lock:
            self._db.execute("UPDATE intents SET hits=hits+1 WHERE id=?", (intent_id,))
            self._db.commit()

    def delete_intent(self, chat_id: int, intent_id: int) -> bool:
        with self._lock:
            cur = self._db.execute(
                "DELETE FROM intents WHERE id=? AND chat_id=?", (intent_id, chat_id)
            )
            self._db.commit()
        return cur.rowcount > 0

    # ---------- الذاكرة الشخصية ----------
    def save_fact(
        self,
        chat_id: int,
        key: str,
        value: str,
        source: str = "",
        *,
        scalar: bool = False,
        dimension: str = "",
        evidence: str = "explicit",
        confidence: float = 1.0,
        quote: str = "",
        session_id: str = "",
        status: str = "active",
        scope: str = "user",
        valid_until: float | None = None,
        structured: dict[str, Any] | None = None,
    ) -> int:
        """يحفظ معلومة عن المستخدم مع دليلها (quote) ومستوى الثقة.

        scalar = قيمة واحدة بس (الاسم، المدينة...). القيمة القديمة بتتحول
        ``superseded`` مش بتتمسح، عشان يبقى عندنا تاريخ تغيّر الحقائق.
        """
        now = time.time()
        structured_json = json.dumps(structured or {}, ensure_ascii=False)
        with self._lock:
            # نفس المفتاح + نفس القيمة: تحديث/تقوية (حتى لو كانت superseded قديمة)
            row = self._db.execute(
                "SELECT * FROM facts WHERE chat_id=? AND key=? AND value=? ORDER BY id DESC LIMIT 1",
                (chat_id, key, value),
            ).fetchone()

            if row:
                fact_id = int(row["id"])
                old_status = str(row["status"] or "active")
                # explicit/corrected بيرقّي المعلومة المرصودة، والعكس مابينزلهاش
                new_status = old_status
                if status == "active" and old_status in {"pending", "dormant", "forgotten", "superseded"}:
                    new_status = "active"
                if evidence in {"explicit", "corrected"}:
                    new_status = "active"
                new_conf = max(float(row["confidence"] or 0.0), float(confidence))
                new_evidence = evidence
                if old_status == "active" and evidence == "observed":
                    new_evidence = str(row["evidence"] or "explicit")
                    new_conf = float(row["confidence"] or 1.0)
                self._db.execute(
                    "UPDATE facts SET updated_at=?, source=?, hits=hits+1, confidence=?, "
                    "evidence=?, status=?, quote=?, session_id=?, dimension=?, scope=?, "
                    "valid_until=?, superseded_by=NULL, structured=? WHERE id=?",
                    (
                        now, source, new_conf, new_evidence, new_status, quote,
                        session_id, dimension or row["dimension"], scope, valid_until,
                        structured_json, fact_id,
                    ),
                )
                if scalar:
                    self._db.execute(
                        "UPDATE facts SET status='superseded', superseded_by=?, updated_at=? "
                        "WHERE chat_id=? AND key=? AND id<>? AND status='active'",
                        (fact_id, now, chat_id, key, fact_id),
                    )
            else:
                cur = self._db.execute(
                    "INSERT INTO facts (chat_id, key, value, source, hits, created_at, updated_at, "
                    "dimension, evidence, confidence, status, scope, quote, session_id, "
                    "valid_until, structured) VALUES (?,?,?,?,0,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        chat_id, key, value, source, now, now, dimension, evidence,
                        confidence, status, scope, quote, session_id, valid_until,
                        structured_json,
                    ),
                )
                fact_id = int(cur.lastrowid)
                if scalar:
                    # القيم القديمة بتتحفظ في التاريخ لكن مش بتظهر في البروفايل
                    self._db.execute(
                        "UPDATE facts SET status='superseded', superseded_by=?, updated_at=? "
                        "WHERE chat_id=? AND key=? AND id<>? AND status='active'",
                        (fact_id, now, chat_id, key, fact_id),
                    )

            self._db.execute(
                "INSERT OR IGNORE INTO memory_evidence "
                "(chat_id, fact_id, session_id, evidence, quote, created_at) VALUES (?,?,?,?,?,?)",
                (chat_id, fact_id, session_id, evidence, quote[:1000], now),
            )
            self._db.commit()
        return fact_id

    def add_evidence(
        self, chat_id: int, fact_id: int, session_id: str, evidence: str, quote: str
    ) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR IGNORE INTO memory_evidence "
                "(chat_id, fact_id, session_id, evidence, quote, created_at) VALUES (?,?,?,?,?,?)",
                (chat_id, fact_id, session_id, evidence, quote[:1000], time.time()),
            )
            self._db.commit()

    def fact_sessions(self, fact_id: int) -> int:
        with self._lock:
            row = self._db.execute(
                "SELECT COUNT(DISTINCT session_id) AS n FROM memory_evidence "
                "WHERE fact_id=? AND session_id<>''",
                (fact_id,),
            ).fetchone()
        return int(row["n"]) if row else 0

    def all_facts(self, chat_id: int, *, include_inactive: bool = False) -> list[dict[str, Any]]:
        now = time.time()
        with self._lock:
            if include_inactive:
                rows = self._db.execute(
                    "SELECT * FROM facts WHERE chat_id=? ORDER BY key, id", (chat_id,)
                ).fetchall()
            else:
                rows = self._db.execute(
                    "SELECT * FROM facts WHERE chat_id=? AND status='active' "
                    "AND (valid_until IS NULL OR valid_until>?) ORDER BY key, id",
                    (chat_id, now),
                ).fetchall()
        return [dict(r) for r in rows]

    def get_facts(self, chat_id: int, key: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM facts WHERE chat_id=? AND key=? AND status='active' "
                "AND (valid_until IS NULL OR valid_until>?) ORDER BY id",
                (chat_id, key, time.time()),
            ).fetchall()
        return [dict(r) for r in rows]

    def pending_facts(self, chat_id: int) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM facts WHERE chat_id=? AND status='pending' ORDER BY id",
                (chat_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def promote_pending(self, chat_id: int, threshold: int = 2) -> int:
        """يرقّي المعلومة المرصودة بعد ما تتكرر في جلسات مستقلة."""
        promoted = 0
        now = time.time()
        for fact in self.pending_facts(chat_id):
            if self.fact_sessions(int(fact["id"])) < threshold:
                continue
            with self._lock:
                self._db.execute(
                    "UPDATE facts SET status='active', evidence='inferred', "
                    "confidence=MAX(confidence, 0.7), updated_at=? WHERE id=?",
                    (now, int(fact["id"])),
                )
                self._db.commit()
            promoted += 1
        return promoted

    def mark_recalled(self, fact_ids: list[int]) -> None:
        if not fact_ids:
            return
        now = time.time()
        with self._lock:
            self._db.executemany(
                "UPDATE facts SET last_recalled_at=?, recall_count=recall_count+1 WHERE id=?",
                [(now, int(fid)) for fid in fact_ids],
            )
            self._db.commit()

    def consolidate(self, chat_id: int, now: float | None = None) -> dict[str, int]:
        """تنظيف دوري: ترقية المرصود + إخفاء القديم + نسيان المسنون.

        القواعد مستوحاة من Ethan: الهوية والتفضيلات والعلاقات معفاة من التقادم،
        النشاط والقرارات بتنام بعد 90 يوم وتُنسى بعد 180 يوم.
        """
        now = now or time.time()
        result = {"promoted": self.promote_pending(chat_id), "dormant": 0, "forgotten": 0}
        exempt = ("identity", "preference", "relationship")
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM facts WHERE chat_id=? AND status='active'", (chat_id,)
            ).fetchall()
            dormant_ids: list[int] = []
            for row in rows:
                dim = str(row["dimension"] or "")
                if not dim or dim.split(".", 1)[0] in exempt:
                    continue
                anchor = max(
                    float(row["updated_at"] or 0.0),
                    float(row["created_at"] or 0.0),
                    float(row["last_recalled_at"] or 0.0),
                )
                if anchor < now - 90 * 86400:
                    dormant_ids.append(int(row["id"]))
            if dormant_ids:
                self._db.executemany(
                    "UPDATE facts SET status='dormant' WHERE id=?",
                    [(fid,) for fid in dormant_ids],
                )
                result["dormant"] = len(dormant_ids)
            forgotten_ids: list[int] = []
            for row in self._db.execute(
                "SELECT * FROM facts WHERE chat_id=? AND status='dormant'", (chat_id,)
            ).fetchall():
                anchor = max(
                    float(row["updated_at"] or 0.0),
                    float(row["created_at"] or 0.0),
                    float(row["last_recalled_at"] or 0.0),
                )
                if anchor < now - 180 * 86400:
                    forgotten_ids.append(int(row["id"]))
            if forgotten_ids:
                self._db.executemany(
                    "UPDATE facts SET status='forgotten', value='[منسي]', quote='', "
                    "structured='{}' WHERE id=?",
                    [(fid,) for fid in forgotten_ids],
                )
                result["forgotten"] = len(forgotten_ids)
            self._db.commit()
        return result

    def backfill_dimensions(self, mapping: dict[str, str]) -> int:
        """يربط الحقائق القديمة (اللي اتخزنت قبل v2) بأبعادها."""
        total = 0
        with self._lock:
            for key, dimension in mapping.items():
                cur = self._db.execute(
                    "UPDATE facts SET dimension=? WHERE key=? "
                    "AND (dimension IS NULL OR dimension='')",
                    (dimension, key),
                )
                total += cur.rowcount
            self._db.commit()
        return total

    def all_chat_ids(self) -> list[int]:
        with self._lock:
            rows = self._db.execute(
                "SELECT chat_id FROM messages UNION SELECT chat_id FROM facts"
            ).fetchall()
        return [int(r["chat_id"]) for r in rows]

    def delete_fact(self, chat_id: int, fact_id: int) -> bool:
        with self._lock:
            self._db.execute(
                "DELETE FROM memory_evidence WHERE fact_id=? AND chat_id=?",
                (fact_id, chat_id),
            )
            cur = self._db.execute(
                "DELETE FROM facts WHERE id=? AND chat_id=?", (fact_id, chat_id)
            )
            self._db.commit()
        return cur.rowcount > 0

    def count_facts(self, chat_id: int) -> int:
        with self._lock:
            row = self._db.execute(
                "SELECT COUNT(*) AS n FROM facts WHERE chat_id=? AND status='active' "
                "AND (valid_until IS NULL OR valid_until>?)",
                (chat_id, time.time()),
            ).fetchone()
        return int(row["n"]) if row else 0

    def delete_facts(self, chat_id: int, key: str, value_contains: str | None = None) -> int:
        """يمسح حقائق بمفتاح معيّن، واختياريًا اللي قيمتها فيها نص معيّن."""
        with self._lock:
            if value_contains:
                ids = [
                    int(r["id"])
                    for r in self._db.execute(
                        "SELECT id FROM facts WHERE chat_id=? AND key=? AND value LIKE ?",
                        (chat_id, key, f"%{value_contains}%"),
                    ).fetchall()
                ]
            else:
                ids = [
                    int(r["id"])
                    for r in self._db.execute(
                        "SELECT id FROM facts WHERE chat_id=? AND key=?", (chat_id, key)
                    ).fetchall()
                ]
            if ids:
                marks = ",".join("?" for _ in ids)
                self._db.execute(
                    f"DELETE FROM memory_evidence WHERE fact_id IN ({marks})", ids
                )
                cur = self._db.execute(
                    f"DELETE FROM facts WHERE id IN ({marks})", ids
                )
            else:
                cur = None
            self._db.commit()
        return cur.rowcount if cur is not None else 0

    def delete_all_facts(self, chat_id: int) -> int:
        with self._lock:
            self._db.execute("DELETE FROM memory_evidence WHERE chat_id=?", (chat_id,))
            cur = self._db.execute("DELETE FROM facts WHERE chat_id=?", (chat_id,))
            self._db.commit()
        return cur.rowcount

    # ---------- قواعد السلوك المتعلَّمة (playbook) ----------
    def save_procedure(self, chat_id: int, rule: str, context: str = "") -> int:
        rule = " ".join((rule or "").split()).strip()
        now = time.time()
        with self._lock:
            row = self._db.execute(
                "SELECT id FROM procedures WHERE chat_id=? AND rule=?", (chat_id, rule)
            ).fetchone()
            if row:
                self._db.execute(
                    "UPDATE procedures SET hits=hits+1, updated_at=?, context=? WHERE id=?",
                    (now, context, int(row["id"])),
                )
                self._db.commit()
                return int(row["id"])
            cur = self._db.execute(
                "INSERT INTO procedures (chat_id, rule, context, hits, created_at, updated_at) "
                "VALUES (?,?,?,1,?,?)",
                (chat_id, rule, context, now, now),
            )
            self._db.commit()
        return int(cur.lastrowid)

    def all_procedures(self, chat_id: int) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM procedures WHERE chat_id=? ORDER BY hits DESC, id",
                (chat_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_procedure(self, chat_id: int, procedure_id: int) -> bool:
        with self._lock:
            cur = self._db.execute(
                "DELETE FROM procedures WHERE id=? AND chat_id=?",
                (procedure_id, chat_id),
            )
            self._db.commit()
        return cur.rowcount > 0

    # ---------- حالة قصيرة المدى ----------
    def set_state(self, chat_id: int, key: str, value: str) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO state (chat_id, key, value, updated_at) VALUES (?,?,?,?) "
                "ON CONFLICT(chat_id, key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (chat_id, key, value, time.time()),
            )
            self._db.commit()

    def get_state(self, chat_id: int, key: str) -> str | None:
        with self._lock:
            row = self._db.execute(
                "SELECT value FROM state WHERE chat_id=? AND key=?", (chat_id, key)
            ).fetchone()
        return str(row["value"]) if row else None

    def recent_user_messages(self, chat_id: int, limit: int = 60) -> list[str]:
        with self._lock:
            rows = self._db.execute(
                "SELECT payload FROM messages WHERE chat_id=? AND role='user' "
                "ORDER BY id DESC LIMIT ?",
                (chat_id, limit),
            ).fetchall()
        texts: list[str] = []
        for row in reversed(rows):
            try:
                data = json.loads(row["payload"])
            except (ValueError, TypeError):
                continue
            content = str(data.get("content") or "").strip()
            if content:
                texts.append(content)
        return texts

    def close(self) -> None:
        with self._lock:
            self._db.close()


def _intent_row(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    try:
        data["action"] = json.loads(data.get("action") or "{}")
    except (ValueError, TypeError):
        data["action"] = {}
    return data
