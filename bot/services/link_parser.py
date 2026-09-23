"""
Парсинг ссылок на TG-посты.
Возвращает текст поста и unix-timestamp даты публикации.
"""
from __future__ import annotations

import re
import logging
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

TG_URL_RE = re.compile(r"https?://t\.me/(?:s/)?([A-Za-z0-9_]+)/(\d+)")


@dataclass
class ParsedPost:
    url: str
    text: str
    timestamp: int  # unix


async def parse_tg_link(url: str) -> Optional[ParsedPost]:
    """Вытаскивает текст и дату из публичного TG-поста через embed-превью."""
    m = TG_URL_RE.search(url)
    if not m:
        return None
    channel, post_id = m.group(1), m.group(2)
    preview_url = f"https://t.me/{channel}/{post_id}?embed=1&mode=tme"
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            r = await client.get(preview_url, headers={"User-Agent": "Mozilla/5.0"})
            html = r.text

        # текст поста
        text_m = re.search(
            r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
            html, re.S
        )
        text = ""
        if text_m:
            raw = text_m.group(1)
            text = re.sub(r"<[^>]+>", " ", raw).strip()
            text = re.sub(r"\s+", " ", text).strip()

        # дата через datetime="" атрибут
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
            logger.warning("TG parse: nothing extracted from %s", url)
            return None

        return ParsedPost(url=url, text=text, timestamp=ts)

    except Exception as e:
        logger.error("TG parse error %s: %s", url, e)
        return None


def extract_seeds_from_text(text: str) -> list[str]:
    """
    Извлекает поисковые фразы из текста посева.
    Убирает ссылки, хештеги, упоминания — берёт осмысленные предложения.
    """
    clean = re.sub(r"https?://\S+", "", text)
    clean = re.sub(r"#\S+", "", clean)
    clean = re.sub(r"@\S+", "", clean)
    clean = re.sub(r"[ \t]+", " ", clean)

    sentences = re.split(r"[.\n!?]+", clean)
    seeds = []
    for s in sentences:
        s = s.strip()
        if 10 <= len(s) <= 120:
            seeds.append(s)

    return seeds[:10]
