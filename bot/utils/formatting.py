
# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Dict, Any, List

def esc(s: str) -> str:
    if not s:
        return ''
    return (
        s.replace('&', '&amp;')
         .replace('<', '&lt;')
         .replace('>', '&gt;')
    )

def _cut(s: str, n: int) -> str:
    if not s:
        return ''
    if len(s) <= n:
        return s
    return s[: max(0, n-1)] + '…'

def _take_text(it: Dict[str, Any]) -> str:
    for k in ('title', 'text', 'caption'):
        v = it.get(k) or ''
        if v.strip():
            return v
    return ''

def fmt_summary(since: str, until: str, seeds: List[str], total: int) -> str:
    return (
        "Итоги поиска\n"
        f"Диапазон: <b>{esc(since)} — {esc(until)}</b>\n"
        f"Фраз: {len(seeds)}\n"
        f"Всего кандидатов: {total}"
    )

def fmt_result_card(it: Dict[str, Any]) -> str:
    link = it.get('_link') or it.get('display_url') or it.get('url') or it.get('link') or ''
    views = it.get('views') or it.get('views_count') or 0
    seed = it.get('_seed') or ''
    text = _cut(_take_text(it), 400)
    title = it.get('channel', {}).get('title') or 'TELEGRAM • Channel'
    return (
        f"<b>{esc(title)}</b>\n"
        f"{esc(text)}\n\n"
        (f"<a href='{esc(link)}'>Открыть пост</a> • 👀 {views} • seed: <code>{esc(seed)}</code>" if link else f"👀 {views} • seed: <code>{esc(seed)}</code>")
    )
