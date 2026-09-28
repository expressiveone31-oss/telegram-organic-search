from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict


def esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def fmt_tg_summary(since_ts: int, until_ts: int, total: int, views: int) -> str:
    since = datetime.fromtimestamp(since_ts, tz=timezone.utc).strftime("%Y-%m-%d")
    until = datetime.fromtimestamp(until_ts, tz=timezone.utc).strftime("%Y-%m-%d")
    return (
        f"<b>Итоги поиска — Telegram</b>\n"
        f"📅 {since} — {until}\n"
        f"Постов: <b>{total}</b>\n"
        f"Суммарные просмотры: <b>{views:,}</b>"
    )


def fmt_vk_summary(since_ts: int, until_ts: int, total: int, views: int) -> str:
    since = datetime.fromtimestamp(since_ts, tz=timezone.utc).strftime("%Y-%m-%d")
    until = datetime.fromtimestamp(until_ts, tz=timezone.utc).strftime("%Y-%m-%d")
    return (
        f"<b>Итоги поиска — ВКонтакте</b>\n"
        f"📅 {since} — {until}\n"
        f"Постов: <b>{total}</b>\n"
        f"Суммарные просмотры: <b>{views:,}</b>"
    )


def _fmt_date(value: Any) -> str:
    """Telemetr отдаёт дату unix-числом либо ISO-строкой."""
    if value in (None, "", 0):
        return "?"
    if isinstance(value, (int, float)) or str(value).isdigit():
        try:
            return datetime.fromtimestamp(int(value), tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        except (ValueError, OSError, OverflowError):
            return "?"
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return str(value)


def fmt_tg_card(it: Dict[str, Any]) -> str:
    ch = it.get("_channel") or it.get("channel") or {}
    username = it.get("_username") or ""
    ch_title = ch.get("title") or ch.get("name") or (f"@{username}" if username else "Telegram")
    dt = _fmt_date(it.get("date") or it.get("published_at"))
    # _views считает search_telemetr; в выдаче поиска Telemetr их часто просто нет
    v = int(it.get("_views") or it.get("views") or it.get("views_count") or 0)
    url = it.get("_link") or it.get("display_url") or it.get("url") or ""
    title = it.get("title") or ""
    text = it.get("text") or it.get("caption") or ""
    body = title if title and title in text else f"{title}\n{text}" if title else text

    meta = esc(dt) if v <= 0 else f"{esc(dt)} | 👀 {v:,}"
    return (
        f"<b>{esc(ch_title)}</b>\n"
        f"{meta}\n"
        f"{esc(body[:400])}\n"
        f"<a href='{esc(url)}'>{esc(url)}</a>"
    )


def fmt_vk_card(it: Dict[str, Any]) -> str:
    ts = it.get("date", 0)
    dt_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M") if ts else "?"
    views = it.get("views", 0)
    url = it.get("url", "")
    excerpt = it.get("excerpt", "")
    return (
        f"VK | {dt_str} | 👀 {views}\n"
        f"{esc(excerpt)}\n"
        f"<a href='{esc(url)}'>{esc(url)}</a>"
    )
