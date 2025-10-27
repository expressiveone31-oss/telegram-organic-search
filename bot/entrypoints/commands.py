
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from datetime import datetime
from bot.keyboards_common import cancel_kb
from bot.services.telemetr_search import search_telemetr, parse_range

router = Router(name="commands")

class OrganicFlow(StatesGroup):
    waiting_range = State()
    waiting_seeds = State()

@router.message(F.text == "/start")
async def start(m: Message):
    await m.answer("Привет! Я ищу органику *в Telegram* по фразам. Нажми /organic.", parse_mode="MarkdownV2")

@router.message(F.text == "/help")
async def help_cmd(m: Message):
    await m.answer("Команды: /organic — запустить поиск. Будет запрошен диапазон дат и фразы.", parse_mode="MarkdownV2")

@router.message(F.text == "/organic")
async def organic(m: Message, state: FSMContext):
    await state.set_state(OrganicFlow.waiting_range)
    await m.answer(
        "Напиши диапазон дат для поиска.\n"
        "Форматы: YYYY-MM-DD — YYYY-MM-DD или DD.MM.YYYY - DD.MM.YYYY\n"
        "Например: 2025-10-19 — 2025-10-26",
        parse_mode="MarkdownV2",
        reply_markup=cancel_kb()
    )

@router.callback_query(F.data == "cancel")
async def cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("Отменено. Нажми /organic чтобы начать снова.")
    await cb.answer()

@router.message(OrganicFlow.waiting_range)
async def got_range(m: Message, state: FSMContext):
    try:
        since, until = parse_range(m.text)
    except Exception as e:
        await m.answer("Не понял даты. Пример: 2025-10-19 — 2025-10-26")
        return
    await state.update_data(since=since.isoformat(), until=until.isoformat())
    await state.set_state(OrganicFlow.waiting_seeds)
    await m.answer("Теперь пришли *подводки/поисковые фразы* — по одной на строку.\n"
                   "Когда закончишь — просто отправь сообщение.", parse_mode="MarkdownV2", reply_markup=cancel_kb())

@router.message(OrganicFlow.waiting_seeds)
async def got_seeds(m: Message, state: FSMContext):
    seeds = [s.strip() for s in (m.text or "").splitlines() if s.strip()]
    if not seeds:
        await m.answer("Нужна хотя бы одна фраза.")
        return
    data = await state.get_data()
    await state.clear()
    since = data["since"]; until = data["until"]
    await m.answer(f"Запускаю поиск... Это может занять до 1–2 минут при большом количестве источников.\n"
                   f"Диапазон: {since[:10]} — {until[:10]}\nФраз: {len(seeds)}")
    result = await search_telemetr(seeds=seeds, since=since, until=until)
    await m.answer(result.text, parse_mode="MarkdownV2", disable_web_page_preview=True)
    if result.debug:
        await m.answer(result.debug[:4000])
