
from __future__ import annotations
import os, re, math, asyncio
from dataclasses import dataclass
from typing import List, Dict, Tuple
from datetime import datetime, timezone
from dateutil import parser as dtparser
import httpx
from bot.utils.formatting import render_results, escape_md

TELEMETR_BASE = "https://api.telemetr.me"
PAGE_LIMIT = 50

def _env_bool(key: str, default: bool=False) -> bool:
    v = os.getenv(key)
    if v is None: return default
    return str(v).strip().lower() in ("1","true","yes","y","on")

def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, default))
    except Exception:
        return default

def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, default))
    except Exception:
        return default

@dataclass
class SearchResult:
    text: str
    debug: str = ""

def parse_range(s: str) -> Tuple[datetime, datetime]:
    s = s.strip().replace("—","-").replace("–","-")
    if "-" in s:
        parts = [p.strip() for p in s.split("-") if p.strip()]
        if len(parts) >= 2:
            a = dtparser.parse(parts[0], dayfirst=True)
            b = dtparser.parse(parts[1], dayfirst=True)
            if a > b: a, b = b, a
            a = a.replace(tzinfo=timezone.utc)
            b = b.replace(tzinfo=timezone.utc)
            return a, b
    # fallback: single date -> today
    a = dtparser.parse(s, dayfirst=True).replace(tzinfo=timezone.utc)
    b = datetime.now(tz=timezone.utc)
    return a, b

def contains_phrase(seed: str, text: str) -> bool:
    return seed in text

def contains_phrase_with_gap(seed: str, text: str, max_gap_words: int=0) -> bool:
    if max_gap_words <= 0:
        return seed in text
    parts = seed.split()
    if len(parts) <= 1:
        return seed in text
    # build regex allowing up to N words between parts
    esc = [re.escape(p) for p in parts]
    gap = r"(?:\W+\w+){0,%d}\W+" % max_gap_words
    pattern = r"\b" + gap.join(esc) + r"\b"
    return re.search(pattern, text, flags=re.IGNORECASE) is not None

def match_score(seed: str, text: str) -> float:
    # simple token overlap
    s = set(seed.lower().split())
    t = set(re.findall(r"[\w-]+", text.lower()))
    if not s or not t: return 0.0
    inter = len(s & t)
    return inter / len(s)

async def _telemetr_query(client: httpx.AsyncClient, token: str, query: str, limit: int, offset: int) -> Dict:
    r = await client.get(f"{TELEMETR_BASE}/channels/posts/search",
                         headers={"Authorization": f"Bearer {token}"},
                         params={"query": query, "limit": limit, "offset": offset}, timeout=30)
    r.raise_for_status()
    return r.json()

def _norm_date(val) -> datetime | None:
    if not val: return None
    try:
        return dtparser.parse(str(val)).replace(tzinfo=timezone.utc)
    except Exception:
        return None

async def search_telemetr(seeds: List[str], since: str, until: str) -> SearchResult:
    token = os.getenv("TELEMETR_TOKEN","").strip()
    if not token:
        return SearchResult(text="⚠️ Не задан TELEMETR_TOKEN.")

    max_pages = _env_int("TELEMETR_PAGES", 3)
    use_quotes = _env_bool("TELEMETR_USE_QUOTES", True)
    strict = _env_bool("TELEMETR_REQUIRE_EXACT", True)
    max_gap = _env_int("TELEMETR_MAX_GAP_WORDS", 0)
    fuzzy_thr = _env_float("TELEMETR_FUZZY_THRESHOLD", 0.72)
    debug_on = _env_bool("ORGANIC_DEBUG", False)

    since_dt = dtparser.parse(since); until_dt = dtparser.parse(until)

    collected: Dict[str, Dict] = {}
    debug_lines: List[str] = []

    async with httpx.AsyncClient() as client:
        for seed in seeds:
            q = f'"{seed}"' if use_quotes else seed
            matched_count = 0
            for page in range(max_pages):
                try:
                    js = await _telemetr_query(client, token, q, PAGE_LIMIT, page*PAGE_LIMIT)
                except httpx.HTTPStatusError as e:
                    debug_lines.append(f"Telemetr HTTP {e.response.status_code} for seed '{seed}'")
                    break
                except Exception as e:
                    debug_lines.append(f"Telemetr error for seed '{seed}': {e}")
                    break

                items = (js.get("response") or {}).get("items") or []
                total = (js.get("response") or {}).get("total_count", "?")
                if debug_on:
                    debug_lines.append(f"Telemetr page {page+1}/{max_pages} for '{seed}': got {len(items)} of ~{total}")

                if not items:
                    break

                for it in items:
                    body = (it.get("text") or "") or (it.get("title") or "")
                    body_lc = body.lower()
                    dt = _norm_date(it.get("date"))
                    if dt and (dt < since_dt or dt > until_dt):
                        continue

                    ok = False
                    reason = ""
                    if strict:
                        if contains_phrase(seed.lower(), body_lc) or contains_phrase_with_gap(seed.lower(), body_lc, max_gap):
                            ok = True; reason = "strict"
                    else:
                        if contains_phrase(seed.lower(), body_lc) or match_score(seed, body) >= fuzzy_thr:
                            ok = True; reason = "fuzzy"

                    if not ok:
                        continue

                    # Build post url (fallbacks)
                    post_url = it.get("url") or it.get("link") or ""
                    if not post_url:
                        ch = it.get("channel") or {}
                        chan = ch.get("username") or ch.get("link") or ""
                        mid = it.get("id")
                        if chan and mid:
                            post_url = f"https://t.me/{chan}/{mid}"

                    key = post_url or (body[:120])
                    if key in collected:
                        continue

                    collected[key] = {
                        "channel": it.get("channel") or {},
                        "url": post_url,
                        "views": it.get("views") or it.get("reactions_count") or "",
                        "date": it.get("date") or "",
                        "reason": reason,
                        "text": body
                    }
                    matched_count += 1

            if debug_on:
                debug_lines.append(f"Matched for seed '{seed}': {matched_count}")

    items = list(collected.values())
    text = (f"*Итоги поиска*\nПубликаций: {len(items)}\n"
            f"Диапазон: {escape_md(since[:10])} — {escape_md(until[:10])}\n"
            f"{render_results(items)}")
    debug = "\n".join(debug_lines) if debug_on else ""
    return SearchResult(text=text, debug=debug)
