from aiogram import Router, types, F
from aiogram.filters import CommandStart
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

import re

commands_router = Router(name="commands")

# --- Определяем состояния ---
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


# --- Получаем диапазон дат ---
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
        f"Диапазон принят: <b>{start_date}</b> — <b>{end_date}</b>.\n"
        "Теперь пришли подводки или поисковые фразы (по одной на строке). "
        "Когда закончишь — просто отправь сообщение."
    )
    await state.set_state(SearchStates.waiting_for_phrases)


# --- Получаем поисковые фразы ---
@commands_router.message(SearchStates.waiting_for_phrases)
async def handle_phrases(m: types.Message, state: FSMContext):
    text = m.text.strip()
    phrases = [line.strip() for line in text.split("\n") if line.strip()]
    if not phrases:
        await m.answer("Не вижу ни одной фразы. Напиши хотя бы одну строку.")
        return

    data = await state.get_data()
    start_date = data.get("start_date")
    end_date = data.get("end_date")

    await m.answer(
        f"Запускаю поиск…\n"
        f"📅 Диапазон: <b>{start_date}</b> — <b>{end_date}</b>\n"
        f"Фраз: {len(phrases)}"
    )
    # --- здесь позже вставим вызов Telemetr API ---
    await m.answer("✅ Поиск завершён (заглушка). Результаты появятся здесь.")
    await state.clear()
