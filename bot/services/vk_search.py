"""
Поиск органики во ВКонтакте через newsfeed.search.
"""
from __future__ import annotations

import logging
import os
import re
import unicodedata
from typing import Any, Dict, List, Tuple

import httpx

logger = logging.getLogger(__name__)

VK_API = "https://api.vk.com/method"


def _cfg() -> Dict[str, Any]:
    return {
        "token":     os.getenv("VK_TOKEN", "").strip(),
        "max_pages": int(os.getenv("VK_MAX_PAGES", "5") or 5),
        "min_views": int(os.getenv("VK_MIN_VIEWS", "500") or 500),
        "strict":    os.getenv("VK_STRICT", "1") == "1",
    }


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", (s or "").lower())
    s = s.replace("ё", "е")
    return re.sub(r"\s+", " ", s).strip()


def _contains(needle: str, hay: str) -> bool:
    return _norm(needle) in _norm(hay)


async def _call(
    client: httpx.AsyncClient,
    token: str,
    method: str,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    r = await client.get(
        f"{VK_API}/{method}",
        params={"v": "5.199", "access_token": token, **params},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise RuntimeError(f"VK API error {data['error'].get('error_code')}: {data['error'].get('error_msg')}")
    return data["response"]


async def search_vk(
    seeds: List[str],
    since_ts: int,
    until_ts: int,
) -> Tuple[List[Dict[str, Any]], str]:
    cfg = _cfg()
    if not cfg["token"]:
        raise RuntimeError("VK_TOKEN is not set")

    results: List[Dict[str, Any]] = []
    diag_parts = []

    async with httpx.AsyncClient() as client:
        for seed in seeds:
            fetched = 0
            matched = 0
            next_from = None

            for _page in range(cfg["max_pages"]):
                params: Dict[str, Any] = {
                    "q": seed,
                    "count": 50,
                    "start_time": since_ts,
                    "end_time": until_ts,
                }
                if next_from:
                    params["start_from"] = next_from

                try:
                    resp = await _call(client, cfg["token"], "newsfeed.search", params)
                except Exception as e:
                    logger.error("VK search error seed=%r: %s", seed, e)
                    break

                items = resp.get("items", [])
                next_from = resp.get("next_from")
                fetched += len(items)

                for it in items:
                    views = (it.get("views") or {}).get("count", 0)
                    if views < cfg["min_views"]:
                        continue
                    text = it.get("text") or ""
                    if not text:
                        continue
                    if cfg["strict"] and not _contains(seed, text):
                        continue
                    matched += 1
                    owner_id = it.get("owner_id")
                    post_id = it.get("id")
                    results.append({
                        "date":    it.get("date", 0),
                        "views":   views,
                        "url":     f"https://vk.com/wall{owner_id}_{post_id}",
                        "excerpt": text[:200] + ("…" if len(text) > 200 else ""),
                        "_seed":   seed,
                    })

                if not next_from or not items:
                    break

            logger.info("VK seed=%r fetched=%d matched=%d", seed, fetched, matched)
            diag_parts.append(f"'{seed}': {matched}/{fetched}")

    results.sort(key=lambda r: r["date"], reverse=True)
    return results, "VK: " + "; ".join(diag_parts)
