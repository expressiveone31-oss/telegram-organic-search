# bot/services/telemetr_search.py
# -*- coding: utf-8 -*-

"""
Поиск постов в Telegram через Telemetr API.

Ключевые фичи:
- Строгое/нестрогое сопоставление (TELEMETR_REQUIRE_EXACT)
- Заключение исходной фразы в кавычки для точного поиска на стороне Telemetr (TELEMETR_USE_QUOTES)
- «Доверительный» режим, когда Telemetr нашёл, но у элемента нет полноценного текста (TELEMETR_TRUST_QUERY)
- Фильтр по просмотрам и пагинация
- Развёрнутая диагностика (что получили и почему отбраковали)

Ожидаемые переменные окружения:
- TELEMETR_TOKEN           : str  (обязательно)
- TELEMETR_USE_QUOTES      : "0"|"1" (по умолч. "1")
- TELEMETR_REQUIRE_EXACT   : "0"|"1" (по умолч. "0")
- TELEMETR_TRUST_QUERY     : "0"|"1" (по умолч. "1")  <-- новинка
- TELEMETR_MIN_VIEWS       : int  (по умолч. 0)
- TELEMETR_PAGES           : int  (по умолч. 2, по 50 элементов страницей)
"""

from __future__ import annotations

import os
import asyncio
import aiohttp
from typing import Any, Dict, List, Optional, Tuple

# ---------- Настройки из ENV ----------

TELEM_TOKEN = os.getenv("TELEMETR_TOKEN", "").strip()

TELEM_USE_QUOTES = os.getenv("TELEMETR_USE_QUOTES", "1") == "1"
TELEM_REQUIRE_EXACT = os.getenv("TELEMETR_REQUIRE_EXACT", "0") == "1"
TELEM_TRUST_QUERY = os.getenv("TELEMETR_TRUST_QUERY", "1") == "1"   # новинка

TELEM_MIN_VIEWS = int(os.getenv("TELEMETR_MIN_VIEWS", "0") or 0)
TELEM_PAGES = max(1, int(os.getenv("TELEMETR_PAGES", "2") or 2))

# Базовый эндпоинт Telemetr (документация: /channels/posts/search)
TELEM_BASE_URL = "https://api.telemetr.me"


# ---------- Вспомогательные ----------

def _normalize_seed(seed: str) -> str:
    s = (seed or "").strip()
    if TELEM_USE_QUOTES and s and not (s.startswith('"') and s.endswith('"')):
        # Точный поиск на стороне Telemetr
        return f"\"{s}\""
    return s


def _body_from_item(it: Dict[str, Any]) -> str:
    """
    Собираем максимально возможный «текст» элемента:
    title + text + подписи к медиаконтенту, если они есть.
    Telemetr иногда возвращает неполный/урезанный текст.
    """
    parts: List[str] = []
    for k in ("title", "text", "caption"):
        v = (it.get(k) or "").strip()
        if v:
            parts.append(v)
    return "\n".join(parts).strip()


def _contains_exact(needle: str, haystack: str) -> bool:
    """
    Простейшее точное вхождение (чувствительно к регистру).
    На вход подаём НЕ нормализованный seed (без кавычек).
    """
    if not needle or not haystack:
        return False
    return needle in haystack


def _views_of(it: Dict[str, Any]) -> int:
    v = it.get("views") or it.get("views_count") or 0
    try:
        return int(v)
    except Exception:
        return 0


def _link_of(it: Dict[str, Any]) -> str:
    """
    Пытаемся собрать стабильную ссылку. Telemetr обычно отдаёт display_url
    или внутренний url/link. Берём всё, что есть.
    """
    return it.get("display_url") or it.get("url") or it.get("link") or ""


# ---------- Вызов Telemetr API ----------

