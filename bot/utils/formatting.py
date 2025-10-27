from html import escape
from datetime import datetime


def esc(s: str) -> str:
    return escape(s or "")


def fmt_result_card(it: dict) -> str:
    """
    it: {
      'title','text','url','views','date'
    }
    """
    title = it.get("title") or it.get("text") or ""
    url = it.get("url") or ""
    views = it.get("views") or 0
    dt = it.get("date") or ""
    if isinstance(dt, str) and len(dt) >= 10:
        dt = dt[:10]

    # одно сообщение-карточка
    chunks = []
    if title:
        chunks.append(f"<b>TELEGRAM · Channel</b>\n{esc(title)}")
    if url:
        chunks.append(f'<a href="{esc(url)}">{esc(url)}</a>')
    meta = []
    if dt:
        meta.append(dt)
    if views:
        meta.append(f"👁 {views}")
    if meta:
        chunks.append(" · ".join(meta))
    return "\n".join(chunks)


def fmt_summary(total: int, matched: int, since: str, until: str, phrases: list[str]) -> str:
    lines = [
        "<b>Итоги поиска</b>",
        f"📅 Диапазон: <b>{esc(since)}</b> — <b>{esc(until)}</b>",
        f"Фраз: {len(phrases)}",
        f"Всего канд.: {total} · Совпало: <b>{matched}</b>",
    ]
    return "\n".join(lines)
