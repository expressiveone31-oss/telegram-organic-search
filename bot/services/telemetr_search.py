
# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import aiohttp
from typing import Any, Dict, List, Optional, Tuple

TELEM_TOKEN = os.getenv("TELEMETR_TOKEN", "").strip()

TELEM_USE_QUOTES    = os.getenv("TELEMETR_USE_QUOTES", "1") == "1"
TELEM_REQUIRE_EXACT = os.getenv("TELEMETR_REQUIRE_EXACT", "1") == "1"
TELEM_TRUST_QUERY   = os.getenv("TELEMETR_TRUST_QUERY", "1") == "1"

TELEM_MIN_VIEWS = int(os.getenv("TELEMETR_MIN_VIEWS", "0") or 0)
TELEM_PAGES     = max(1, int(os.getenv("TELEMETR_PAGES", "3") or 3))

TELEM_BASE_URL = "https://api.telemetr.me"

def _normalize_seed(seed: str) -> str:
    s = (seed or "").strip()
    if TELEM_USE_QUOTES and s and not (s.startswith('"') and s.endswith('"')):
        return f'"{s}"'
    return s

def _as_dict(it: Any) -> Dict[str, Any]:
    if isinstance(it, dict):
        return it
    if isinstance(it, str):
        return {"text": it}
    return {}

def _body_from_item(it: Dict[str, Any]) -> str:
    parts: List[str] = []
    for k in ("title", "text", "caption"):
        v = (it.get(k) or "").strip()
        if v:
            parts.append(v)
    return "\n".join(parts).strip()

def _contains_exact(needle: str, haystack: str) -> bool:
    return bool(needle and haystack and needle in haystack)

def _views_of(it: Dict[str, Any]) -> int:
    v = it.get("views") or it.get("views_count") or 0
    try:
        return int(v)
    except Exception:
        return 0

def _link_of(it: Dict[str, Any]) -> str:
    return it.get("display_url") or it.get("url") or it.get("link") or ""

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
        return items, {
            "count": resp_obj.get("count"),
            "total_count": resp_obj.get("total_count"),
        }

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

    own_session = False
    if session is None:
        own_session = True
        session = aiohttp.ClientSession()

    matched: List[Dict[str, Any]] = []
    try:
        for idx, raw_seed in enumerate(seeds_raw):
            q = seeds_q[idx]

            items_all: List[Any] = []
            for page in range(1, TELEM_PAGES + 1):
                try:
                    items, _meta = await _fetch_page(session, q, since, until, page)
                except Exception:
                    break
                items_all.extend(items)
                if len(items) < 50:
                    break

            norm: List[Dict[str, Any]] = []
            for it in items_all:
                d = _as_dict(it)
                if not d:
                    continue
                if _views_of(d) >= TELEM_MIN_VIEWS:
                    norm.append(d)

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

        return matched, "ok"

    finally:
        if own_session and session:
            await session.close()
