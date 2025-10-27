from datetime import datetime
from typing import List, Dict

def fmt_date(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")

def bold(s: str) -> str:
    return f"*{escape_md(s)}*"

def code(s: str) -> str:
    return f"`{escape_md(s)}`"

def escape_md(text: str) -> str:
    specials = "_*[]()~`>#+-=|{}.!"  # Telegram MarkdownV2
    return "".join("\\" + c if c in specials else c for c in text)

def render_results(items: List[Dict]) -> str:
    if not items:
        return "Ничего не найдено."
    lines = ["*Найденные публикации:*"]
    for it in items[:20]:
        c
