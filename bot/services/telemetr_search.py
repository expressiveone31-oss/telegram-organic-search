# bot/handlers/telemetr_search.py
# -*- coding: utf-8 -*-

from __future__ import annotations

import re
from typing import List, Tuple

from aiogram import Router, F
from aiogram.types import Message
from aiogram.enums import ParseMode

from bot.services.telemetr_search import search_telemetr
from bot.utils.formatting import fmt_result_card, fmt_summary, esc

router = Router()

# Простенькое «состояние» на пользователя (без FSM)
_USER_RANGE: dict[int, Tuple[str, str]] = {}  # user_id -> (since, until)


# ---------------------------
# Утилиты
# ---------------------------

_DATE_RE = re.compile(
    r"""
    ^\s*
      (?P<d1>\d{4}[-.]\d{2}[-.]\d{2})
      \s*[–—-]\s*                 # любые тире: -, –, —
      (?P<d2>\d{4}[-.]\d{2}[-.]\d{2})
    \s*$
    """,
    re.VERBOSE,
)

def _normalize_date(d: str) -> str:
    # 2025.10.24 -> 2025-10-24
    return d.replace(".", "-").strip()

def parse_range(text: str) -> Tuple[str, str] | None:
    """
    Принимает строки вида:
      2025-10-22 — 2025-10-25
      2025-10-22 - 2025-10-25
      2025.10.22 — 2025.10.25
    Возвращает (since, until) или None.
    """
    m = _DATE_RE.match(text or "")
    if not m:
        return None
    d1 = _normalize_date(m.group("d1"))
    d2 = _normalize_date(m.group("d2"))
    return d1, d2


# ---------------------------
# Хэндлеры
# ---------------------------

@router.message(F.text == "/start")
async def start(m: Message):
    _USER_RANGE.pop(m.from_user.id, None)
    await m.answer(
        "Привет! Я бот поиска по <b>Телеграм</b>.\n"
        "Отправь диапазон дат в формате <code>YYYY-MM-DD  —  YYYY-MM-DD</code>.",
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )

@router.message()
async def any_message(m: Message):
    uid = m.from_user.id
    text = (m.text or "").strip()

    # 1) Если диапазон дат ещё не задан — ждём именно его
    if uid not in _USER_RANGE:
        rng = parse_range(text)
        if not rng:
            await m.answer(
                "Не смог разобрать даты. Пример: <code>2025-10-22  —  2025-10-25</code>",
                parse_mode=ParseMode.HTML,
            )
            return
        _USER_RANGE[uid] = rng
        await m.answer(
            f"Диапазон принят: <b>{esc(rng[0])} — {esc(rng[1])}</b>.\n"
            "Теперь пришли подводки или поисковые фразы (по одной на строке).\n"
            "Когда закончишь — просто отправь сообщение.",
            parse_mode=ParseMode.HTML,
        )
        return

    # 2) Диапазон задан — значит это фразы
    since, until = _USER_RANGE[uid]
    seeds_raw = [s.strip() for s in text.splitlines() if s.strip()]
    if not seeds_raw:
        await m.answer("Нужна хотя бы одна фраза (каждая — на новой строке).")
        return

    # Стартовый статус
    await m.answer(
        "Запускаю поиск... Это может занять до 1–2 минут при большом количестве источников.\n"
        f"Диапазон: <b>{esc(since)}</b> — <b>{esc(until)}</b>\n"
        f"Фраз: <b>{len(seeds_raw)}</b>",
        parse_mode=ParseMode.HTML,
    )

    # Поиск
    items, diag = await search_telemetr(seeds_raw, since, until)

    # Сводная карточка
    await m.answer(
        fmt_summary(since, until, seeds=seeds_raw, total=len(items)),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )

    if not items:
        await m.answer("❗️По заданным параметрам ничего не найдено.", parse_mode=ParseMode.HTML)
        # Диагностику всё равно покажем, это полезно
        await m.answer(f"<b>Диагностика:</b>\n<code>{esc(diag)}</code>", parse_mode=ParseMode.HTML)
        return

    # Показать топ-10 результатов
    shown = 0
    for d in items[:10]:
        await m.answer(fmt_result_card(d), parse_mode=ParseMode.HTML, disable_web_page_preview=False)
        shown += 1

    # Диагностика в конце
    await m.answer(
        f"<b>Диагностика:</b>\n<code>{esc(diag)}</code>",
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )
