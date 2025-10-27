# bot/services/telemetr_search.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import aiohttp
from typing import Any, Dict, List, Optional, Tuple

# ==========================
# ENVIRONMENT VARIABLES
# ==========================

TELEM_TOKEN = os.getenv("TELEMETR_TOKEN", "").strip()

# поведение поиска
TELEM_USE_QUOTES    = os.getenv("TELEMETR_USE_QUOTES", "1") == "1"     # оборачивать фразы в кавычки
TELEM_REQUIRE_EXACT = os.getenv("TELEMETR_REQUIRE_EXACT", "1") == "1"  # искать точное совпадение
TELEM_TRUST_QUERY   = os.getenv("TELEMETR_TRUST_QUERY", "1") == "1"    # считать совпадением без текста

# ограничения
TELEM_MIN_VIEWS = int(os.getenv("TELEMETR_MIN_VIEWS", "100") or 100)
TELEM_PAGES     = max(1, int(os.getenv("TELEMETR_PAGES", "3") or 3))

TELEM_BASE_URL = "https://api.telemetr.me"


# ==========================
# HELPERS
# ==========================

def _normalize_seed(seed: str) -> str:
    """Добавляем кавычки, если нужно"""
    s = (seed or "").strip()
    if TELEM_USE_QUOTES and s and not (s.startswith('"') and s.endswith('"')):
        return f"\"{s}\""
    return s


def _as_dict(it: Any) -> Dict[str, Any]:
    """Telemetr иногда возвращает строку вместо dict — приводим всё к словарю"""
    if isinstance(it, dict):
        return it
    if isinstance(it, str):
        return {"text": it}
    return {}


def _body_from_item(it: Dict[str, Any]) -> str:
    """Собираем текст поста (title + text + caption)"""
    parts: List[str] = []
    for k in ("title", "text", "caption"):
        v = (it.get(k) or "").strip()
        if v:
            parts.append(v)
    return "\n".join(parts).strip()


def _contains_exact(needle: str, haystack: str) -> bool:
    """Проверка наличия подстроки"""
    return bool(needle and haystack and needle in haystack)


def _views_of(it: Dict[str, Any]) -> int:
    """Безопасное извлечение числа просмотров"""
    v = it.get("views") or it.get("views_count") or 0
    try:
        return int(v)
    except Exception:
        return 0


def _link_of(it: Dict[str, Any]) -> str:
    """Безопасное извлечение ссылки"""
    return it.get("display_url") or it.get("url") or it.get("link") or ""


# ==========================
# TELEMETR API
# ==========================

async def _fetch_page(
    session: aiohttp.ClientSession,
    query: str,
    since: str,
    until: str,
    page: int,
    limit: int = 50,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Запрос одной страницы результатов у Telemetr"""
    if not TELEM_TOKEN:
        raise RuntimeError("TELEMETR_TOKEN is not set")

    params = {
        "query": query,
        "date_from": since,
        "date_to": until,
        "limit": str(limit),
        "page": str(page),
    }
    headers = {"Authorization": f"Bearer {TELEM_TOKEN}"}
    url = f"{TELEM_BASE_URL}/channels/posts/search"

    async with session.get(url, params=params, headers=headers, timeout=30) as resp:
        data = await resp.json(content_type=None)

    # если что-то не так — возвращаем пустой список
    if not isinstance(data, dict) or data.get("status") != "ok":
        return [], {"error": data}

    resp_obj = data.get("response") or {}
    raw_items = resp_obj.get("items") or []

    # нормализуем все элементы в dict
    items: List[Dict[str, Any]] = []
    malformed = 0
    for it in raw_items:
        d = _as_dict(it)
        if d:
            items.append(d)
        else:
            malformed += 1

    meta = {
        "count": resp_obj.get("count"),
        "total_count": resp_obj.get("total_count"),
        "malformed": malformed,
    }
    return items, meta


# ==========================
# PUBLIC ENTRYPOINT
# ==========================

async def search_telemetr(
    seeds: List[str],
    since: str,
    until: str,
    *,
    session: Optional[aiohttp.ClientSession] = None,
) -> Tuple[List[Dict[str, Any]], str]:
    """
    Главная функция поиска по Telemetr API
    """
    seeds_raw = [s.strip() for s in (seeds or []) if s and s.strip()]
    if not seeds_raw:
        return [], "Telemetr: нет фраз для поиска"

    seeds_q = [_normalize_seed(s) for s in seeds_raw]

    diag: List[str] = []
    diag.append(
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
        for idx, raw_seed in enumerate(seeds_raw):
            q = seeds_q[idx]
            fetched_total = 0
            filtered_by_views = 0
            local_matched = 0
            malformed = 0

            all_items: List[Dict[str, Any]] = []

            # цикл по страницам
            for page in range(1, TELEM_PAGES + 1):
                try:
                    items, meta = await _fetch_page(session, q, since, until, page)
                except Exception as e:
                    diag.append(f"seed='{raw_seed}': fetch page={page} error: {e!r}")
                    break

                fetched_total += len(items)
                malformed += int(meta.get("malformed") or 0)
                all_items.extend(items)
                if len(items) < 50:
                    break

            # фильтруем по просмотрам
            norm: List[Dict[str, Any]] = [
                d for d in all_items if _views_of(d) >= TELEM_MIN_VIEWS
            ]
            filtered_by_views = len(norm)

            # фильтр совпадений
            for d in norm:
                body = _body_from_item(d)
                ok = True
                if TELEM_REQUIRE_EXACT:
                    if body:
                        ok = _contains_exact(raw_seed, body)
                    else:
                        ok = TELEM_TRUST_QUERY
                if ok:
                    d["_seed"] = raw_seed
                    d["_link"] = _link_of(d)
                    matched.append(d)
                    local_matched += 1

            total_candidates += filtered_by_views
            diag.append(
                f"seed='{raw_seed}': fetched={fetched_total} malformed={malformed} "
                f"filtered_by_views={filtered_by_views} matched={local_matched}"
            )

        diag.append(f"total_candidates={total_candidates}, total_matched={len(matched)}")
        return matched, "\n".join(diag)

    finally:
        if own_session and session:
            await session.close()
