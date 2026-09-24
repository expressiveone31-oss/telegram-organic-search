# -*- coding: utf-8 -*-
"""
Поиск органики в Telegram через Telemetr API.
"""
from __future__ import annotations

import logging
import os
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

import httpx

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


def _link_of(it: Dict[str, Any]) -> str:
    return it.get("display_url") or it.get("url") or it.get("link") or ""


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


_QUOTES_RE = re.compile(r"[«»„“”\"'`]")
_SPACES_RE = re.compile(r"\s+")


def _normalize(s: str) -> str:
    """Нормализует текст для сравнения: нижний регистр, убирает кавычки и лишние пробелы."""
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = _QUOTES_RE.sub("", s)
    s = s.replace("ё", "е")
    return _SPACES_RE.sub(" ", s).strip()


def _contains_seed(seed: str, body: str) -> bool:
    """Проверяет что тело поста содержит фразу посева (нормализованно)."""
    return _normalize(seed) in _normalize(body)


async def _fetch_page(
    client: httpx.AsyncClient,
    token: str,
    query: str,
    since: str,
    until: str,
    page: int,
) -> List[Any]:
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
        return []
    except Exception as e:
        logger.error("Telemetr request failed for query=%r: %s", query, e)
        return []

    if not isinstance(data, dict) or data.get("status") != "ok":
        logger.error("Telemetr bad response for query=%r: %s", query, str(data)[:300])
        return []

    return (data.get("response") or {}).get("items") or []


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
    skipped_no_body = 0
    skipped_no_match = 0

    async with httpx.AsyncClient() as client:
        for raw_seed in seeds:
            q = _normalize_seed(raw_seed, cfg["use_quotes"])
            items_all: List[Any] = []

            for page in range(1, cfg["pages"] + 1):
                items = await _fetch_page(client, cfg["token"], q, since, until, page)
                items_all.extend(items)
                if len(items) < 50:
                    break

            logger.info("Telemetr seed=%r fetched=%d", raw_seed, len(items_all))

            # Лог первого результата для диагностики структуры ответа
            if items_all:
                first = items_all[0]
                logger.info("Telemetr first item keys=%s views=%s link=%s",
                            list(first.keys()) if isinstance(first, dict) else type(first),
                            _views_of(first) if isinstance(first, dict) else "?",
                            _link_of(first) if isinstance(first, dict) else "?")
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
                it["_seed"] = raw_seed
                it["_link"] = _link_of(it)
                matched.append(it)

            if skipped_views:
                logger.info("Telemetr seed=%r: skipped %d by min_views=%d", raw_seed, skipped_views, cfg["min_views"])

    diag = (
        f"seeds={len(seeds)}, matched={len(matched)}, "
        f"no_match={skipped_no_match}, no_body={skipped_no_body}, range={since}–{until}"
    )
    logger.info("Telemetr done: %s", diag)
    return matched, diag
