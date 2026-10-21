"""أدوات الويب: جلب صفحة كنص + بحث بسيط."""

from __future__ import annotations

import html as html_lib
import re
import urllib.parse

import httpx

from . import tool, truncate

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def html_to_text(raw: str) -> str:
    text = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", raw)
    text = re.sub(r"(?is)<br\s*/?>", "\n", text)
    text = re.sub(r"(?is)</(p|div|li|tr|h[1-6]|section|article)>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    text = re.sub(r"[ \t\x0b\f\r]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


@tool(
    "fetch_url",
    "جلب صفحة ويب وتحويلها لنص مقروء. مناسب للأخبار والمقالات والـ API.",
    {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "عنوان الصفحة (http/https)."},
            "max_chars": {"type": "integer", "description": "أقصى طول للنص (افتراضي 8000)."},
        },
        "required": ["url"],
    },
    cacheable=True,
)
def fetch_url(url: str, max_chars: int = 8000) -> str:
    if not url.startswith(("http://", "https://")):
        return "خطأ: لازم الرابط يبدأ بـ http:// أو https://"
    try:
        with httpx.Client(
            headers={"User-Agent": UA, "Accept-Language": "ar,en;q=0.8"},
            follow_redirects=True,
            timeout=30,
        ) as client:
            resp = client.get(url)
        content_type = resp.headers.get("content-type", "")
        if "json" in content_type:
            return truncate(resp.text, int(max_chars or 8000))
        if "html" not in content_type and "text" not in content_type:
            return f"نوع المحتوى غير مدعوم: {content_type}"
        return truncate(html_to_text(resp.text), int(max_chars or 8000))
    except httpx.HTTPError as exc:
        return f"فشل الجلب: {type(exc).__name__}: {exc}"


@tool(
    "search_web",
    "بحث في الويب (DuckDuckGo) ويرجع عناوين وروابط ومقتطفات.",
    {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "كلمات البحث."},
            "limit": {"type": "integer", "description": "عدد النتائج (1-10)."},
        },
        "required": ["query"],
    },
    cacheable=True,
)
def search_web(query: str, limit: int = 6) -> str:
    limit = max(1, min(int(limit or 6), 10))
    try:
        with httpx.Client(
            headers={"User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=True,
            timeout=25,
        ) as client:
            resp = client.post("https://html.duckduckgo.com/html/", data={"q": query})
        body = resp.text
    except httpx.HTTPError as exc:
        return f"فشل البحث: {exc}"

    anchors = re.findall(r'(?is)<a([^>]*class="result__a"[^>]*)>(.*?)</a>', body)
    snippets = re.findall(r'(?is)<a([^>]*class="result__snippet"[^>]*)>(.*?)</a>', body)

    results: list[str] = []
    for idx, (attrs, title_html) in enumerate(anchors[:limit]):
        href = re.search(r'href="([^"]+)"', attrs)
        if not href:
            continue
        link = html_lib.unescape(href.group(1))
        if "uddg=" in link:
            link = urllib.parse.unquote(
                urllib.parse.parse_qs(urllib.parse.urlparse(link).query).get("uddg", [link])[0]
            )
        title = html_to_text(title_html)
        snippet = ""
        if idx < len(snippets):
            snippet = html_to_text(snippets[idx][1])
        results.append(f"{idx + 1}. {title}\n   {link}\n   {snippet[:300]}")

    return "\n\n".join(results) if results else "مفيش نتائج — جرّب صياغة تانية أو استخدم fetch_url مباشرة."
