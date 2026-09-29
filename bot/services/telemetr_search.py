# -*- coding: utf-8 -*-
"""
Поиск органики в Telegram через Telemetr API.
"""
from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

from bot.services import cache
from bot.utils.text import contains_phrase, normalize_for_match

logger = logging.getLogger(__name__)

BASE_URL = "https://api.telemetr.me"


MAX_PAGES_HARD_LIMIT = 5  # абсолютный потолок, даже если в env стоит больше


def _cfg() -> Dict[str, Any]:
    """Читаем конфиг при каждом вызове — Railway может подтянуть переменные позже."""
    pages = min(
        MAX_PAGES_HARD_LIMIT,
        max(1, int(os.getenv("TELEMETR_PAGES", "3") or 3))
    )
    cfg = {
        "token":         os.getenv("TELEMETR_TOKEN", "").strip(),
        "use_quotes":    os.getenv("TELEMETR_USE_QUOTES", "1") == "1",
        "min_views":     int(os.getenv("TELEMETR_MIN_VIEWS", "0") or 0),
        "pages":         pages,
    }
    logger.info("Telemetr cfg: pages=%d min_views=%d use_quotes=%s",
                cfg["pages"], cfg["min_views"], cfg["use_quotes"])
    return cfg


def _ts_to_date(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def _normalize_seed(seed: str, use_quotes: bool) -> str:
    s = seed.strip()
    if use_quotes and s and not (s.startswith('"') and s.endswith('"')):
        return f'"{s}"'
    return s


def _views_of(it: Dict[str, Any]) -> int:
    # Telemetr search API возвращает просмотры в stats.views, не в корне
    v = (
        it.get("views")
        or it.get("views_count")
        or (it.get("stats") or {}).get("views")
        or (it.get("stats") or {}).get("views_count")
        or 0
    )
    try:
        return int(v)
    except Exception:
        return 0


def _post_id_of(it: Dict[str, Any]) -> str:
    for key in ("post_id", "message_id", "msg_id", "tg_post_id", "id"):
        v = it.get(key)
        if isinstance(v, (int, str)) and str(v).isdigit():
            return str(v)
    # joinchat-ссылки Telemetr хвостом несут номер поста: .../AYs2WTVN/6093
    raw = it.get("display_url") or it.get("url") or it.get("link") or ""
    m = re.search(r"/(\d+)/?$", raw)
    return m.group(1) if m else ""


def _channel_of(it: Dict[str, Any], channels: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Telemetr кладёт в пост только channel_id; данные канала — отдельным блоком."""
    inline = it.get("channel")
    if isinstance(inline, dict):
        return inline
    cid = it.get("channel_id")
    if channels and cid is not None:
        return channels.get(str(cid)) or {}
    return {}


def _username_from_link(link: str) -> str:
    m = re.search(r"t\.me/(?:s/)?([A-Za-z0-9_]{4,})/\d+", link or "")
    return m.group(1) if m and m.group(1) != "joinchat" else ""


def _internal_id(cid: Any) -> str:
    """-1001105810677 и 1105810677 — одно и то же, t.me/c/ хочет вариант без -100."""
    s = str(cid or "").lstrip("-")
    if not s.isdigit():
        return ""
    return s[3:] if len(s) > 10 and s.startswith("100") else s


def _link_of(it: Dict[str, Any], channels: Optional[Dict[str, Dict[str, Any]]] = None) -> str:
    """
    Ссылка на пост. Telemetr отдаёт её без схемы, а для приватных каналов —
    как t.me/joinchat/<hash>/<id>: не открывается, да и инвайт-хэш протухает.
    """
    raw = (it.get("link") or it.get("display_url") or it.get("url") or "").strip()
    if raw and not raw.startswith("http"):
        raw = "https://" + raw.lstrip("/")
    if raw and "/joinchat/" not in raw and "/+" not in raw:
        return raw

    post_id = _post_id_of(it)
    if not post_id:
        return raw

    ch = _channel_of(it, channels)
    username = ch.get("username") or ch.get("link") or it.get("username") or ""
    username = str(username).lstrip("@").replace("https://t.me/", "").replace("t.me/", "").strip("/")
    if username and username.isascii() and "/" not in username:
        return f"https://t.me/{username}/{post_id}"

    # приватный канал без юзернейма — внутренняя ссылка t.me/c/<id>/<post>
    short = _internal_id(it.get("channel_id") or ch.get("tg_id") or ch.get("id"))
    if short:
        return f"https://t.me/c/{short}/{post_id}"
    return raw


# Telemetr не гарантирует имя поля с текстом поста, поэтому собираем из всех известных
_TEXT_KEYS = (
    "title", "text", "caption", "message", "post_text",
    "body", "content", "snippet", "description",
)


def _body_of(it: Dict[str, Any]) -> str:
    parts: List[str] = []
    for key in _TEXT_KEYS:
        val = it.get(key)
        if isinstance(val, str) and val.strip():
            parts.append(val.strip())
        elif isinstance(val, dict):
            for nested in val.values():
                if isinstance(nested, str) and nested.strip():
                    parts.append(nested.strip())
    return " ".join(parts).strip()


_normalize = normalize_for_match


def _contains_seed(seed: str, body: str) -> bool:
    """Проверяет что тело поста содержит фразу посева (нормализованно)."""
    return contains_phrase(seed, body)


async def _fetch_page(
    client: httpx.AsyncClient,
    token: str,
    query: str,
    since: str,
    until: str,
    page: int,
) -> Tuple[List[Any], Dict[str, Dict[str, Any]]]:
    params = {
        "query": query,
        "date_from": since,
        "date_to": until,
        "limit": "50",
        "page": str(page),
    }
    headers = {"Authorization": f"Bearer {token}"}
    try:
        r = await client.get(
            f"{BASE_URL}/channels/posts/search",
            params=params,
            headers=headers,
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
    except httpx.HTTPStatusError as e:
        logger.error("Telemetr HTTP %s for query=%r: %s", e.response.status_code, query, e.response.text[:200])
        return [], {}
    except Exception as e:
        logger.error("Telemetr request failed for query=%r: %s", query, e)
        return [], {}

    if not isinstance(data, dict) or data.get("status") != "ok":
        logger.error("Telemetr bad response for query=%r: %s", query, str(data)[:300])
        return [], {}

    resp = data.get("response") or {}
    return resp.get("items") or [], _index_channels(resp.get("channels"))


def _index_channels(raw: Any) -> Dict[str, Dict[str, Any]]:
    """Справочник каналов из ответа: приходит списком либо словарём по id."""
    out: Dict[str, Dict[str, Any]] = {}
    if isinstance(raw, list):
        for ch in raw:
            if isinstance(ch, dict) and ch.get("id") is not None:
                out[str(ch["id"])] = ch
    elif isinstance(raw, dict):
        for key, ch in raw.items():
            if isinstance(ch, dict):
                out[str(ch.get("id", key))] = ch
    return out


async def search_telemetr(
    seeds: List[str],
    since_ts: int,
    until_ts: int,
) -> Tuple[List[Dict[str, Any]], str]:
    cfg = _cfg()
    if not cfg["token"]:
        raise RuntimeError("TELEMETR_TOKEN is not set")

    since = _ts_to_date(since_ts)
    until = _ts_to_date(until_ts)
    seeds = [s.strip() for s in seeds if s.strip()]
    if not seeds:
        return [], "нет фраз для поиска"

    matched: List[Dict[str, Any]] = []
    seen: set[str] = set()
    raw_sample: Optional[Dict[str, Any]] = None
    skipped_no_body = 0
    skipped_no_match = 0
    skipped_dupes = 0

    async with httpx.AsyncClient() as client:
        for raw_seed in seeds:
            q = _normalize_seed(raw_seed, cfg["use_quotes"])
            ckey = cache.make_key("tg", q, since, until, cfg["pages"])

            cached = cache.get(ckey)
            if cached is not None:
                items_all: List[Any] = cached["items"]
                channels: Dict[str, Dict[str, Any]] = cached["channels"]
                logger.info("Telemetr seed=%r: %d items from cache", raw_seed, len(items_all))
            else:
                items_all = []
                channels = {}
                barren = 0
                for page in range(1, cfg["pages"] + 1):
                    items, page_channels = await _fetch_page(client, cfg["token"], q, since, until, page)
                    if not items:
                        break
                    items_all.extend(items)
                    channels.update(page_channels)

                    # Выдача Telemetr не строго отсортирована по релевантности, поэтому
                    # останавливаемся только после двух пустых страниц подряд.
                    page_hits = sum(
                        1 for it in items
                        if isinstance(it, dict) and _contains_seed(raw_seed, _body_of(it))
                    )
                    barren = barren + 1 if page_hits == 0 else 0
                    if barren >= 2:
                        logger.info("Telemetr seed=%r: stop at page %d, 2 barren pages", raw_seed, page)
                        break
                    if len(items) < 50:
                        break

                cache.set(ckey, {"items": items_all, "channels": channels})

            logger.info("Telemetr seed=%r fetched=%d", raw_seed, len(items_all))

            # Лог первого результата для диагностики структуры ответа
            if items_all:
                first = items_all[0]
                logger.info("Telemetr first item keys=%s views=%s link=%s",
                            list(first.keys()) if isinstance(first, dict) else type(first),
                            _views_of(first) if isinstance(first, dict) else "?",
                            _link_of(first) if isinstance(first, dict) else "?")
                if raw_sample is None and isinstance(first, dict):
                    raw_sample = first
            else:
                logger.info("Telemetr seed=%r: zero items from API", raw_seed)

            skipped_views = 0
            for it in items_all:
                if not isinstance(it, dict):
                    continue
                v = _views_of(it)
                if v < cfg["min_views"]:
                    skipped_views += 1
                    continue
                # Всегда проверяем точное вхождение фразы — Telemetr кавычки игнорирует.
                # Пост без распознанного текста отбрасываем: проверить его нечем.
                body = _body_of(it)
                if not body:
                    skipped_no_body += 1
                    continue
                if not _contains_seed(raw_seed, body):
                    skipped_no_match += 1
                    continue

                link = _link_of(it, channels)
                dedup_key = link or f"{it.get('channel_id')}_{_post_id_of(it)}"
                if dedup_key in seen:
                    skipped_dupes += 1
                    continue
                seen.add(dedup_key)

                it["_seed"] = raw_seed
                it["_link"] = link
                it["_views"] = v
                it["_channel"] = _channel_of(it, channels)
                it["_username"] = _username_from_link(link)
                matched.append(it)

            if skipped_views:
                logger.info("Telemetr seed=%r: skipped %d by min_views=%d", raw_seed, skipped_views, cfg["min_views"])

    diag = (
        f"seeds={len(seeds)}, matched={len(matched)}, "
        f"no_match={skipped_no_match}, no_body={skipped_no_body}, "
        f"dupes={skipped_dupes}, range={since}–{until}, {cache.stats()}"
    )
    logger.info("Telemetr done: %s", diag)

    # Схема ответа Telemetr не документирована — под отладкой показываем сырой
    # элемент, чтобы видеть, откуда на самом деле брать ссылку и просмотры.
    if os.getenv("ORGANIC_DEBUG", "0") == "1" and raw_sample is not None:
        sample = json.dumps(raw_sample, ensure_ascii=False, default=str)
        diag += f"\n\nСырой ответ: {sample[:1500]}"

    return matched, diag
