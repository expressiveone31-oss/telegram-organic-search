# bot/services/telemetr_search.py
import os
import aiohttp
from datetime import date, datetime

API_URL = "https://api.telemeter.top/channels/posts/search"
TELEMETER_TOKEN = os.getenv("TELEMETER_TOKEN", "")

def _parse_date(s: str) -> date:
    return datetime.strptime(s.strip(), "%Y-%m-%d").date()

def parse_range(s: str) -> tuple[date, date]:
    """
    Принимает 'YYYY-MM-DD — YYYY-MM-DD' (длинное тире) или 'YYYY-MM-DD - YYYY-MM-DD'.
    """
    if "—" in s:
        left, right = s.split("—", 1)
    else:
        left, right = s.split("-", 1)
    return _parse_date(left), _parse_date(right)

async def search_telemetr(
    query: str,
    since: date,
    until: date,
    *,
    limit: int = 50,
    pages: int = 1,
):
    """
    Ищет посты в Telemetr Search API.
    Возвращает список словарей: {platform, url, title, views}.
    """
    headers = {"Authorization": f"Bearer {TELEMETER_TOKEN}"} if TELEMETER_TOKEN else {}
    params = {
        "query": query,
        "date_from": since.isoformat(),
        "date_to": until.isoformat(),
        "limit": min(max(int(limit), 1), 50),  # лимит Telemetr = 50
        "sort": "date",
    }

    out = []
    async with aiohttp.ClientSession(headers=headers) as sess:
        for _ in range(max(1, int(pages))):
            async with sess.get(API_URL, params=params) as r:
                data = await r.json(content_type=None)
                resp = data.get("response", {})
                for it in resp.get("items", []):
                    out.append(
                        {
                            "platform": "TG",
                            "url": it.get("display_url") or it.get("link") or "",
                            "title": it.get("text") or "",
                            "views": it.get("views") or 0,
                        }
                    )
                next_offset = resp.get("next_offset")
                if not next_offset:
                    break
                params["offset"] = next_offset
    return out
