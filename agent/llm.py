"""عميل LLM متوافق مع OpenAI API (يشتغل مع OpenAI / OpenRouter / Ollama / LM Studio)."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from .config import Config


class LLMError(RuntimeError):
    pass


class LLM:
    def __init__(self, cfg: Config) -> None:
        self.base_url = cfg.llm_base_url.rstrip("/")
        self.api_key = cfg.llm_api_key
        self.model = cfg.llm_model
        self.temperature = cfg.llm_temperature

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        timeout: float = 180.0,
    ) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        url = f"{self.base_url}/chat/completions"
        last_error: Exception | None = None

        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.post(url, headers=headers, json=payload)

                if resp.status_code in (429, 500, 502, 503, 504):
                    last_error = LLMError(f"HTTP {resp.status_code}: {resp.text[:300]}")
                    await asyncio.sleep(2 * (attempt + 1))
                    continue

                if resp.status_code >= 400:
                    raise LLMError(f"HTTP {resp.status_code}: {resp.text[:500]}")

                data = resp.json()
                choices = data.get("choices") or []
                if not choices:
                    raise LLMError(f"رد غير متوقع من الموديل: {str(data)[:300]}")

                message = choices[0].get("message") or {}
                return {
                    "role": "assistant",
                    "content": message.get("content") or "",
                    **({"tool_calls": message["tool_calls"]} if message.get("tool_calls") else {}),
                }

            except LLMError:
                raise
            except Exception as exc:  # شبكة / timeout
                last_error = exc
                await asyncio.sleep(2 * (attempt + 1))

        raise LLMError(f"فشل الاتصال بالموديل بعد 3 محاولات: {last_error}")

    async def ping(self) -> str:
        msg = await self.chat(
            [{"role": "user", "content": "Reply with exactly: OK"}],
            timeout=60,
        )
        return (msg.get("content") or "").strip()
