"""مهارات Markdown — نفس فكرة SKILL.md في ethan-agent لكن بدون LLM.

كل مهارة ملف ``skills/<name>/SKILL.md`` أو ``skills/<name>.md``:

```
---
name: morning
description: رد صباحي
trigger: "صباح الفل|صباح النور|good morning"
reply: "صباح الفل 🌞 يومك سعيد."
fast_path: true
---
```

أو مهارة تنفّذ أداة:

```
---
name: youtube
trigger: "افتح يوتيوب|youtube"
tool: open_target
args: {"target": "youtube"}
---
```

``trigger`` ممكن يكون regex لو بدأ بـ ``re:``، وممكن يكون أكتر من trigger
مفصولين بـ ``|`` أو قائمة YAML. الـ ``args`` بتدعم ``{match}`` و``{1}``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import BASE_DIR
from .text import normalize

DEFAULT_SKILLS_DIR = BASE_DIR / "skills"


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """محلل YAML صغير: key: value + قوائم مسطحة. مش محتاج PyYAML."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    raw_meta = text[3:end].strip("\n")
    body = text[end + 4 :].lstrip("\n")
    meta: dict[str, Any] = {}
    current_key = ""
    for raw_line in raw_meta.splitlines():
        line = raw_line.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        stripped = line.strip()
        if stripped.startswith("- ") and current_key:
            meta.setdefault(current_key, [])
            if isinstance(meta[current_key], list):
                meta[current_key].append(_strip_quotes(stripped[2:]))
            continue
        if ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        key = key.strip()
        value = value.strip()
        current_key = key
        if value:
            meta[key] = _strip_quotes(value)
        else:
            meta[key] = []
    return meta, body


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [part.strip() for part in value.split("|") if part.strip()]
    return []


@dataclass
class MarkdownSkill:
    name: str
    description: str
    triggers: list[str]
    content: str
    source: Path
    tool: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    reply: str = ""
    fast_path: bool = False

    def matches(self, text: str) -> re.Match | None:
        norm = normalize(text, lower=True)
        for trigger in self.triggers:
            if trigger.startswith("re:"):
                try:
                    match = re.search(trigger[3:], text, re.IGNORECASE)
                except re.error:
                    continue
            else:
                needle = normalize(trigger, lower=True)
                pos = norm.find(needle) if needle else -1
                match = None
                if pos >= 0:
                    # بنرجّع match وهمي عشان التوحيد مع فروع الـ regex
                    match = re.search(r".*", text, re.DOTALL)
            if match:
                return match
        return None

    def build(self, text: str, match: re.Match | None = None) -> Any:
        from .brain import Action

        def fill(value: Any) -> Any:
            if isinstance(value, str):
                value = value.replace("{match}", text)
                for index in range(1, 10):
                    try:
                        value = value.replace(f"{{{index}}}", match.group(index) or "")
                    except (IndexError, AttributeError):
                        value = value.replace(f"{{{index}}}", "")
                return value
            if isinstance(value, dict):
                return {key: fill(item) for key, item in value.items()}
            if isinstance(value, list):
                return [fill(item) for item in value]
            return value

        if self.tool:
            return Action(tool=self.tool, args=fill(self.args or {}))
        reply = fill(self.reply or self.content or "تمام.")
        return Action(reply=reply)


class MarkdownSkills:
    """سجل مهارات Markdown مع إعادة تحميل تلقائية لو الملفات اتغيرت."""

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = Path(directory) if directory else DEFAULT_SKILLS_DIR
        self._skills: list[MarkdownSkill] = []
        self._fingerprint: tuple[tuple[str, float], ...] = ()
        self._loaded = False

    def _scan(self) -> tuple[tuple[str, float], ...]:
        if not self.directory.exists():
            return ()
        items: list[tuple[str, float]] = []
        for path in self.directory.rglob("*.md"):
            if path.name.lower() in {"readme.md", "skill.md"} and path.name.lower() == "readme.md":
                continue
            try:
                items.append((str(path), path.stat().st_mtime))
            except OSError:
                continue
        return tuple(sorted(items))

    def load(self, *, force: bool = False) -> list[MarkdownSkill]:
        fingerprint = self._scan()
        if not force and self._loaded and fingerprint == self._fingerprint:
            return list(self._skills)
        skills: list[MarkdownSkill] = []
        for path_str, _ in fingerprint:
            path = Path(path_str)
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            meta, body = _parse_frontmatter(text)
            triggers = _as_list(meta.get("trigger", ""))
            if not triggers:
                continue
            name = str(meta.get("name") or path.parent.name or path.stem).strip()
            args: dict[str, Any] = {}
            raw_args = meta.get("args", "")
            if isinstance(raw_args, str) and raw_args.strip():
                try:
                    parsed = json.loads(raw_args)
                    if isinstance(parsed, dict):
                        args = parsed
                except (ValueError, TypeError):
                    args = {}
            skills.append(
                MarkdownSkill(
                    name=name,
                    description=str(meta.get("description", "")).strip(),
                    triggers=triggers,
                    content=body.strip(),
                    source=path,
                    tool=str(meta.get("tool", "")).strip(),
                    args=args,
                    reply=str(meta.get("reply", "")).strip(),
                    fast_path=str(meta.get("fast_path", "")).lower() in {"1", "true", "yes", "on"},
                )
            )
        self._skills = skills
        self._fingerprint = fingerprint
        self._loaded = True
        return list(skills)

    def all(self) -> list[MarkdownSkill]:
        return self.load()

    def match(self, text: str) -> Any | None:
        for skill in self.load():
            match = skill.matches(text)
            if match:
                return skill.build(text, match)
        return None

    def get(self, name: str) -> MarkdownSkill | None:
        for skill in self.load():
            if skill.name == name:
                return skill
        return None
