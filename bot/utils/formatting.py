# bot/utils/formatting.py
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Sequence, Tuple, Union

# -------- Markdown-v2 escaping -------------------------------------------------


_MD_V2_NEED_ESCAPE = r"_*[]()~`>#+-=|{}.!"


def escape_md(text: Union[str, None]) -> str:
    """
    Безопасное экранирование для Telegram MarkdownV2.
    Ничего не делает, если text == None.
    """
    if not text:
        return ""
    out = []
    for ch in str(text):
        if ch in _MD_V2_NEED_ESCAPE or ch == "\\":
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


# -------- Утилиты представления чисел ------------------------------------------


def human_int(n: Union[int, float, None]) -> str:
    if n is None:
        return "0"
    try:
        n = int(n)
    except Exception:
        return str(n)
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M".rstrip("0").rstrip(".")
    if n >= 1_000:
        return f"{n/1_000:.1f}K".rstrip("0").rstrip(".")
    return str(n)


# -------- Нормализация элементов выдачи ----------------------------------------


Item = Dict[str, Any]
Items = List[Item]


def ensure_safe_items(items: Iterable[Any]) -> Items:
    """
    Приводим коллекцию к списку словарей.
    - dict -> dict (как есть)
    - str  -> {"text": "..."}        (важно для «странных» ответов Telemetr)
    - прочее -> пропускаем
    """
    safe: Items = []
    for x in items or []:
        if isinstance(x, dict):
            safe.append(x)
        elif isinstance(x, str):
            safe.append({"text": x})
        else:
            # игнорируем неизвестные типы, чтобы не ронять пайплайн
            continue
    return safe


# -------- Телеграм-текст из элемента Telemetr ----------------------------------


def _telemetr_body(it: Union[str, Item]) -> str:
    """
    Безопасно собираем «тело» поста из элемента Telemetr.
    Поддерживает как dict, так и str.
    При dict пытаемся взять title, text, caption.
    """
    if isinstance(it, str):
        return it.strip()

    if not isinstance(it, dict):
        return ""

    parts: List[str] = []
    for key in ("title", "text", "caption"):
        v = it.get(key)
        if v:
            v = str(v).strip()
            if v:
                parts.append(v)

    return "\n".join(parts)


def _telemetr_link(it: Item) -> str:
    """
    Пытаемся вытащить ссылку на пост из разных полей.
    """
    for key in ("url", "link", "display_url"):
        v = it.get(key)
        if v:
            return str(v)
    # Иногда Telemetr кладёт в media/display_url
    media = it.get("media")
    if isinstance(media, dict):
        v = media.get("display_url")
        if v:
            return str(v)
    return ""


def _telemetr_channel_name(it: Item) -> str:
    ch = it.get("channel") or {}
    if isinstance(ch, dict):
        name = ch.get("name") or ch.get("title") or ch.get("username")
        if name:
            return str(name)
    return ""


# -------- Универсальный рендер результатов ------------------------------------


def _smart_pick_args(*args, **kwargs) -> Tuple[str, Items, int, str]:
    """
    Поддерживаем несколько «популярных» сигнатур вызова render_results:

    1) render_results(items, title=None, max_items=10, footer=None)
    2) render_results(title, items, max_items=10, footer=None)
    3) render_results(items=..., title=..., max_items=..., footer=...)

    Возвращаем кортеж: (title, items, max_items, footer)
    """
    title = kwargs.get("title") or ""
    max_items = int(kwargs.get("max_items") or 10)
    footer = kwargs.get("footer") or ""

    if "items" in kwargs:
        items = ensure_safe_items(kwargs["items"])
        return str(title), items, max_items, str(footer)

    # позиционные варианты
    if len(args) == 1 and isinstance(args[0], list):
        return str(title), ensure_safe_items(args[0]), max_items, str(footer)

    if len(args) >= 2:
        # (title, items, ...)
        if isinstance(args[0], str) and isinstance(args[1], list):
            title = args[0]
            items = args[1]
            if len(args) >= 3 and isinstance(args[2], int):
                max_items = int(args[2])
            if len(args) >= 4 and isinstance(args[3], str):
                footer = args[3]
            return str(title), ensure_safe_items(items), max_items, str(footer)

        # (items, title, ...)
        if isinstance(args[0], list) and isinstance(args[1], str):
            items = args[0]
            title = args[1]
            if len(args) >= 3 and isinstance(args[2], int):
                max_items = int(args[2])
            if len(args) >= 4 and isinstance(args[3], str):
                footer = args[3]
            return str(title), ensure_safe_items(items), max_items, str(footer)

    # fallback — ничего не распознали
    items = ensure_safe_items([])
    return str(title), items, max_items, str(footer)


def render_results(*args, **kwargs) -> str:
    """
    Формирует один Markdown-v2 блок с превью результатов.
    Терпима к «кривым» элементам и к неожиданным сигнатурам вызова.
    Возвращает Готовый Текст.
    """
    title, items, max_items, footer = _smart_pick_args(*args, **kwargs)

    head = f"*{escape_md(title)}*\n" if title else ""
    if not items:
        return head + "_Ничего не найдено._"

    lines: List[str] = [head] if head else []
    shown = 0

    for it in items:
        if shown >= max_items:
            break
        body = _telemetr_body(it)
        if not body:
            # даже если «тела» нет — попробуем показать ссылку/канал
            body = _telemetr_channel_name(it) or "Публикация"

        # короткое превью
        preview = " ".join(body.split())
        if len(preview) > 180:
            preview = preview[:177] + "..."

        url = _telemetr_link(it)
        channel = _telemetr_channel_name(it)

        left = f"• {escape_md(preview)}"
        right = f" — _{escape_md(channel)}_" if channel else ""
        if url:
            # Кликабельный заголовок
            line = f"• [{escape_md(preview)}]({escape_md(url)}){right}"
        else:
            line = left + right

        lines.append(line)
        shown += 1

    if footer:
        lines.append("")
        lines.append(escape_md(footer))

    return "\n".join(lines) or "_Ничего не найдено._"
