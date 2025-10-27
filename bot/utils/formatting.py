# bot/utils/formatting.py
# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Dict, List

# экранирование под MarkdownV2
MD_V2_NEEDS_ESCAPE = r"_*[]()~`>#+-=|{}.!"
def escape_md(s: str) -> str:
    if not s:
        return ""
    out: List[str] = []
    for ch in s:
        if ch in MD_V2_NEEDS_ESCAPE:
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)

def _as_dict(it: Any) -> Dict[str, Any]:
    if isinstance(it, dict):
        return it
    return {"text": str(it) if it is not None else ""}

def fmt_summary(stats: Dict[str, int]) -> str:
    total = stats.get("total", 0)
    matched = stats.get("matched", 0)
    cand = stats.get("candidates", 0)
    return (
        f"Итоги поиска\n"
        f"Всего канд.: {cand} • Совпало: {matched} • Обработано: {total}"
    )

def fmt_result_card(it: Any) -> str:
    # 🔒 Главный фикс: приводим что угодно к dict
    it = _as_dict(it)

    title = (it.get("title") or "").strip()
    text  = (it.get("text") or "").strip()
    cap   = (it.get("caption") or "").strip()
    body  = "\n".join([p for p in (title, text, cap) if p]).strip()

    link  = it.get("display_url") or it.get("url") or it.get("link") or ""
    views = it.get("views") or it.get("views_count") or ""

    body_md = escape_md(body)[:3500]
    link_md = escape_md(link)

    rows = [
        f"*TELEGRAM · Channel*",
    ]
    if views:
        rows.append(f"👁 {views}")
    if body_md:
        rows.append(body_md)
    if link_md:
        rows.append(link_md)

    return "\n".join(rows)

