from aiogram import Router, types
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

import asyncio
import re
from typing import List

from bot.services.telemetr_search import search_telemetr
from bot.utils.formatting import fmt_result_card, fmt_summary, escape_md

commands_router = Router(name="commands")

class SearchStates(StatesGroup):
    waiting_for_dates = State()
    waiting_for_phrases = State()


@commands_router.message(CommandStart())
async def start_cmd(m: types.Message, state: FSMContext):
    await state.clear()
    await m.answer(
        "Привет! Я бот поиска по <b>Телеграм</b>.\n"
        "Отправь диапазон дат в формате <code>YYYY-MM-DD — YYYY-MM-DD</code> "
        "или <code>YYYY-MM-DD - YYYY-MM-DD</code>."
    )
    await state.set_state(SearchStates.waiting_for_dates)


@commands_router.message(SearchStates.waiting_for_dates)
async def handle_dates(m: types.Message, state: FSMContext):
    text = m.text.strip()
    match = re.match(r"(\d{4}-\d{2}-\d{2})\s*[—-]\s*(\d{4}-\d{2}-\d{2})", text)
    if not match:
        await m.answer("Формат неверный. Используй <code>YYYY-MM-DD — YYYY-MM-DD</code>.")
        return
    start_date, end_date = match.groups()
    await state.update_data(start_date=start_date, end_date=end_date)
    await m.answer(
        f"Диапазон принят: <b>{escape_md(start_date)}</b> — <b>{escape_md(end_date)}</b>.\n"
        "Теперь пришли подводки или поисковые фразы (по одной на строке). "
        "Когда закончишь — просто отправь сообщение."
    )
    await state.set_state(SearchStates.waiting_for_phrases)


def _extract_phrases(text: str) -> List[str]:
    return [ln.strip() for ln in (text or "").splitlines() if ln.strip()]


@commands_router.message(SearchStates.waiting_for_phrases)
async def handle_phrases(m: types.Message, state: FSMContext):
    phrases = _extract_phrases(m.text)
    if not phrases:
        await m.answer("Не вижу ни одной фразы. Напиши хотя бы одну строку.")
        return

    data = await state.get_data()
    since = data.get("start_date")
    until = data.get("end_date")

    # явный статус: старт
    status = await m.answer(
        "🔎 Запускаю поиск…\n"
        f"📅 Диапазон: <b>{escape_md(since)}</b> — <b>{escape_md(until)}</b>\n"
        f"Фраз: {len(phrases)}"
    )

    try:
        # сам поиск
        found, meta = await search_telemetr(phrases, since, until)

        # отчёт: сколько нашли
        await status.edit_text(
            fmt_summary(total=meta.get("total", 0), matched=len(found), since=since, until=until, phrases=phrases)
        )

        if not found:
            await m.answer("❗️По заданным параметрам ничего не найдено.")
            await state.clear()
            return

        # отдаём карточки (аккуратно — Telegram ограничивает частоту отправки)
        for item in found[:30]:  # чтобы не заспамить — отдать до 30 карточек
            await m.answer(fmt_result_card(item))
            await asyncio.sleep(0.15)

        if len(found) > 30:
            await m.answer(f"…и ещё {len(found) - 30} результатов. Уточни фразу или сузь диапазон, чтобы увидеть всё.")
    except Exception as e:
        # любой фэйл — понятная диагностика
        await status.edit_text(f"⚠️ Ошибка поиска: <code>{escape_md(str(e))}</code>")
    finally:
        await state.clear()
