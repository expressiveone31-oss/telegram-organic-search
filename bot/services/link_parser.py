"""
Парсинг ссылок на посты TG и VK.
Возвращает текст поста и unix-timestamp даты публикации.
"""
from __future__ import annotations

import os
import re
import logging
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

TG_URL_RE       = re.compile(r"https?://t\.me/(?:s/)?([A-Za-z0-9_]+)/(\d+)")
VK_URL_RE       = re.compile(r"https?://vk\.(?:com|ru)/wall(-?\d+)_(\d+)")
VK_SHORT_URL_RE = re.compile(r"https?://vk\.(?:com|ru)/[^?#]+\?w=wall(-?\d+)_(\d+)")

# Стоп-слова — не идут в поисковые фразы
_STOPWORDS = {
    "и", "в", "на", "с", "по", "из", "за", "к", "у", "о", "а", "но", "или",
    "что", "как", "это", "все", "там", "тут", "уже", "ещё", "еще", "только",
    "мы", "вы", "они", "он", "она", "я", "бы", "не", "да", "нет", "то", "же",
    "ваши", "наши", "свои", "такой", "такая", "такое", "такие",
}


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


def extract_seeds_from_posts(texts: list[str]) -> list[str]:
    """
    Извлекает поисковые фразы из текстов посевов.

    Стратегия: берём биграммы и триграммы из слов длиной 4+,
    не являющихся стоп-словами. Это даёт короткие именные словосочетания
    которые встречаются в органических репостах даже при перефразировании.
    Плюс добавляем наиболее длинные одиночные слова как fallback.
    """
    # Собираем все слова из всех текстов
    all_words: list[str] = []
    for text in texts:
        clean = re.sub(r"https?://\S+", "", text)
        clean = re.sub(r"[#@«»„""\"\(\)\[\]️🔮😁]+", " ", clean)
        words = re.findall(r"[а-яёА-ЯЁa-zA-Z]{4,}", clean)
        all_words.extend(w.lower() for w in words if w.lower() not in _STOPWORDS)

    seeds: list[str] = []

    # Биграммы (пары слов) — из каждого текста отдельно
    for text in texts:
        clean = re.sub(r"https?://\S+", "", text)
        clean = re.sub(r"[#@«»„""\"\(\)\[\]️🔮😁]+", " ", clean)
        words = [
            w.lower() for w in re.findall(r"[а-яёА-ЯЁa-zA-Z]{4,}", clean)
            if w.lower() not in _STOPWORDS
        ]
        for i in range(len(words) - 1):
            bigram = f"{words[i]} {words[i+1]}"
            seeds.append(bigram)
        # Триграммы
        for i in range(len(words) - 2):
            trigram = f"{words[i]} {words[i+1]} {words[i+2]}"
            seeds.append(trigram)

    # Дедупликация с сохранением порядка
    seen: set[str] = set()
    unique: list[str] = []
    for s in seeds:
        if s not in seen:
            seen.add(s)
            unique.append(s)

    # Берём максимум 8 фраз — лучше меньше да точнее
    return unique[:8]
