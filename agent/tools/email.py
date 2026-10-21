"""أدوات الإيميل عبر IMAP/SMTP (مكتبة بايثون القياسية)."""

from __future__ import annotations

import email
import imaplib
import smtplib
from email.header import decode_header, make_header
from email.message import EmailMessage


from ..runtime import rt
from . import tool


def _require() -> str | None:
    cfg = rt.require_cfg()
    if not cfg.email_enabled:
        return (
            "الإيميل مش متظبط. حط EMAIL_USER و EMAIL_PASSWORD و EMAIL_IMAP_HOST "
            "في ملف .env (Gmail محتاج App Password)."
        )
    return None


def _header(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:  # noqa: BLE001
        return value


def _connect_imap() -> imaplib.IMAP4_SSL:
    cfg = rt.require_cfg()
    conn = imaplib.IMAP4_SSL(cfg.email_imap_host, cfg.email_imap_port)
    conn.login(cfg.email_user, cfg.email_password)
    return conn


def _body_text(raw: bytes) -> str:
    msg = email.message_from_bytes(raw)
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(
                part.get("Content-Disposition", "")
            ):
                payload = part.get_payload(decode=True) or b""
                return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        return "(مفيش جزء نصي — الرسالة HTML فقط)"
    payload = msg.get_payload(decode=True) or b""
    return payload.decode(msg.get_content_charset() or "utf-8", errors="replace")


@tool(
    "email_list",
    "آخر الرسائل في صندوق الوارد (المرسل + الموضوع + التاريخ).",
    {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "عدد الرسائل (1-25)."},
            "mailbox": {"type": "string", "description": "اسم المجلد (افتراضي INBOX)."},
        },
    },
    cacheable=True,
)
def email_list(limit: int = 10, mailbox: str = "INBOX") -> str:
    problem = _require()
    if problem:
        return problem
    limit = max(1, min(int(limit or 10), 25))
    try:
        conn = _connect_imap()
        try:
            conn.select(mailbox, readonly=True)
            status, data = conn.search(None, "ALL")
            if status != "OK":
                return "فشل البحث في الصندوق."
            uids = data[0].split()[-limit:]
            lines = []
            for uid in reversed(uids):
                status, fetched = conn.fetch(uid, "(RFC822.HEADER)")
                if status != "OK" or not fetched or not isinstance(fetched[0], tuple):
                    continue
                msg = email.message_from_bytes(fetched[0][1])
                lines.append(
                    f"[{uid.decode()}] {_header(msg.get('Subject'))}\n"
                    f"    من: {_header(msg.get('From'))}\n"
                    f"    في: {_header(msg.get('Date'))}"
                )
            return "\n\n".join(lines) or "الصندوق فاضي."
        finally:
            try:
                conn.logout()
            except Exception:  # noqa: BLE001
                pass
    except imaplib.IMAP4.error as exc:
        return f"خطأ IMAP: {exc}"
    except OSError as exc:
        return f"خطأ شبكة: {exc}"


@tool(
    "email_read",
    "قراءة رسالة كاملة بالـ UID اللي رجع من email_list.",
    {
        "type": "object",
        "properties": {
            "uid": {"type": "string", "description": "معرّف الرسالة."},
            "mailbox": {"type": "string", "description": "اسم المجلد."},
        },
        "required": ["uid"],
    },
    cacheable=True,
)
def email_read(uid: str, mailbox: str = "INBOX") -> str:
    problem = _require()
    if problem:
        return problem
    try:
        conn = _connect_imap()
        try:
            conn.select(mailbox, readonly=True)
            status, fetched = conn.fetch(str(uid).encode(), "(RFC822)")
            if status != "OK" or not fetched or not isinstance(fetched[0], tuple):
                return f"مش لاقي الرسالة {uid}."
            raw = fetched[0][1]
            msg = email.message_from_bytes(raw)
            body = _body_text(raw)
            return (
                f"الموضوع: {_header(msg.get('Subject'))}\n"
                f"من: {_header(msg.get('From'))}\n"
                f"إلى: {_header(msg.get('To'))}\n"
                f"التاريخ: {_header(msg.get('Date'))}\n\n"
                f"{body[:6000]}"
            )
        finally:
            try:
                conn.logout()
            except Exception:  # noqa: BLE001
                pass
    except (imaplib.IMAP4.error, OSError) as exc:
        return f"خطأ: {exc}"


@tool(
    "email_send",
    "إرسال إيميل (بيحتاج موافقة صريحة قبل الإرسال).",
    {
        "type": "object",
        "properties": {
            "to": {"type": "string", "description": "عنوان المستلم."},
            "subject": {"type": "string", "description": "الموضوع."},
            "body": {"type": "string", "description": "نص الرسالة."},
        },
        "required": ["to", "subject", "body"],
    },
    side_effect=True,
)
def email_send(to: str, subject: str, body: str) -> str:
    problem = _require()
    if problem:
        return problem
    cfg = rt.require_cfg()
    sender = cfg.email_from or cfg.email_user
    if "," in to or ";" in to:
        recipients = [a for a in to.replace(";", ",").split(",") if a.strip()]
    else:
        recipients = [to]

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        with smtplib.SMTP_SSL(cfg.email_smtp_host or cfg.email_imap_host, cfg.email_smtp_port) as smtp:
            smtp.login(cfg.email_user, cfg.email_password)
            smtp.send_message(msg)
        return f"تم إرسال الإيميل إلى {msg['To']}."
    except (smtplib.SMTPException, OSError) as exc:
        return f"فشل الإرسال: {exc}"
