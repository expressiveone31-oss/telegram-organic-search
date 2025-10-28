# bot/services/telemetr_search.py
# -*- coding: utf-8 -*-

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

# ---------------------------------------------------------------------------
# ENV
# ---------------------------------------------------------------------------

TELEM_TOKEN = (os.getenv("TELEMETR_TOKEN") or "").strip()

TELEM_USE_QUOTES = os.getenv("TELEMETR_USE_QUOTES", "1") == "1"
TELEM_REQUIRE_EXACT = os.getenv("TELEMETR_REQUIRE_EXACT", "0") == "1"
TELEM_TRUST_QUERY = os.getenv("TELEMETR_TRUST_QUERY", "1") == "1"

# Минимум просмотров для поста, чтобы пройти первичный фильтр
TELEM_MIN_VIEWS = int(os.getenv("TELEMETR_MIN_VIEWS", "0") or 0)

# Сколько страниц вытягиваем у Telemetr (по 50 элементов на страницу)
TELEM_PAGES = max(1, int(os.getenv("TELEMETR_PAGES", "2") or 2))

TELEM_BASE_URL = "https://api.telemetr.me"

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _normalize_seed(seed: str) -> str:
    """
    По желанию — оборачиваем поисковую фразу в кавычки.
    Это даёт Telemetr более точный поиск по цитате.
    """
    s = (seed or "").strip()
    if not s:
        return s
    if TELEM_USE_QUOTES and not (s.startswith('"') and s.endswith('"')):
        return f'"{s}"'
    return s


def _as_dict(it: Any) -> Dict[str, Any]:
    """
    Telemetr может вернуть строку (например, body целиком) вместо dict.
    Всегда приводим к словарю, чтобы downstream-логика была безопасна.
    """
    if isinstance(it, dict):
        return it
    if isinstance(it, str):
        return {"text": it}
    return {}


def _text_from_item(d: Dict[str, Any]) -> str:
    """
    Собираем текст поста из возможных полей.
    """
    parts: List[str] = []
    for key in ("title", "text", "caption"):
        v = (d.get(key) or "").strip()
        if v:
            parts.append(v)
    return "\n".join(parts).strip()


def _contains_exact(needle: str, haystack: str) -> bool:
    """
    Простая проверка подстроки (для режима REQUIRE_EXACT).
    """
    return bool(needle and haystack and needle in haystack)


def _views_of(d: Dict[str, Any]) -> int:
    """
    Достаём кол-во просмотров из разных возможных полей.
    """
    v = d.get("views") or d.get("views_count") or 0
    try:
        return int(v)
    except Exception:
        return 0


def _link_of(d: Dict[str, Any]) -> str:
    """
    Унифицируем ссылку на сообщение.
    """
    return d.get("display_url") or d.get("url") or d.get("link") or ""


# ---------------------------------------------------------------------------
# Telemetr API
# ---------------------------------------------------------------------------


async def _fetch_page(
    session: aiohttp.ClientSession,
    query: str,
    since: str,
    until: str,
    page: int,
    limit: int = 50,
) -> Tuple[List[Any], Dict[str, Any]]:
    """
    Один вызов к Telemetr: /channels/posts/search
    Возвращает «сырые» items (они могут быть dict или str) и метаданные.
    """
    if not TELEM_TOKEN:
        raise RuntimeError("TELEMETR_TOKEN is not set")

    params = {
        "query": query,
        "date_from": since,  # формат YYYY-MM-DD
        "date_to": until,    # формат YYYY-MM-DD
        "limit": str(limit),
        "page": str(page),
    }
    headers = {"Authorization": f"Bearer {TELEM_TOKEN}"}

    url = f"{TELEM_BASE_URL}/channels/posts/search"
    async with session.get(url, params=params, headers=headers, timeout=30) as resp:
        # Не фиксируем content_type, Telemetr иногда отдаёт пустой
        data = await resp.json(content_type=None)

    if not isinstance(data, dict) or (data.get("status") != "ok"):
        # Вернём «пусто», но с ошибкой в метаданных
        return [], {"error": data}

    resp_obj = data.get("response") or {}
    items = resp_obj.get("items") or []
    meta = {
        "count": resp_obj.get("count"),
        "total_count": resp_obj.get("total_count"),
    }
    return items, meta


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------


async def search_telemetr(
    seeds: List[str],
    since: str,
    until: str,
    *,
    session: Optional[aiohttp.ClientSession] = None,
) -> Tuple[List[Dict[str, Any]], str]:
    """
    Главная функция Telemetr-поиска.
    Возвращает (список совпадений, диагностику-строку).
    Каждый элемент результата — dict, дополненный полями:
      - _seed   : исходная фраза, по которой найдено
      - _link   : ссылка на пост
      - _body   : собранный текст поста
    """
    seeds_raw = [s.strip() for s in (seeds or []) if s and s.strip()]
    if not seeds_raw:
        return [], "Telemetr: нет фраз для поиска"

    # Готовим фразы для запроса
    seeds_q = [_normalize_seed(s) for s in seeds_raw]

    diag: List[str] = []
    diag.append(
        "Telemetr cfg: "
        f"strict={'on' if TELEM_REQUIRE_EXACT else 'off'}, "
        f"quotes={'on' if TELEM_USE_QUOTES else 'off'}, "
        f"trust={'on' if TELEM_TRUST_QUERY else 'off'}, "
        f"min_views={TELEM_MIN_VIEWS}, pages={TELEM_PAGES}"
    )

    own_session = False
    if session is None:
        own_session = True
        session = aiohttp.ClientSession()

    results: List[Dict[str, Any]] = []
    total_candidates = 0

    try:
        for idx, raw_seed in enumerate(seeds_raw):
            q = seeds_q[idx]

            fetched_total = 0
            malformed = 0
            local_candidates = 0
            local_matched = 0

            page_items_all: List[Any] = []

            # Пагинация
            for page in range(1, TELEM_PAGES + 1):
                try:
                    items, meta = await _fetch_page(session, q, since, until, page)
                except Exception as e:
                    diag.append(f"seed='{raw_seed}': fetch error on page {page}: {e!r}")
                    break

                fetched_total += len(items)
                page_items_all.extend(items)

                # Если меньше лимита — дальше страниц нет
                if len(items) < 50:
                    break

            # Нормализуем и фильтруем
            normalized: List[Dict[str, Any]] = []
            for it in page_items_all:
                d = _as_dict(it)
                if not d:
                    malformed += 1
                    continue
                if _views_of(d) < TELEM_MIN_VIEWS:
                    continue
                normalized.append(d)

            local_candidates = len(normalized)
            total_candidates += local_candidates

            # Локальная валидация совпадений
            for d in normalized:
                body = _text_from_item(d)

                match_ok = True
                if TELEM_REQUIRE_EXACT:
                    # Если текста нет — решаем, доверять ли самому факту попадания по запросу
                    if body:
                        match_ok = _contains_exact(raw_seed, body)
                    else:
                        match_ok = TELEM_TRUST_QUERY

                if match_ok:
                    out = dict(d)  # копия
                    out["_seed"] = raw_seed
                    out["_link"] = _link_of(d)
                    out["_body"] = body
                    results.append(out)
                    local_matched += 1

            diag.append(
                f"seed='{raw_seed}': fetched={fetched_total}, "
                f"malformed={malformed}, candidates={local_candidates}, "
                f"matched={local_matched}"
            )

        diag.append(f"total_candidates={total_candidates}, total_matched={len(results)}")
        return results, "\n".join(diag)

    finally:
        if own_session and session:
            await session.close()
