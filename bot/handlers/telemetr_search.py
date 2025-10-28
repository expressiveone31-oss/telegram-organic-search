
# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import List
import re

from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

from bot.services.telemetr_search import search_telemetr
from bot.utils.formatting import fmt_result_card, fmt_summary, esc

router = Router(name="telemetr")

class Flow(StatesGroup):
    awaiting_range = State()
    awaiting_seeds = State()

def _prompt_start() -> str:
    return (
        "Привет! Я бот поиска по <b>Телеграм</b>\n"
        "Отправь диапазон дат в формате <code>YYYY-MM-DD — YYYY-MM-DD</code>."
    )

@router.message(F.text == "/start")
async def cmd_start(m: Message, state: FSMContext) -> None:
    await state.set_state(Flow.awaiting_range)
    await m.answer(_prompt_start())

def _parse_range(txt: str):
    s = (txt or "").replace("—", "-")
    m = re.findall(r"(\\d{4}-\\d{2}-\\d{2})", s)
    if len(m) >= 2:
        return m[0], m[1]
    return None

@router.message(Flow.awaiting_range, F.text)
async def got_range(m: Message, state: FSMContext) -> None:
    pr = _parse_range(m.text or "")
    if not pr:
        await m.answer("Не смог разобрать даты. Пример: <code>2025-10-22 — 2025-10-25</code>")
        return
    since, until = pr
    await state.update_data(since=since, until=until)
    await state.set_state(Flow.awaiting_seeds)
    await m.answer(
        f"Диапазон принят: <b>{esc(since)} — {esc(until)}</b>.\n"
        "Теперь пришли <b>подводки/фразы</b> — по одной на строке.\n"
        "Когда закончишь — просто отправь сообщение."
    )

@router.message(Flow.awaiting_seeds, F.text)
async def got_seeds(m: Message, state: FSMContext) -> None:
    data = await state.get_data()
    since = data.get("since")
    until = data.get("until")
    seeds: List[str] = [s.strip() for s in (m.text or "").splitlines() if s.strip()]
    if not seeds:
        await m.answer("Нужны фразы — по одной на строке.")
        return

    await m.answer("Запускаю поиск...")
    try:
        items, _diag = await search_telemetr(seeds=seeds, since=since, until=until)
    except Exception as e:
        await m.answer(f"⚠️ Ошибка поиска: <code>{esc(str(e))}</code>")
        return

    await m.answer(fmt_summary(since, until, seeds, len(items)), disable_web_page_preview=True)
    if not items:
        await m.answer("По заданным параметрам ничего не найдено.")
        return

    for it in items[:8]:
        await m.answer(fmt_result_card(it), disable_web_page_preview=False)
