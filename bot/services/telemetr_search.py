# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import re
import unicodedata
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

# =======================
# ENV / настройки
# =======================

TELEM_TOKEN = (os.getenv("TELEMETR_TOKEN") or "").strip()
TELEM_BASE_URL = "https://api.telemetr.me"

# ВАЖНО: по умолчанию кавычки ВЫКЛ (можно включить env-переменной)
TELEM_USE_QUOTES: bool = os.getenv("TELEMETR_USE_QUOTES", "0") == "1"

# Строгий локальный матч (как вы просили)
TELEM_REQUIRE_EXACT: bool = os.getenv("TELEMETR_REQUIRE_EXACT", "1") == "1"
TELEM_TRUST_QUERY: bool = os.getenv("TELEMETR_TRUST_QUERY", "0") == "1"

TELEM_MIN_VIEWS: int = int(os.getenv("TELEMETR_MIN_VIEWS", "0") or 0)
TELEM_PAGES: int = max(1, int(os.getenv("TELEMETR_PAGES", "50") or 50))

TELEM_DATE_TO_INCLUSIVE: bool = os.getenv("TELEMETR_DATE_TO_INCLUSIVE", "1") == "1"
ORGANIC_DEBUG: bool = os.getenv("ORGANIC_DEBUG", "1") == "1"

# =======================
# Вспомогательные
# =======================

def _normalize_seed(seed: str) -> str:
    s = (seed or "").strip()
    if TELEM_USE_QUOTES and s and not (s.startswith('"') and s.endswith('"')):
        return f"\"{s}\""
    return s

def _plus_one_day(d: str) -> str:
    if not d:
        return d
    try:
        # Обрабатываем случаи с временем (YYYY-MM-DDTHH:MM:SS)
        date_part = d.split("T")[0]
        dt = datetime.fromisoformat(date_part).date()
        return (dt + timedelta(days=1)).isoformat()
    except Exception:
        return d  # Возвращаем исходную строку при ошибке

def _as_dict(it: Any) -> Dict[str, Any]:
    if isinstance(it, dict):
        return it
    if isinstance(it, str):
        return {"text": it}
    return {}

def _body_from_item(it: Dict[str, Any]) -> str:
    parts: List[str] = []
    # Расширенный список полей для извлечения текста
    for k in ("title", "text", "caption", "alt_text", "description", "content"):
        v = (it.get(k) or "").strip()
        if v:
            parts.append(v)
    return "\n".join(parts).strip()

def _views_of(it: Dict[str, Any]) -> int:
    v = it.get("views") or it.get("views_count") or 0
    try:
        return int(v)
    except (ValueError, TypeError):
        return 0

def _link_of(it: Dict[str, Any]) -> str:
    return it.get("display_url") or it.get("url") or it.get("link") or ""

# ---- строгая проверка фразы без разрывов ----

def _norm_basic(s: str) -> str:
    if not s:
        return ""
    # Нормализация Unicode
    s = unicodedata.normalize("NFKC", s)
    # Замена всех видов тире на обычный дефис
    s = re.sub(r"[\-\u2013\u2014]", "-", s)
    # Замена всех видов кавычек на простые "
    s = re.sub(r"[\"\u201C\u201D\u00AB\u00BB]", '"', s)
    # Приведение к нижнему регистру
    s = s.lower()
    # Схлопывание пробелов
    s = re.sub(r"\s+", " ", s).strip()
    return s

_BOUNDARY_CLASS = r"[0-9A-Za-zА-Яа-яЁё_]"

def _contains_exact_phrase_word_boundary(needle: str, haystack: str) -> bool:
    n = _norm_basic(needle)
    h = _norm_basic(haystack)
    if not n or not h:
        return False
    
    # Создаем шаблон с границами слов и поддержкой множественных пробелов
    pattern = rf"\b{re.sub(r'\s+', r'\\s+', n)}\b"
    return re.search(pattern, h) is not None

# =======================
# Telemetr API
# =======================

async def _fetch_page(
    session: aiohttp.ClientSession,
    query: str,
    since: str,
    until: str,
    page: int,
    limit: int = 50,
) -> Tuple[List[Any], Dict[str, Any]]:
    if not TELEM_TOKEN:
        raise RuntimeError("TELEMETR_TOKEN is not set")

    date_to = _plus_one_day(until) if TELEM_DATE_TO_INCLUSIVE else until

    params = {
        "query": query,
        "date_from": since,
        "date_to": date_to,
        "limit": str(limit),
        "page": str(page),
    }
    headers = {"Authorization": f"Bearer {TELEM_TOKEN}"}

    url = f"{TELEM_BASE_URL}/channels/posts/search"
    async with session.get(url, params=params, headers=headers, timeout=45) as resp:
        try:
            data = await resp.json(content_type=None)
        except aiohttp.ContentTypeError:
            # Если ответ не JSON, возвращаем ошибку
            return [], {"error": f"Invalid JSON response: {await resp.text()}"}

        if not isinstance(data, dict) or data.get("status") != "ok":
            return [], {"error": data}

        resp_obj = data.get("response") or {}
        items = resp_obj.get("items") or []
        return items, {
            "count": resp_obj.get("count"),
            "total_count": resp_obj.get("total_count"),
        }

# =======================
# Публичный поиск
# =======================

async def search_telemetr(
    seeds: List[str],
    since: str,
    until: str,
    *,
    session: Optional[aiohttp.ClientSession] = None,
) -> Tuple[List[Dict[str, Any]], str]:
    # Исправление опечатки: было seeds_raw
    seeds_raw: List[str] = [s.strip() for s in (seeds or []) if s and s.strip()]
    if not seeds_raw:
        return [], "Telemetr: нет фраз для поиска"

    seeds_q: List[str] = [_normalize_seed(s) for s in seeds_raw]

    diag: List[str] = []
    diag.append(
        "Telemetr diag: "
        f"strict={'on' if TELEM_REQUIRE_EXACT else 'off'}, "
        f"quotes={'on' if TELEM_USE_QUOTES else 'off'}, "
        f"trust_no_text={'on' if TELEM_TRUST_QUERY else 'off'}, "
        f"min_views={TELEM_MIN_VIEWS}, pages={TELEM_PAGES}, "
        f"date_to_inclusive={'on' if TELEM_DATE_TO_INCLUSIVE else 'off'}"
    )

    own_session = False
    if session is None:
        own_session = True
        session = aiohttp.ClientSession()

    matched: List[Dict[str, Any]] = []
    total_candidates = 0

    # Для расширенной диагностики, если не найдём
