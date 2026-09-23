"""
Поиск органики во ВКонтакте через newsfeed.search.
"""
from __future__ import annotations

import os
import re
import unicodedata
from typing import Any, Dict, List, Tuple

import httpx

VK_TOKEN     = os.getenv("VK_TOKEN", "")
VK_MAX_PAGES = int(os.getenv("VK_MAX_PAGES", "5"))
VK_MIN_VIEWS = int(os.getenv("VK_MIN_VIEWS", "500"))
VK_STRICT    = os.getenv("VK_STRICT", "1") == "1"


def _norm(s: str) -> str:
    s = (s or "").lower()
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("ё", "е")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _contains_phrase(needle: str, hay: str) -> bool:
    return _norm(needle) in _norm(hay)


async def _vk_call(method: str, params: Dict[str, Any]) -> Dict[str, Any]:
    if not VK_TOKEN:
        raise RuntimeError("VK_TOKEN is not set")
    url = f"https://api.vk.com/method/{method}"
    base = {"v": "5.199", "access_token": VK_TOKEN, **params}
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(url, params=base)
        r.raise_for_status()
        data = r.json()
        if "error" in data:
            raise RuntimeError(f"VK API error: {data['error']}")
        return data["response"]


async def search_vk(
    seeds: List[str],
    since_ts: int,
    until_ts: int,
) -> Tuple[List[Dict[str, Any]], str]:
    results: List[Dict[str, Any]] = []
    diagnostics = []

    for seed in seeds:
        fetched = 0
        matched = 0
        next_from = None

        for _page in range(VK_MAX_PAGES):
            params: Dict[str, Any] = {
                "q": seed,
                "count": 50,
                "start_time": since_ts,
                "end_time": until_ts,
            }
            if next_from:
                params["start_from"] = next_from

            resp = await _vk_call("newsfeed.search", params)
            items = resp.get("items", [])
            next_from = resp.get("next_from")
            fetched += len(items)

            for it in items:
                views = (it.get("views") or {}).get("count", 0)
                if views < VK_MIN_VIEWS:
                    continue
                text = it.get("text") or ""
                if not text:
                    continue
                if VK_STRICT and not _contains_phrase(seed, text):
                    continue
                matched += 1
                owner_id = it.get("owner_id")
                post_id = it.get("id")
                results.append({
                    "owner_id": owner_id,
                    "post_id": post_id,
                    "date": it.get("date", 0),
                    "views": views,
                    "url": f"https://vk.com/wall{owner_id}_{post_id}",
                    "excerpt": text[:200] + ("…" if len(text) > 200 else ""),
                    "_seed": seed,
                })

            if not next_from or not items:
                break

        diagnostics.append(f"'{seed}': fetched={fetched} matched={matched}")

    results.sort(key=lambda r: (r["date"], r["views"]), reverse=True)
    return results, "VK: " + "; ".join(diagnostics)
