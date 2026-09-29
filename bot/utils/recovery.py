"""
Сообщение с кнопками как источник состояния.

FSM живёт в памяти процесса, а Railway перезапускает воркер на каждый деплой.
После рестарта состояние пустое и кнопки под старым сообщением перестают
работать — хотя всё нужное для поиска написано прямо в тексте сообщения.
Поэтому список фраз и печатается, и читается обратно одним модулем.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

BULLET = "•"

_SEED_LINE_RE = re.compile(rf"^{re.escape(BULLET)}\s*(.+)$", re.M)
_RANGE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})\s*—\s*(\d{4}-\d{2}-\d{2})")


def fmt_seeds_preview(seeds: list[str]) -> str:
    return "\n".join(f"{BULLET} {s}" for s in seeds)


def _to_ts(day: str) -> int:
    return int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())


def recover_from_message(text: str) -> tuple[list[str], int, int]:
    """Возвращает (фразы, since_ts, until_ts), разобранные из текста сообщения."""
    seeds = [m.group(1).strip() for m in _SEED_LINE_RE.finditer(text or "")]
    seeds = [s for s in seeds if s]

    m = _RANGE_RE.search(text or "")
    if not m:
        return seeds, 0, 0
    try:
        return seeds, _to_ts(m.group(1)), _to_ts(m.group(2))
    except ValueError:
        return seeds, 0, 0
