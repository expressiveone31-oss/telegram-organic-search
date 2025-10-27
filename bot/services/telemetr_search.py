import os
import re
from typing import Any, Dict, List, Tuple
from html import unescape

import aiohttp

TELEMETR_BASE = os.getenv("TELEMETR_BASE", "https://api.telemetr.me")
TELEMETR_TOKEN = os.getenv("TELEMETR_TOKEN", "")

# настройки фильтра
TELEM_PAGES = int(os.getenv("TELEMETR_PAGES", "2"))            # страниц по 50
TELEM_MIN_VIEWS = int(os.getenv("TELEMETR_MIN_VIEWS", "0"))    # порог просмотров
TELEM_REQUIRE_EXACT = os.getenv("TELEMETR_REQUIRE_EXACT", "0") == "1"
TELEM_USE_QUOTES = os.getenv("TELEMETR_USE_QUOTES", "1") == "1"
TELEM_MAX_GAP = int(os.getenv("TELEMETR_MAX_GAP_WORDS", "3"))  # на будущее


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _contains_exact(needle: str, hay: str) -> bool:
    """точное вхождение (последовательность слов), без рег.вариантов"""
    n = _normalize(needle).lower()
    h = _normalize(hay).lower()
    return n in h


async def _fetch_page(session: aiohttp.ClientSession, query: str, since: str, until: str, offset: int) -> Dict[str, Any]:
    url = f"{TELEMETR_BASE}/channels/posts/search"
    headers = {"Authorization": f"Bearer {TELEMETR_TOKEN}"}
    params = {
        "query": query,
        "date_from": since,
        "date_to": until,
        "limit": 50,
        "offset": offset
    }
    async with session.get(url, headers=headers, params=params, timeout=30) as resp:
        resp.raise_for_status()
        return await resp.json()


async def search_telemetr(seeds: List[str], since: str, until: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Возвращает (список_совпадений, мета-диагностика)
    """
    if not TELEMETR_TOKEN:
        raise RuntimeError("TELEMETR_TOKEN не задан")

    results: List[Dict[str, Any]] = []
    meta = {"pages": TELEM_PAGES, "total": 0, "per_seed": {}}

    async with aiohttp.ClientSession(raise_for_status=True) as session:
        for seed in seeds:
            raw_seed = seed.strip()
            if not raw_seed:
                continue

            query = raw_seed
            if TELEM_USE_QUOTES or TELEM_REQUIRE_EXACT:
                # точная фраза в Telemetr
                query = f"\"{raw_seed}\""

            matched_here = 0
            total_here = 0

            for p in range(TELEM_PAGES):
                offset = p * 50
                data = await _fetch_page(session, query, since, until, offset)
                # ожидаемый ответ: {status, response:{count,total_count,items:[...]}}
                resp = (data or {}).get("response") or {}
                items = resp.get("items") or []
                total_here += len(items)
                meta["total"] += len(items)

                for it in items:
                    # полотно текста/заголовка
                    body = _normalize(unescape((it.get("text") or "") + " " + (it.get("title") or "")))
                    # в некоторых кейсах Telemetr отдаёт display_url
                    url = it.get("display_url") or it.get("url") or ""
                    views = int(it.get("views") or 0)

                    if views < TELEM_MIN_VIEWS:
                        continue

                    ok = True
                    if TELEM_REQUIRE_EXACT:
                        ok = _contains_exact(raw_seed, body)

                    if not ok:
                        continue

                    matched_here += 1
                    results.append({
                        "title": it.get("title") or it.get("text") or "",
                        "text": it.get("text") or "",
                        "url": url,
                        "views": views,
                        "date": it.get("date") or it.get("published_at") or "",
                        "seed": raw_seed,
                    })

            meta["per_seed"][raw_seed] = {"total": total_here, "matched": matched_here}

    return results, meta
