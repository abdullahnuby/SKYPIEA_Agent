"""إعدادات الـ Agent — من ملف .env أو من متغيرات البيئة."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path) -> None:
    """محلل .env بسيط لا يعتمد على أي مكتبة خارجية."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        # متغيرات النظام الحقيقية لها الأولوية دائمًا
        os.environ.setdefault(key, value.strip().strip('"').strip("'"))


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _path(name: str, default: Path) -> Path:
    raw = os.environ.get(name, "").strip()
    p = Path(raw).expanduser() if raw else default
    if not p.is_absolute():
        p = BASE_DIR / p
    return p.resolve()


@dataclass(frozen=True)
class Config:
    agent_name: str

    telegram_token: str
    allowed_chat_ids: tuple[int, ...]

    llm_base_url: str
    llm_api_key: str
    llm_model: str
    llm_temperature: float

    workspace: Path
    db_path: Path
    log_path: Path
    intent_model: Path

    approval_mode: str
    agent_mode: str
    approval_timeout: int
    max_steps: int
    shell_timeout: int
    max_history: int

    browser_enabled: bool
    browser_headless: bool

    email_imap_host: str
    email_imap_port: int
    email_smtp_host: str
    email_smtp_port: int
    email_user: str
    email_password: str
    email_from: str

    @classmethod
    def load(cls) -> "Config":
        load_dotenv(BASE_DIR / ".env")

        ids: list[int] = []
        for part in os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS", "").replace(";", ",").split(","):
            part = part.strip()
            if part.lstrip("-").isdigit():
                ids.append(int(part))

        return cls(
            agent_name=os.environ.get("AGENT_NAME", "Agent").strip() or "Agent",
            telegram_token=os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(),
            allowed_chat_ids=tuple(ids),
            llm_base_url=os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1").strip(),
            llm_api_key=os.environ.get("LLM_API_KEY", "").strip(),
            llm_model=os.environ.get("LLM_MODEL", "gpt-4.1-mini").strip(),
            llm_temperature=_float("LLM_TEMPERATURE", 0.3),
            workspace=_path("WORKSPACE", BASE_DIR / "workspace"),
            db_path=_path("DB_PATH", BASE_DIR / "data" / "agent.db"),
            log_path=_path("LOG_PATH", BASE_DIR / "data" / "audit.log"),
            intent_model=_path("INTENT_MODEL", BASE_DIR / "data" / "intent_model.npz"),
            approval_mode=os.environ.get("APPROVAL_MODE", "ask").strip().lower(),
            agent_mode=os.environ.get("AGENT_MODE", "auto").strip().lower(),
            approval_timeout=_int("APPROVAL_TIMEOUT", 300),
            max_steps=_int("MAX_STEPS", 25),
            shell_timeout=_int("SHELL_TIMEOUT", 120),
            max_history=_int("MAX_HISTORY", 40),
            browser_enabled=_bool("BROWSER_ENABLED", False),
            browser_headless=_bool("BROWSER_HEADLESS", True),
            email_imap_host=os.environ.get("EMAIL_IMAP_HOST", "").strip(),
            email_imap_port=_int("EMAIL_IMAP_PORT", 993),
            email_smtp_host=os.environ.get("EMAIL_SMTP_HOST", "").strip(),
            email_smtp_port=_int("EMAIL_SMTP_PORT", 465),
            email_user=os.environ.get("EMAIL_USER", "").strip(),
            email_password=os.environ.get("EMAIL_PASSWORD", ""),
            email_from=os.environ.get("EMAIL_FROM", "").strip(),
        )

    @property
    def email_enabled(self) -> bool:
        return bool(self.email_user and self.email_password and self.email_imap_host)

    @property
    def llm_ready(self) -> bool:
        """هل فيه موديل قابل للاستخدام فعلًا؟"""
        if self.llm_api_key and not self.llm_api_key.startswith("sk-xxxx"):
            return True
        return any(host in self.llm_base_url for host in ("localhost", "127.0.0.1", "0.0.0.0"))

    @property
    def mode(self) -> str:
        """الوضع الفعلي: llm أو rules."""
        if self.agent_mode in {"llm", "rules"}:
            return self.agent_mode
        return "llm" if self.llm_ready else "rules"

    def validate(self) -> list[str]:
        """أخطاء تمنع التشغيل."""
        errors: list[str] = []
        if not self.telegram_token or ":" not in self.telegram_token:
            errors.append("TELEGRAM_BOT_TOKEN ناقص أو غير صالح (خده من @BotFather).")
        if not self.allowed_chat_ids:
            errors.append(
                "TELEGRAM_ALLOWED_CHAT_IDS فاضي — ده خطر أمني: أي حد يعرف البوت هيتحكم في جهازك."
            )
        if not self.llm_model:
            errors.append("LLM_MODEL مطلوب.")
        if self.agent_mode not in {"auto", "llm", "rules"}:
            errors.append("AGENT_MODE لازم يكون auto أو llm أو rules.")
        if self.mode == "llm" and "api.openai.com" in self.llm_base_url and not self.llm_api_key:
            errors.append("LLM_API_KEY مطلوب لـ OpenAI (أو خلي AGENT_MODE=rules للعمل بدون موديل).")
        if self.approval_mode not in {"ask", "auto"}:
            errors.append("APPROVAL_MODE لازم يكون ask أو auto.")
        return errors
