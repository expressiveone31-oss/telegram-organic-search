# bot/services/telemetr_search.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import aiohttp
from typing import Any, Dict, List, Optional, Tuple

# ---------- ENV ----------
TELEM_TOKEN = os.getenv("TELEMETR_TOKEN", "").strip()

TELEM_USE_QUOTES    = os.getenv("TELEMETR_USE_QUOTES", "1") == "1"
TELEM_REQUIRE_EXACT = os.getenv("TELEMETR_REQUIRE_EXACT", "0") == "1"
TELEM_TRUST_QUERY   = os.getenv("TELEMETR_TRUST_QUERY", "1") == "1"

TELEM_MIN_VIEWS = int(os.getenv("TELEMETR_MIN_VIEWS", "0") or 0)
TELEM_PAGES     = max(1, int(os.getenv("TELEMETR_PAGES", "2") or 2))

TELEM_BASE_URL = "https://api.telemetr.me"


# ---------- helpers ----------

def _normalize_seed(seed: str) -> str:
    s = (seed or "").strip()
    if TELEM_USE_QUOTES and s and not (s.startswith('"') and s.endswith('"')):
        return f"\"{s}\""
    return s

def _as_dict(it: Any) -> Dict[str, Any]:
    """
    Telemetr может прислать строку вместо объекта.
    Приводим ко внутреннему безопасному словарю.
    """
    if isinstance(it, dict):
        return it
    if isinstance(it, str):
        return {"text": it}
    # на всякий случай — ничего не знаем про тип:
    return {}

def _body_from_item(it: Any) -> str:
    """
    Достаём текст поста безопасно для любого it.
    """
    d = _as_dict(it)
    parts: List[str] = []
    for k in ("title", "text", "caption"):
        v = d.get(k)
        if v:
            v = str(v).strip()
            if v:
                parts.append(v)
    # если в словаре ничего нет, но пришла сырая строка — она уже
    # будет в d["text"] благодаря _as_dict
    return "\n".join(parts).strip()

def _contains_exact(needle: str, haystack: str) -> bool:
    return bool(needle and haystack and needle in haystack)

def _views_of(it: Any) -> int:
    """
    Безопасно вытаскиваем просмотры.
    """
    d = _as_dict(it)
    v = d.get("views") or d.get("views_count") or 0
    try:
        return int(v)
    except Exception:
        return 0

def _link_of(it: Any) -> str:
    d = _as_dict(it)
    for k in ("display_url", "url", "link"):
        v = d.get(k)
        if v:
            return str(v)
    media = d.get("media")
    if isinstance(media, dict):
        v = media.get("display_url")
        if v:
            return str(v)
    return ""


# ---------- Telemetr API ----------

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
        if not isinstance(data, dict) or data.get("status") != "ok":
            return [], {"error": data}

        resp_obj = data.get("response") or {}
        items = resp_obj.get("items") or []
        # возвращаем «как есть»: дальше везде жёсткая нормализация _as_dict
        return items, {
            "count": resp_obj.get("count"),
            "total_count": resp_obj.get("total_count"),
        }


# ---------- Public ----------

async def search_telemetr(
    seeds: List[str],
    since: str,
    until: str,
    *,
    session: Optional[aiohttp.ClientSession] = None,
) -> Tuple[List[Dict[str, Any]], str]:
    """
    Возвращает:
      matched: список словарей с полями постов + служебными _seed, _link
      diag: текст диагностики
    Все элементы matched — гарантированно dict (никаких str внутри).
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

            items_all: List[Any] = []
            for page in range(1, TELEM_PAGES + 1):
                try:
                    items, meta = await _fetch_page(session, q, since, until, page)
                except Exception as e:
                    diag.append(f"seed='{raw_seed}': fetch page={page} error: {e!r}")
                    break

                # Ничего не предполагаем о типах — только считаем
                fetched_total += len(items)
                items_all.extend(items)

                # Telemetr отдаёт по 50 на страницу — значит можно прерываться,
                # если пришло меньше 50.
                if len(items) < 50:
                    break

            # жёсткая нормализация + фильтр по просмотрам
            norm: List[Dict[str, Any]] = []
            for it in items_all:
                d = _as_dict(it)
                if not d:
                    malformed += 1
                    continue
                if _views_of(d) >= TELEM_MIN_VIEWS:
                    norm.append(d)
            filtered_by_views = len(norm)

            # сопоставление
            for d in norm:
                body = _body_from_item(d)  # безопасно для любых входов
                ok = True
                if TELEM_REQUIRE_EXACT:
                    if body:
                        ok = _contains_exact(raw_seed, body)
                    else:
                        ok = TELEM_TRUST_QUERY  # доверяем совпадению запроса, даже без текста
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

