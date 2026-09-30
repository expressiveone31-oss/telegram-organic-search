"""
Парсинг ссылок на посты TG и VK.
Возвращает текст поста и unix-timestamp даты публикации.
"""
from __future__ import annotations

import os
import re
import logging
import unicodedata
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

TG_URL_RE       = re.compile(r"https?://t\.me/(?:s/)?([A-Za-z0-9_]+)/(\d+)")
# схема и m. необязательны: пользователь часто шлёт vk.ru/wall-… без https
_VK_HOST = r"(?:https?://)?(?:m\.)?vk\.(?:com|ru)/"
VK_URL_RE       = re.compile(_VK_HOST + r"wall(-?\d+)_(\d+)")
VK_SHORT_URL_RE = re.compile(_VK_HOST + r"[^?\s#]+[?&]w=wall(-?\d+)_(\d+)")
VK_CLUB_RE      = re.compile(_VK_HOST + r"(?:club|public|event)(\d+)")

@dataclass
class ParsedPost:
    platform: str   # "tg" | "vk"
    url: str
    text: str
    timestamp: int  # unix


async def parse_tg_link(url: str) -> Optional[ParsedPost]:
    m = TG_URL_RE.search(url)
    if not m:
        return None
    channel, post_id = m.group(1), m.group(2)
    preview_url = f"https://t.me/{channel}/{post_id}?embed=1&mode=tme"
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            r = await client.get(preview_url, headers={"User-Agent": "Mozilla/5.0"})
            html = r.text

        text_m = re.search(
            r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
            html, re.S
        )
        text = ""
        if text_m:
            raw = text_m.group(1)
            text = re.sub(r"<[^>]+>", " ", raw)
            text = re.sub(r"\s+", " ", text).strip()

        dt_m = re.search(r'datetime="([^"]+)"', html)
        ts = 0
        if dt_m:
            from datetime import datetime
            try:
                dt = datetime.fromisoformat(dt_m.group(1).replace("Z", "+00:00"))
                ts = int(dt.timestamp())
            except Exception:
                pass

        if not text and not ts:
            return None

        logger.info("TG parsed %s: ts=%d text=%r", url, ts, text[:80])
        return ParsedPost(platform="tg", url=url, text=text, timestamp=ts)

    except Exception as e:
        logger.error("TG parse error %s: %s", url, e)
        return None


async def parse_vk_link(url: str) -> Optional[ParsedPost]:
    vk_token = os.getenv("VK_TOKEN", "").strip()
    if not vk_token:
        raise RuntimeError("VK_TOKEN is not set")

    m = VK_URL_RE.search(url) or VK_SHORT_URL_RE.search(url)
    if not m:
        return None
    owner_id, post_id = m.group(1), m.group(2)

    params = {
        "posts": f"{owner_id}_{post_id}",
        "v": "5.199",
        "access_token": vk_token,
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get("https://api.vk.com/method/wall.getById", params=params)
            data = r.json()

        if "error" in data:
            logger.error("VK API error parsing %s: %s", url, data["error"])
            return None

        items = data.get("response", {}).get("items") or data.get("response", [])
        if not items:
            return None

        post = items[0]
        text = post.get("text", "")
        ts = post.get("date", 0)
        logger.info("VK parsed %s: ts=%d text=%r", url, ts, text[:80])
        return ParsedPost(platform="vk", url=url, text=text, timestamp=ts)

    except Exception as e:
        logger.error("VK parse error %s: %s", url, e)
        return None


async def parse_link(url: str) -> Optional[ParsedPost]:
    if "t.me" in url:
        return await parse_tg_link(url)
    if "vk.com" in url or "vk.ru" in url:
        return await parse_vk_link(url)
    return None


_INVISIBLE = {"\ufe0f", "\ufe0e", "\u200d"}


def _clean_for_sentences(text: str) -> str:
    """Убирает ссылки и эмодзи, оставляет пунктуацию для разбивки на предложения."""
    text = re.sub(r"https?://\S+", "", text)
    # Категория So покрывает и ⚡ (U+26A1), и 🔮 — диапазона с U+1F300 мало
    text = "".join(
        ch for ch in text
        if ch not in _INVISIBLE and unicodedata.category(ch) != "So"
    )
    # Переносы строк — такой же разделитель предложений, как точка, поэтому
    # схлопываем только пробелы внутри строки, а сами переносы сохраняем.
    text = re.sub(r"[^\S\n]+", " ", text)
    text = re.sub(r"\n\s*", "\n", text)
    return text.strip()


QUESTION_STARTS = {"ваши", "что", "как", "где", "кто", "зачем", "почему",
                   "только", "ваш", "напишите", "расскажите"}


def extract_seeds_from_posts(
    texts: list[str],
    *,
    min_len: int = 20,
    limit: int = 8,
) -> list[str]:
    """
    Извлекает поисковые фразы из текстов.

    Органика — это чаще всего дословный копипаст посева, поэтому берём целые
    предложения как есть. Склейка из нескольких предложений почти никогда не
    совпадает дословно: достаточно убранной запятой, и совпадения уже нет.

    Фильтры:
    - не короче min_len символов (для посевов 20: отсекает "Что там?")
    - максимум 120 символов (слишком длинное плохо ищется)
    - не начинается с вопросительного слова или призыва
    """
    if not texts:
        return []

    seen: set[str] = set()
    result: list[str] = []

    for text in texts:
        clean = _clean_for_sentences(text)
        # разбиваем по . ! ? и переносам строк
        sentences = re.split(r"[.!?\n]+", clean)
        for s in sentences:
            s = s.strip().strip(",")
            if len(s) < min_len or len(s) > 120:
                continue
            # отсекаем вопросы и призывы
            first_word = s.split()[0].lower().rstrip("?!,.")
            if first_word in QUESTION_STARTS:
                continue
            if s not in seen:
                seen.add(s)
                result.append(s)

    return result[:limit]


def extract_manual_seeds(text: str) -> list[str]:
    """
    Фразы, набранные руками. Режем так же на предложения — пользователь обычно
    вставляет кусок текста поста, а не выверенную фразу. Порог длины ниже:
    короткая фраза здесь осмысленная, её напечатали намеренно.
    """
    return extract_seeds_from_posts([text], min_len=10)


def extract_vk_owner_ids(text: str) -> list[int]:
    """
    id стен ВК из ссылок. newsfeed.search не индексирует все паблики;
    по этим стенам потом ищем через wall.search.
    club/public/event → отрицательный owner_id сообщества.
    """
    ids: list[int] = []
    for m in VK_URL_RE.finditer(text or ""):
        ids.append(int(m.group(1)))
    for m in VK_SHORT_URL_RE.finditer(text or ""):
        ids.append(int(m.group(1)))
    for m in VK_CLUB_RE.finditer(text or ""):
        ids.append(-int(m.group(1)))
    seen: set[int] = set()
    out: list[int] = []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out
