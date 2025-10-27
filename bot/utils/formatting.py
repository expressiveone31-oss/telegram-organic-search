# bot/utils/formatting.py
# -*- coding: utf-8 -*-

from __future__ import annotations
from typing import Any, Dict, Iterable, List

def escape_md(s: str) -> str:
    if not s:
        return ""
    # Нейтральный эскейп под MarkdownV2
    for ch in r"\_*[]()~`>#+-=|{}.!":
        s = s.replace(ch, f"\\{ch}")
    return s

def _as_dict(it: Any) -> Dict[str, Any]:
    """Нормализация айтема Telemetr: dict/str -> dict{text:...}"""
    if isinstance(it, dict):
        return it
    if isinstance(it, str):
        return {"text": it}
    return {}

def _body(d: Dict[str, Any]) -> str:
    parts: List[str] = []
    for k in ("title", "text", "caption"):
        v = (d.get(k) or "").strip()
        if v:
            parts.append(v)
    return "\n".join(parts).strip()

def _views_of(d: Dict[str, Any]) -> int:
    v = d.get("views") or d.get("views_count") or 0
    try:
        return int(v)
    except Exception:
        return 0

def _link_of(d: Dict[str, Any]) -> str:
    return (
        d.get("display_url")
        or d.get("url")
        or d.get("link")
        or d.get("_link")
        or ""
    )

def dedup_items(items: Iterable[Any]) -> List[Dict[str, Any]]:
    seen = set()
    out: List[Dict[str, Any]] = []
    for it in items:
        d = _as_dict(it)
        if not d:
            continue
        key = _link_of(d) or (_body(d)[:120] if _body(d) else str(d))
        if key in seen:
            continue
        seen.add(key)
        out.append(d)
    return out

def fmt_summary(*, since: str, until: str, phrases_count: int, total_candidates: int, matched: int) -> str:
    return (
        "Итоги поиска:\n"
        f"📅 Диапазон: {escape_md(since)} — {escape_md(until)}\n"
        f"Фраз: {phrases_count}\n"
        f"Всего канд.: {total_candidates} · Совпало: {matched}"
    )

def fmt_result_card(d: Dict[str, Any]) -> str:
    link = _link_of(d)
    views = _views_of(d)
    body = _body(d)
    headline = escape_md((d.get("channel") or {}).get("title") or d.get("title") or "TELEGRAM · Channel")
    line_link = f"\n{escape_md(link)}" if link else ""
    body_excerpt = escape_md(body[:600]) if body else "—"
    tail = f"\n👁 {views}" if views else ""
    return f"{headline}\n{body_excerpt}{line_link}{tail}"

def render_results(items: Iterable[Any]) -> List[str]:
    # Полная защита от «кривых» айтемов
    cards: List[str] = []
    for d in dedup_items(items):
        cards.append(fmt_result_card(d))
    return cards
