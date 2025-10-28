# bot/utils/formatting.py
# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import Any, Dict, List

def esc(s: str) -> str:
    """Простейший HTML-escape (мы используем ParseMode.HTML)."""
    if not isinstance(s, str):
        s = str(s)
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
    )

def _safe_str(v: Any) -> str:
    return str(v) if v is not None else ""

def _as_dict(it: Any) -> Dict[str, Any]:
    if isinstance(it, dict):
        return it
    if isinstance(it, str):
        return {"text": it}
    return {}

def _views(d: Dict[str, Any]) -> int:
    v = d.get("views")
    if v is None:
        v = d.get("views_count")
    try:
        return int(v or 0)
    except Exception:
        return 0

def _link(d: Dict[str, Any]) -> str:
    for k in ("display_url", "url", "link"):
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""

def _body(d: Dict[str, Any]) -> str:
    parts: List[str] = []
    for k in ("title", "text", "caption"):
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            parts.append(v.strip())
    return "\n".join(parts).strip() or "(без текста)"

def fmt_summary(since: str, until: str, *, seeds: List[str], total: int) -> str:
    return (
        "Итоги поиска\n"
        f"📅 Диапазон: <b>{esc(since)}</b> — <b>{esc(until)}</b>\n"
        f"🔎 Фраз: <b>{len(seeds)}</b>\n"
        f"📄 Всего кандидатов: <b>{total}</b>"
    )

def fmt_result_card(item: Any) -> str:
    d = _as_dict(item)
    vx = _views(d)
    link = _link(d)
    seed = d.get("_seed") or ""
    body = _body(d)

    header = []
    if seed:
        header.append(f"🧩 По фразе: <b>{esc(seed)}</b>")
    if vx:
        header.append(f"👀 Просмотры: <b>{vx}</b>")
    if link:
        header.append(f"🔗 <a href=\"{esc(link)}\">Открыть пост</a>")

    head = " · ".join(header) if header else "Пост"

    return f"{head}\n\n{esc(body)}"
