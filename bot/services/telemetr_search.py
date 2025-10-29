# bot/services/telemetr_search.py
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
        dt = datetime.fromisoformat(d).date()
        return (dt + timedelta(days=1)).isoformat()
    except Exception:
        return d

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

def _views_of(it: Dict[str, Any]) -> int:
    v = it.get("views") or it.get("views_count") or 0
    try:
        return int(v)
    except Exception:
        return 0

def _link_of(it: Dict[str, Any]) -> str:
    return it.get("display_url") or it.get("url") or it.get("link") or ""

# ---- строгая проверка фразы без разрывов ----

def _norm_basic(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s).lower()
    s = re.sub(r"\s+", " ", s).strip()
    return s

_BOUNDARY_CLASS = r"[0-9A-Za-zА-Яа-яЁё_]"
def _contains_exact_phrase_word_boundary(needle: str, haystack: str) -> bool:
    n = _norm_basic(needle)
    h = _norm_basic(haystack)
    if not n or not h:
        return False
    pattern = rf"(?<!{_BOUNDARY_CLASS}){re.escape(n)}(?!{_BOUNDARY_CLASS})"
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
        data = await resp.json(content_type=None)
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

    # для расширенной диагностики, если не найдём ничего
    debug_first_candidates: List[Dict[str, Any]] = []

    try:
        for idx, raw_seed in enumerate(seeds_raw):
            q = seeds_q[idx]

            fetched_total = 0
            malformed = 0
            filtered_by_views = 0
            local_matched = 0

            items_all: List[Any] = []
            for page in range(1, TELEM_PAGES + 1):
                try:
                    items, _meta = await _fetch_page(session, q, since, until, page)
                except Exception as e:
                    diag.append(f"seed='{raw_seed}': fetch page={page} error: {e!r}")
                    break

                fetched_total += len(items)
                items_all.extend(items)
                if len(items) < 50:
                    break

            norm: List[Dict[str, Any]] = []
            for it in items_all:
                d = _as_dict(it)
                if not d:
                    malformed += 1
                    continue
                if _views_of(d) >= TELEM_MIN_VIEWS:
                    norm.append(d)
            filtered_by_views = len(norm)

            # Сохраним первые 10 кандидатов в debug-список (если потом не будет совпадений)
            if ORGANIC_DEBUG and not debug_first_candidates:
                debug_first_candidates = norm[:10]

            for d in norm:
                body = _body_from_item(d)
                ok = True

                if TELEM_REQUIRE_EXACT:
                    if body:
                        ok = _contains_exact_phrase_word_boundary(raw_seed, body)
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

        # ------- Расширенная диагностика -------
        if ORGANIC_DEBUG:
            if matched:
                sample = []
                for it in matched[:10]:
                    link = it.get("_link") or it.get("display_url") or it.get("url") or it.get("link") or ""
                    if link:
                        seed_tag = it.get("_seed") or ""
                        sample.append(f"- {link}  (seed: {seed_tag})")
                if sample:
                    diag.append("sample_links:\n" + "\n".join(sample))
            else:
                # Ничего не нашли: покажем ПОЧЕМУ на примере первых кандидатов
                if debug_first_candidates:
                    diag.append("no_strict_hits__first_candidates:")
                    for i, it in enumerate(debug_first_candidates, 1):
                        link = _link_of(it)
                        body = _body_from_item(it)
                        nbody = _norm_basic(body)
                        diag.append(f"{i:02d}. {link or '(no link)'}")
                        # обрезаем нормализованный текст, чтобы увидеть, почему не совпало
                        diag.append(f"    body_norm: {nbody[:300]}{'…' if len(nbody) > 300 else ''}")

        return matched, "\n".join(diag)

    finally:
        if own_session and session:
            await session.close()
