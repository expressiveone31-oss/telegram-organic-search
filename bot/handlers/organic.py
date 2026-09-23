"""
Хендлер поиска органики в Telegram.

Флоу:
  /start или /organic  →  бот просит посевной материал
  Пользователь кидает в одном сообщении:
    - ссылки на посевные посты (t.me/channel/123) — дата берётся из них
    - и/или поисковые фразы — по одной на строке
  Бот:
    - парсит ссылки → текст + дата самого раннего поста = since
    - until = since + ORGANIC_WINDOW_DAYS (по умолчанию 14)
    - извлекает фразы из текстов посевов
    - ищет через Telemetr и возвращает карточки
"""
from __future__ import annotations

import logging
import os
import re
import time

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message

from bot.services.link_parser import parse_tg_link, extract_seeds_from_text
from bot.services.telemetr_search import search_telemetr
from bot.utils.formatting import esc, fmt_summary, fmt_result_card

logger = logging.getLogger(__name__)
router = Router()

ORGANIC_DEBUG       = os.getenv("ORGANIC_DEBUG", "0") == "1"
ORGANIC_WINDOW_DAYS = int(os.getenv("ORGANIC_WINDOW_DAYS", "14"))
MAX_CARDS           = int(os.getenv("ORGANIC_MAX_CARDS", "15"))

URL_RE = re.compile(r"https?://\S+")


class OrganicFlow(StatesGroup):
    waiting_input = State()


# ── команды ──────────────────────────────────────────────────────────────────

@router.message(Command("start"))
async def cmd_start(m: Message, state: FSMContext):
    await state.clear()
    await state.set_state(OrganicFlow.waiting_input)
    await m.answer(
        "Привет! Ищу органику по посевам в Telegram.\n\n"
        "Пришли ссылки на посевные посты (t.me/...) и/или поисковые фразы — "
        "всё в одном сообщении, фразы по одной на строке.\n\n"
        "Дату диапазона возьму из самого раннего поста автоматически."
    )


@router.message(Command("organic"))
async def cmd_organic(m: Message, state: FSMContext):
    await state.clear()
    await state.set_state(OrganicFlow.waiting_input)
    await m.answer(
        "Пришли ссылки на посевные посты (t.me/...) и/или поисковые фразы — "
        "всё в одном сообщении, фразы по одной на строке."
    )


# ── обработка ввода ───────────────────────────────────────────────────────────

@router.message(OrganicFlow.waiting_input, F.text)
async def handle_input(m: Message, state: FSMContext):
    await state.clear()
    text = m.text or ""

    # 1. Ищем ссылки
    urls = URL_RE.findall(text)
    tg_urls = [u for u in urls if "t.me" in u]

    wait = await m.answer("Запускаю поиск… это может занять 1–2 минуты.")

    # 2. Парсим посты
    posts = []
    for url in tg_urls:
        post = await parse_tg_link(url)
        if post:
            posts.append(post)

    # 3. Собираем фразы
    seeds = []

    # — ручные фразы (строки без ссылок)
    text_no_urls = URL_RE.sub("", text)
    for line in text_no_urls.splitlines():
        line = line.strip()
        if len(line) >= 5:
            seeds.append(line)

    # — фразы из текстов посевов
    for post in posts:
        if post.text:
            seeds.extend(extract_seeds_from_text(post.text))

    # дедупликация
    seen = set()
    unique_seeds = []
    for s in seeds:
        if s not in seen:
            seen.add(s)
            unique_seeds.append(s)
    seeds = unique_seeds[:15]

    if not seeds:
        await wait.delete()
        await m.answer(
            "Не нашла фраз для поиска.\n"
            "Пришли ссылки на посты или напиши фразы вручную — по одной на строке."
        )
        return

    # 4. Временной диапазон
    timestamps = [p.timestamp for p in posts if p.timestamp > 0]
    since_ts = min(timestamps) if timestamps else int(time.time()) - ORGANIC_WINDOW_DAYS * 86400
    until_ts = since_ts + ORGANIC_WINDOW_DAYS * 86400

    # 5. Поиск
    try:
        results, diag = await search_telemetr(seeds, since_ts, until_ts)
    except Exception as e:
        await wait.delete()
        await m.answer(f"Ошибка поиска: <code>{esc(str(e))}</code>")
        return

    await wait.delete()

    if not results:
        await m.answer(
            f"Ничего не найдено.\n"
            f"Фраз: {len(seeds)} · Диапазон: {ORGANIC_WINDOW_DAYS} дней"
        )
        if ORGANIC_DEBUG:
            await m.answer(f"Диагностика: {diag}\nФразы: {seeds}")
        return

    total_views = sum(int(r.get("views") or r.get("views_count") or 0) for r in results)
    await m.answer(fmt_summary(since_ts, until_ts, len(results), total_views))

    for it in results[:MAX_CARDS]:
        try:
            await m.answer(fmt_result_card(it), disable_web_page_preview=True)
        except Exception:
            pass

    if ORGANIC_DEBUG:
        await m.answer(f"Диагностика: {diag}\nФразы: {seeds}")
