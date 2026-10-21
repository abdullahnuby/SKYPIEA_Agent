"""عميل Bot API خفيف لتيليجرام (بدون مكتبات إضافية)."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

import httpx


class TelegramError(RuntimeError):
    pass


def _chunks(text: str, size: int = 3800) -> list[str]:
    if len(text) <= size:
        return [text]
    parts: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        if len(current) + len(line) > size:
            if current:
                parts.append(current)
            current = ""
        while len(line) > size:
            parts.append(line[:size])
            line = line[size:]
        current += line
    if current:
        parts.append(current)
    return parts or [""]


class Telegram:
    def __init__(self, token: str) -> None:
        self.token = token
        self.base = f"https://api.telegram.org/bot{token}"
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=15.0))

    async def _api(self, method: str, **params: Any) -> Any:
        try:
            resp = await self.client.post(f"{self.base}/{method}", json=params)
        except httpx.HTTPError as exc:
            raise TelegramError(f"شبكة: {exc}") from exc
        try:
            data = resp.json()
        except ValueError as exc:
            raise TelegramError(f"رد غير صالح من تيليجرام ({resp.status_code})") from exc
        if not data.get("ok"):
            raise TelegramError(str(data.get("description") or data))
        return data.get("result")

    async def get_me(self) -> dict[str, Any]:
        return await self._api("getMe")

    async def get_updates(self, offset: int, timeout: int = 40) -> list[dict[str, Any]]:
        return await self._api(
            "getUpdates",
            offset=offset,
            timeout=timeout,
            allowed_updates=["message", "callback_query"],
        )

    async def send(
        self,
        chat_id: int,
        text: str,
        keyboard: dict[str, Any] | None = None,
    ) -> None:
        chunks = _chunks(text or "(فاضي)")
        for index, chunk in enumerate(chunks):
            payload: dict[str, Any] = {
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }
            if keyboard and index == len(chunks) - 1:
                payload["reply_markup"] = keyboard
            try:
                await self._api("sendMessage", **payload)
            except TelegramError as exc:
                if "parse" in str(exc).lower() or "entit" in str(exc).lower():
                    # HTML مش سليم — نبعت نص عادي بدل ما الرسالة تضيع
                    payload.pop("parse_mode", None)
                    await self._api("sendMessage", **payload)
                else:
                    raise

    async def answer_callback(self, callback_id: str, text: str = "") -> None:
        await self._api("answerCallbackQuery", callback_query_id=callback_id, text=text[:200])

    async def typing(self, chat_id: int) -> None:
        try:
            await self._api("sendChatAction", chat_id=chat_id, action="typing")
        except TelegramError:
            pass

    async def send_photo(self, chat_id: int, path: str, caption: str = "") -> bool:
        file_path = Path(path)
        if not file_path.exists():
            return False
        data: dict[str, Any] = {"chat_id": str(chat_id)}
        if caption:
            data["caption"] = caption[:900]
        try:
            with file_path.open("rb") as handle:
                resp = await self.client.post(
                    f"{self.base}/sendPhoto",
                    data=data,
                    files={"photo": (file_path.name, handle, "image/png")},
                )
        except (OSError, httpx.HTTPError):
            return False
        try:
            return bool(resp.json().get("ok"))
        except ValueError:
            return False

    async def close(self) -> None:
        await self.client.aclose()


def esc(text: Any) -> str:
    return html.escape(str(text), quote=False)
