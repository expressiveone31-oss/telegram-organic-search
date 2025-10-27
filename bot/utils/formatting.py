# bot/utils/formatting.py
from typing import Iterable, Mapping

# Набор спецсимволов MarkdownV2, которые нужно экранировать
MDV2_SPECIALS = r'_\*\[\]\(\)~`>#+\-=|{}\.!'

def escape_md(text: str) -> str:
    """Экранирует текст под Telegram MarkdownV2."""
    if not text:
        return ""
    specials = set(MDV2_SPECIALS)
    return "".join("\\" + c if c in specials else c for c in text)

def render_results(items: Iterable[Mapping]) -> str:
    """Формирует компактный список результатов с кликабельными ссылками."""
    lines = []
    for it in items:
        url = it.get("url") or it.get("link") or ""
        title = escape_md(it.get("title") or it.get("text") or "Пост")
        views = it.get("views") or it.get("count") or 0
        platform = it.get("platform", "TG")
        if url:
            lines.append(f"• {escape_md(platform)}: [{title}]({escape_md(url)}) — {views}")
        else:
            lines.append(f"• {escape_md(platform)}: {title} — {views}")
    return "\n".join(lines)
