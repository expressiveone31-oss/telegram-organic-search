"""
Кнопки платформ должны работать и после рестарта воркера: FSM живёт в памяти,
Railway перезапускает процесс на каждый деплой, а всё нужное для поиска
написано прямо в сообщении с кнопками.
"""
from datetime import datetime, timezone

from bot.utils.recovery import fmt_seeds_preview, recover_from_message

SEEDS = [
    "Таинственная пирамида выросла посреди Москва Сити",
    "Загадочная пирамида в Москва Сити стала героиней мемов",
    "В такую «эчпочмачную» мы бы сходили",
]

MESSAGE = (
    "Посты: 0 · Диапазон: 2026-09-15 — 2026-09-29\n"
    "\n"
    f"Фразы для поиска ({len(SEEDS)}):\n"
    f"{fmt_seeds_preview(SEEDS)}\n"
    "\n"
    "Где искать?"
)


def test_seeds_survive_round_trip_through_the_message():
    seeds, _, _ = recover_from_message(MESSAGE)
    assert seeds == SEEDS


def test_range_recovered_from_message():
    _, since_ts, until_ts = recover_from_message(MESSAGE)
    fmt = "%Y-%m-%d"
    assert datetime.fromtimestamp(since_ts, tz=timezone.utc).strftime(fmt) == "2026-09-15"
    assert datetime.fromtimestamp(until_ts, tz=timezone.utc).strftime(fmt) == "2026-09-29"


def test_message_without_seeds_yields_nothing():
    seeds, since_ts, until_ts = recover_from_message("Готово! Можно поискать ещё.")
    assert seeds == []
    assert (since_ts, until_ts) == (0, 0)
