"""سياسة الصلاحيات: كل أداة بتتفحص قبل التنفيذ (allow / ask / deny)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .aliases import resolve


class Decision(str, Enum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


@dataclass(frozen=True)
class Verdict:
    decision: Decision
    reason: str = ""


# أنماط تُرفض فورًا حتى لو المستخدم وافق (تدمير النظام / تسريب أسرار)
DENY_SHELL = [
    r"\brm\s+(-[a-z]*[rf][a-z]*\s+)+(/|~|\$HOME)",
    r"\bformat\s+[a-z]:",
    r"\b(del|erase)\s+.*/[sS]\b",
    r"\b(rd|rmdir)\s+.*/[sS]\b",
    r"\bdiskpart\b",
    r"\bbcdedit\b",
    r"\bvssadmin\b",
    r"\breg\s+delete\b",
    r"\bshutdown\b",
    r"\bcipher\s+/w\b",
    r"\bnet\s+user\b.*\s/add\b",
    r"\b(netcat|nc)\b.*-e\b",
    r"invoke-expression|\biex\b",
    r"downloadstring",
    r"curl[^\n|]*\|\s*(sh|bash|iex)",
    r"wget[^\n|]*\|\s*(sh|bash)",
    r"(type|cat)\s+.*\.(env|pem|key)\b",
    r"\.ssh[/\\]id_",
]

# أوامر آمنة معروفة تتعدّى السؤال (قراءة فقط)
SAFE_SHELL = [
    r"^\s*(dir|ls|pwd|whoami|hostname|date|time|ver|echo)\b",
    r"^\s*git\s+(status|diff|log|branch|show|remote|rev-parse)\b",
    r"^\s*(py|python|node|npm|pip)\s+(--version|-v|--help)\b",
    r"^\s*(where|which|get-command)\b",
    r"^\s*Get-PSDrive\b",
    r"^\s*Get-CimInstance\b",
    r"^\s*Get-Process\b",
    r"^\s*Get-NetIPAddress\b",
    r"^\s*\$os\s*=\s*Get-CimInstance\b",
    r"^\s*rundll32\.exe\s+user32\.dll,LockWorkStation\s*;",
    r"^\s*New-Item\s+-ItemType\s+Directory\b",
]

# أدوات لازم تاخد موافقة صريحة في كل مرة
ALWAYS_ASK = {"email_send", "delete_file", "browser_eval", "write_file"}

# أدوات بتلمس مسارات على القرص
PATH_TOOLS = {"read_file", "write_file", "list_dir", "find_files", "delete_file"}

# مسارات أسرار: ممنوع قراءتها أو نسخها حتى لو جوّه مجلد العمل
SECRET_PATH = re.compile(
    r"(?i)(?:^|[/\\])(?:\.env|\.pem|\.key|id_rsa|id_ed25519|credentials|secrets?)(?:$|\.|[/\\])"
    r"|\.ssh[/\\]"
)

# هدف «افتح» اللي شكله أمر تدميري — يترفض مش يتفتح
DANGEROUS_TARGET = re.compile(
    r"(?i)(net\s+user\b.*\s/add\b|shutdown\b|diskpart\b|format\s+[a-z]:|reg\s+delete\b"
    r"|bcdedit\b|vssadmin\b|invoke-expression|\biex\b|downloadstring"
    r"|\.ssh[/\\]id_|\.env\b|\.pem\b)"
)


class Policy:
    def __init__(self, workspace: Path, mode: str = "ask") -> None:
        self.workspace = Path(workspace).resolve()
        self.mode = mode

    # ---------- مساعدات ----------
    def resolve(self, raw: str | None) -> Path:
        p = Path(raw or ".").expanduser()
        if not p.is_absolute():
            p = self.workspace / p
        return p.resolve()

    def inside(self, p: Path) -> bool:
        try:
            p.relative_to(self.workspace)
            return True
        except ValueError:
            return False

    # ---------- القرار ----------
    def check(self, tool: str, args: dict) -> Verdict:
        verdict = self._decide(tool, args)
        # وضع auto معناه: تنفيذ بدون سؤال (الرفض المطلق يفضل شغال)
        if self.mode == "auto" and verdict.decision is Decision.ASK:
            return Verdict(Decision.ALLOW, f"{verdict.reason} (وضع auto)")
        return verdict

    def _decide(self, tool: str, args: dict) -> Verdict:
        if tool == "open_target":
            raw = str(args.get("target", ""))
            if DANGEROUS_TARGET.search(raw):
                return Verdict(Decision.DENY, "هدف خطير — مش هفتحه")
            target = resolve(raw)
            # أسماء مواقع عربية (يوتيوب/جوجل...) بتتحول لرابط قبل الفحص
            if target.startswith(("http://", "https://")):
                return Verdict(Decision.ALLOW)
            return Verdict(Decision.ASK, "فتح برنامج أو ملف على الجهاز")
        if tool == "shell":
            return self._shell(args)
        if tool in PATH_TOOLS:
            raw_path = str(args.get("path") or args.get("pattern") or args.get("root") or "")
            if SECRET_PATH.search(raw_path):
                return Verdict(Decision.DENY, "ملف أسرار — ممنوع الوصول")
        if tool in {"write_file", "delete_file"}:
            target = self.resolve(args.get("path", ""))
            if not self.inside(target):
                return Verdict(
                    Decision.ASK,
                    f"الكتابة خارج مجلد العمل ({self.workspace})",
                )
            return Verdict(Decision.ASK, "تعديل ملفات على القرص")
        if tool in PATH_TOOLS:
            target = self.resolve(args.get("path") or args.get("root"))
            if not self.inside(target):
                return Verdict(Decision.ASK, "قراءة خارج مجلد العمل")
            return Verdict(Decision.ALLOW)
        if tool in ALWAYS_ASK:
            return Verdict(Decision.ASK, "عملية حساسة")
        return Verdict(Decision.ALLOW)

    def _shell(self, args: dict) -> Verdict:
        command = str(args.get("command", ""))
        for pattern in DENY_SHELL:
            if re.search(pattern, command, re.IGNORECASE):
                return Verdict(Decision.DENY, "أمر ممنوع نهائيًا (تدميري أو خطير)")
        for pattern in SAFE_SHELL:
            if re.search(pattern, command, re.IGNORECASE):
                return Verdict(Decision.ALLOW)
        return Verdict(Decision.ASK, "تنفيذ أمر على النظام")
