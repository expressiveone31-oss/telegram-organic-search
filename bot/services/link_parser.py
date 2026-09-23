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
VK_URL_RE       = re.compile(r"https?://vk\.com/wall(-?\d+)_(\d+)")
VK_SHORT_URL_RE = re.compile(r"https?://vk\.com/[^?#]+\?w=wall(-?\d+)_(\d+)")


@dataclass
class ParsedPost:
    platform: str   # "tg" | "vk"
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

        return ParsedPost(platform="tg", url=url, text=text, timestamp=ts)

    except Exception as e:
        logger.error("TG parse error %s: %s", url, e)
        return None


async def parse_vk_link(url: str) -> Optional[ParsedPost]:
    """Вытаскивает текст и дату VK-поста через VK API."""
    vk_token = os.getenv("VK_TOKEN", "")
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
            logger.error("VK API error: %s", data["error"])
            return None

        items = data.get("response", {}).get("items") or data.get("response", [])
        if not items:
            return None

        post = items[0]
        return ParsedPost(
            platform="vk",
            url=url,
            text=post.get("text", ""),
            timestamp=post.get("date", 0),
        )

    except Exception as e:
        logger.error("VK parse error %s: %s", url, e)
        return None


async def parse_link(url: str) -> Optional[ParsedPost]:
    if "t.me" in url:
        return await parse_tg_link(url)
    if "vk.com" in url:
        return await parse_vk_link(url)
    return None


def extract_seeds_from_text(text: str) -> list[str]:
    """Извлекает поисковые фразы из текста посева."""
    clean = re.sub(r"https?://\S+", "", text)
    clean = re.sub(r"#\S+", "", clean)
    clean = re.sub(r"@\S+", "", clean)
    clean = re.sub(r"[ \t]+", " ", clean)

    seeds = []
    for s in re.split(r"[.\n!?]+", clean):
        s = s.strip()
        if 10 <= len(s) <= 120:
            seeds.append(s)

    return seeds[:10]