async def _fetch_page(
    session: aiohttp.ClientSession,
    query: str,
    since: str,
    until: str,
    page: int,
    limit: int = 50,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Возвращает (items, raw_meta).
    Telemetr сортирует по релевантности/дате. Мы фильтруем локально.
    """
    if not TELEM_TOKEN:
        raise RuntimeError("TELEMETR_TOKEN is not set")

    params = {
        "query": query,
        "date_from": since,  # форматы: YYYY-MM-DD
        "date_to": until,
        "limit": str(limit),
        "page": str(page),
    }
    headers = {"Authorization": f"Bearer {TELEM_TOKEN}"}

    url = f"{TELEM_BASE_URL}/channels/posts/search"
    async with session.get(url, params=params, headers=headers, timeout=30) as resp:
        data = await resp.json(content_type=None)
        if (data or {}).get("status") != "ok":
            # вернём пусто + «сырую» мету для диагностики
            return [], {"error": data}

        resp_obj = data.get("response") or {}
        items = resp_obj.get("items") or []
        return items, {"count": resp_obj.get("count"), "total_count": resp_obj.get("total_count")}


# ---------- Публичный API модуля ----------

async def search_telemetr(
    seeds: List[str],
    since: str,
    until: str,
    *,
    session: Optional[aiohttp.ClientSession] = None,
) -> Tuple[List[Dict[str, Any]], str]:
    """
    Ищет посты в Telemetr по списку фраз `seeds` в диапазоне дат [since; until].
    Возвращает (список_совпадений, строка_диагностики).

    Совпадение определяется так:
      - если TELEMETR_REQUIRE_EXACT=0 → принимаем любой элемент Telemetr, прошедший фильтры по просмотрам
      - если TELEMETR_REQUIRE_EXACT=1:
            * если у элемента есть текст → проверяем точное вхождение «как есть»
            * если текста нет/он явно урезан → принимаем, если TELEMETR_TRUST_QUERY=1
    """
    seeds_raw = [s.strip() for s in (seeds or []) if s and s.strip()]
    if not seeds_raw:
        return [], "Telemetr: нет фраз для поиска"

    # Соберём нормализованные (с кавычками при необходимости)
    seeds_q = [_normalize_seed(s) for s in seeds_raw]

    # Диагностика
    diag_lines: List[str] = []
    diag_lines.append(
        f"Telemetr diag: strict={'on' if TELEM_REQUIRE_EXACT else 'off'}, "
        f"quotes={'on' if TELEM_USE_QUOTES else 'off'}, "
        f"trust={'on' if TELEM_TRUST_QUERY else 'off'}, "
        f"min_views={TELEM_MIN_VIEWS}, pages={TELEM_PAGES}"
    )

    own_session = False
    if session is None:
        own_session = True
        session = aiohttp.ClientSession()

    matched: List[Dict[str, Any]] = []
    total_candidates = 0

    try:
        # Идём по всем seed-строкам: суммируем совпадения
        for idx, raw_seed in enumerate(seeds_raw):
            q = seeds_q[idx]

            local_candidates = 0
            local_matched = 0

            items_all: List[Dict[str, Any]] = []
            # Пагинируем (Telemetr по 50 шт/страница)
            for page in range(1, TELEM_PAGES + 1):
                try:
                    items, meta = await _fetch_page(session, q, since, until, page)
                except Exception as e:
                    diag_lines.append(f"seed='{raw_seed}': fetch page={page} error: {e!r}")
                    break

                items_all.extend(items)
                # Если пришло меньше лимита — можно прекращать
                if len(items) < 50:
                    break

            # Фильтр по просмотрам
            filtered = [it for it in items_all if _views_of(it) >= TELEM_MIN_VIEWS]
            local_candidates = len(filtered)

            # Локальное сопоставление
            for it in filtered:
                body = _body_from_item(it)
                ok = True

                if TELEM_REQUIRE_EXACT:
                    if body:
                        ok = _contains_exact(raw_seed, body)
                    else:
                        # текста нет/он урезан → доверимся Telemetr, если разрешено
                        ok = TELEM_TRUST_QUERY

                if ok:
                    it["_seed"] = raw_seed
                    it["_link"] = _link_of(it)
                    matched.append(it)
                    local_matched += 1

            diag_lines.append(
                f"seed='{raw_seed}': fetched={len(items_all)} "
                f"filtered_by_views={local_candidates} matched={local_matched}"
            )
            total_candidates += local_candidates

        # Краткая сводка
        diag_lines.append(f"total_candidates={total_candidates}, total_matched={len(matched)}")

        return matched, "\n".join(diag_lines)

    finally:
        if own_session and session:
            await session.close()
