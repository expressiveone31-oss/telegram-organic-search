"""
Хендлер поиска органики в Telegram и ВКонтакте.

Флоу:
  /start  →  инструкция
  Пользователь кидает ссылки на посевные посты и/или фразы
  Бот отвечает кнопками: [Telegram] [ВКонтакте]
  После выбора — ищет и возвращает карточки
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
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from bot.services.link_parser import parse_link, extract_seeds_from_text
from bot.services.telemetr_search import search_telemetr
from bot.services.vk_search import search_vk
from bot.utils.formatting import (
    esc, fmt_tg_summary, fmt_vk_summary, fmt_tg_card, fmt_vk_card
)

logger = logging.getLogger(__name__)
router = Router()

ORGANIC_DEBUG       = os.getenv("ORGANIC_DEBUG", "0") == "1"
ORGANIC_WINDOW_DAYS = int(os.getenv("ORGANIC_WINDOW_DAYS", "14"))
MAX_CARDS           = int(os.getenv("ORGANIC_MAX_CARDS", "15"))

URL_RE = re.compile(r"https?://\S+")


class OrganicFlow(StatesGroup):
    waiting_input    = State()  # ждём ссылки/фразы
    waiting_platform = State()  # ждём выбор платформы


def _platform_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Telegram", callback_data="platform:tg"),
        InlineKeyboardButton(text="ВКонтакте", callback_data="platform:vk"),
    ]])


# ── /start ───────────────────────────────────────────────────────────────────

@router.message(Command("start"))
async def cmd_start(m: Message, state: FSMContext):
    await state.clear()
    await state.set_state(OrganicFlow.waiting_input)
    await m.answer(
        "Привет! Ищу органику по посевам.\n\n"
        "Пришли ссылки на посевные посты и/или поисковые фразы — "
        "всё в одном сообщении, фразы по одной на строке.\n\n"
        "Поддерживаю ссылки <b>t.me/...</b> и <b>vk.com/wall...</b>"
    )


# ── приём посевного материала ─────────────────────────────────────────────────

@router.message(OrganicFlow.waiting_input, F.text)
@router.message(F.text & ~F.text.startswith("/"))  # принимаем и без команды
async def handle_input(m: Message, state: FSMContext):
    text = m.text or ""

    # парсим ссылки
    urls = URL_RE.findall(text)
    posts = []
    for url in urls:
        post = await parse_link(url)
        if post:
            posts.append(post)

    # собираем фразы
    seeds = []
    text_no_urls = URL_RE.sub("", text)
    for line in text_no_urls.splitlines():
        line = line.strip()
        if len(line) >= 5:
            seeds.append(line)

    for post in posts:
        if post.text:
            seeds.extend(extract_seeds_from_text(post.text))

    # дедупликация
    seen: set[str] = set()
    unique: list[str] = []
    for s in seeds:
        if s not in seen:
            seen.add(s)
            unique.append(s)
    seeds = unique[:15]

    if not seeds and not posts:
        await m.answer(
            "Не нашла ни ссылок, ни фраз.\n"
            "Пришли ссылки на посты или напиши фразы — по одной на строке."
        )
        return

    # временной диапазон
    timestamps = [p.timestamp for p in posts if p.timestamp > 0]
    since_ts = min(timestamps) if timestamps else int(time.time()) - ORGANIC_WINDOW_DAYS * 86400
    until_ts = since_ts + ORGANIC_WINDOW_DAYS * 86400

    # сохраняем в state и спрашиваем платформу
    await state.set_state(OrganicFlow.waiting_platform)
    await state.update_data(seeds=seeds, since_ts=since_ts, until_ts=until_ts)

    await m.answer(
        f"Фраз для поиска: <b>{len(seeds)}</b>\n"
        f"Диапазон: <b>{ORGANIC_WINDOW_DAYS} дней</b> от первого поста\n\n"
        "Где искать?",
        reply_markup=_platform_keyboard(),
    )


# ── выбор платформы ───────────────────────────────────────────────────────────

@router.callback_query(OrganicFlow.waiting_platform, F.data.startswith("platform:"))
async def handle_platform(cb: CallbackQuery, state: FSMContext):
    platform = cb.data.split(":")[1]  # "tg" или "vk"
    data = await state.get_data()
    seeds: list[str] = data.get("seeds", [])
    since_ts: int = data.get("since_ts", 0)
    until_ts: int = data.get("until_ts", 0)

    await state.clear()
    await cb.answer()

    label = "Telegram" if platform == "tg" else "ВКонтакте"
    wait = await cb.message.edit_text(f"Ищу в {label}… это может занять 1–2 минуты.")

    try:
        if platform == "tg":
            results, diag = await search_telemetr(seeds, since_ts, until_ts)
        else:
            results, diag = await search_vk(seeds, since_ts, until_ts)
    except Exception as e:
        await wait.edit_text(f"Ошибка поиска: <code>{esc(str(e))}</code>")
        return

    if not results:
        await wait.edit_text(
            f"Ничего не найдено в {label}.\n"
            f"Фраз: {len(seeds)} · Диапазон: {ORGANIC_WINDOW_DAYS} дней"
        )
        if ORGANIC_DEBUG:
            await cb.message.answer(f"Диагностика: {diag}\nФразы: {seeds}")
        return

    if platform == "tg":
        total_views = sum(int(r.get("views") or r.get("views_count") or 0) for r in results)
        await wait.edit_text(fmt_tg_summary(since_ts, until_ts, len(results), total_views))
        for it in results[:MAX_CARDS]:
            try:
                await cb.message.answer(fmt_tg_card(it), disable_web_page_preview=True)
            except Exception:
                pass
    else:
        total_views = sum(r.get("views", 0) for r in results)
        await wait.edit_text(fmt_vk_summary(since_ts, until_ts, len(results), total_views))
        for it in results[:MAX_CARDS]:
            try:
                await cb.message.answer(fmt_vk_card(it), disable_web_page_preview=True)
            except Exception:
                pass

    if ORGANIC_DEBUG:
        await cb.message.answer(f"Диагностика: {diag}\nФразы: {seeds}")

    # готовы к следующему запросу
    await state.set_state(OrganicFlow.waiting_input)
    await cb.message.answer("Готово! Можешь прислать следующий посев.")
