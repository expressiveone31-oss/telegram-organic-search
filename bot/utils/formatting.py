from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict


def esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def fmt_summary(since_ts: int, until_ts: int, total: int, views: int) -> str:
    since = datetime.fromtimestamp(since_ts, tz=timezone.utc).strftime("%Y-%m-%d")
    until = datetime.fromtimestamp(until_ts, tz=timezone.utc).strftime("%Y-%m-%d")
    return (
        f"<b>Итоги поиска — Telegram</b>\n"
        f"📅 {since} — {until}\n"
        f"Постов: <b>{total}</b>\n"
        f"Суммарные просмотры: <b>{views:,}</b>"
    )


def fmt_result_card(it: Dict[str, Any]) -> str:
    ch = it.get("channel") or {}
    ch_title = ch.get("title") or ch.get("name") or "Telegram"
    dt = it.get("date") or it.get("published_at") or ""
    v = it.get("views") or it.get("views_count") or 0
    url = it.get("_link") or it.get("display_url") or it.get("url") or ""
    title = it.get("title") or ""
    text = it.get("text") or it.get("caption") or ""
    body = title if title and title in text else f"{title}\n{text}" if title else text
    return (
        f"<b>{esc(ch_title)}</b>\n"
        f"{esc(str(dt))} | 👀 {v}\n"
        f"{esc(body[:400])}\n"
        f"<a href='{esc(url)}'>{esc(url)}</a>"
    )
