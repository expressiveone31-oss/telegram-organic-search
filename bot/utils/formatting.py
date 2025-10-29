
from __future__ import annotations
from typing import Dict, Any
def esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
def fmt_summary(since: str, until: str, total: int, views: int) -> str:
    return (f"<b>Итоги поиска</b>\n"
            f"\n📅 Диапазон: <b>{since} — {until}</b>"
            f"\nПостов: <b>{total}</b>"
            f"\nСуммарные просмотры: <b>{views}</b>")
def fmt_result_card(it: Dict[str, Any]) -> str:
    ch = it.get("channel") or {}
    ch_title = ch.get("title") or ch.get("name") or "TELEGRAM · Channel"
    dt = it.get("date") or it.get("published_at") or ""
    v = it.get("views") or it.get("views_count") or 0
    url = it.get("_link") or it.get("display_url") or it.get("url") or ""
    title = it.get("title") or ""
    text = it.get("text") or it.get("caption") or ""
    body = title if title and (title in text) else f"{title}\n{text}" if title else text
    return (f"<b>{esc(ch_title)}</b>\n"
            f"{esc(str(dt))} | 👀 {v}\n"
            f"{esc(body[:400])}\n"
            f"<a href='{esc(url)}'>{esc(url)}</a>")
