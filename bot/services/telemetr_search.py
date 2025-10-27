# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import aiohttp
from typing import Any, Dict, List, Optional, Tuple

# ---------- ENV ----------
TELEM_TOKEN = os.getenv("TELEMETR_TOKEN", "").strip()

# поведение поиска
TELEM_USE_QUOTES    = os.getenv("TELEMETR_USE_QUOTES", "1") == "1"   # оборачивать запрос в кавычки
TELEM_REQUIRE_EXACT = os.getenv("TELEMETR_REQUIRE_EXACT", "1") == "1" # оставляем строгое совпадение
TELEM_TRUST_QUERY   = os.getenv("TELEMETR_TRUST_QUERY", "1") == "1"   # считать совпадением, если текста нет, но есть ссылка

# ограничители
TELEM_MIN_VIEWS = int(os.getenv("TELEMETR_MIN_VIEWS", "0") or 0)       # можно поднимать до 100+
TELEM_PAGES     = max(1, int(os.getenv("TELEMETR_PAGES", "3") or 3))   # сколько страниц Telemetr перебирать (по 50 шт)

TELEM_BASE_URL = "https://api.telemetr.me"


# ---------- helpers ----------

def _normalize_seed(seed: str) -> str:
    s = (seed or "").strip()
    if TELEM_USE_QUOTES and s and not (s.startswith('"') and s.endswith('"')):
        return f"\"{s}\""
    return s

def _coerce_dict(it: Any) -> Dict[str, Any]:
    """
    Telemetr иногда возвращает элемент списком строк.
    Превращаем всё в словарь одинаковой формы.
    """
    if isinstance(it, dict):
        return it
    if isinstance(it, str):
        # кладём строку как текст; остальные поля пустые
        return {"text": it}
    # неожиданный тип
    return {}

def _body_from_item(it: Any) -> str:
    """
    Собираем полный текст поста. Терпим любой тип.
    """
    if isinstance(it, str):
        return it.strip()
    if not isinstance(it, dict):
        return ""
    parts: List[str] = []
    for k in ("title", "text", "caption"):
        v = (it.get(k) or "").strip()
        if v:
            parts.append(v)
    return "\n".join(parts).strip()

def _contains_exact(needle: str, haystack: str) -> bool:
    return bool(needle and haystack and needle in haystack)

def _views_of(it: Any) -> int:
    if isinstance(it, dict):
        v = it.get("views") or it.get("views_count") or 0
    else:
        v = 0
    try:
        return int(v)
    except Exception:
        return 0

def _link_of(it: Any) -> str:
    if isinstance(it, dict):
        return it.get("display_url") or it.get("url") or it.get("link") or ""
    return ""


# ---------- Telemetr API ----------

async def _fetch_page(
    session: aiohttp.ClientSession,
    query: str,
    since: str,
    until: str,
    page: int,
    limit: int = 50,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
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

    # Базовая проверка формата
    if not isinstance(data, dict) or data.get("status") != "ok":
        return [], {"error": data}

    resp_obj = data.get("response") or {}
    raw_items = resp_obj.get("items") or []

    # >>> САМОЕ ВАЖНОЕ: принудительная нормализация <<<
    items: List[Dict[str, Any]] = []
    malformed = 0
    for it in raw_items:
        d = _coerce_dict(it)
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


# ---------- Public ----------

async def search_telemetr(
    seeds: List[str],
    since: str,
    until: str,
    *,
    session: Optional[aiohttp.ClientSession] = None,
) -> Tuple[List[Dict[str, Any]], str]:
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
            malformed_pages = 0

            items_all: List[Dict[str, Any]] = []

            for page in range(1, TELEM_PAGES + 1):
                try:
                    page_items, meta = await _fetch_page(session, q, since, until, page)
                except Exception as e:
                    diag.append(f"seed='{raw_seed}': fetch page={page} error: {e!r}")
                    break

                fetched_total += len(page_items)
                malformed_pages += int(meta.get("malformed") or 0)
                items_all.extend(page_items)

                # Telemetr обычно отдаёт по 50 на страницу — если меньше, дальше нечего
                if len(page_items) < 50:
                    break

            # фильтруем по просмотрам (тут уже всё dict)
            norm: List[Dict[str, Any]] = [d for d in items_all if _views_of(d) >= TELEM_MIN_VIEWS]
            filtered_by_views = len(norm)

            # строгая проверка совпадения (при необходимости)
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
                f"seed='{raw_seed}': fetched={fetched_total} malformed_in_pages={malformed_pages} "
                f"after_views={filtered_by_views} matched={local_matched}"
            )

        diag.append(f"total_candidates={total_candidates}, total_matched={len(matched)}")
        return matched, "\n".join(diag)

    finally:
        if own_session and session:
            await session.close()
