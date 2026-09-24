"""
Хендлер поиска органики в Telegram и ВКонтакте.

Флоу:
  /start → инструкция, ждём ввода
  Пользователь присылает ссылки на посевные посты (и опционально свои фразы)
  Бот парсит посты, извлекает ключевые словосочетания, показывает список
  Пользователь может отредактировать фразы или сразу нажать [Telegram]/[ВКонтакте]
"""
from __future__ import annotations

import logging
import os
import re
import time
from datetime import datetime, timezone

from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from bot.services.link_parser import parse_link, extract_seeds_from_posts
from bot.services.telemetr_search import search_telemetr
from bot.services.vk_search import search_vk
from bot.utils.formatting import esc, fmt_tg_summary, fmt_vk_summary, fmt_tg_card, fmt_vk_card

logger = logging.getLogger(__name__)
router = Router()

ORGANIC_WINDOW_DAYS = int(os.getenv("ORGANIC_WINDOW_DAYS", "14"))
ORGANIC_DEBUG       = os.getenv("ORGANIC_DEBUG", "0") == "1"
MAX_CARDS           = int(os.getenv("ORGANIC_MAX_CARDS", "15"))

URL_RE = re.compile(r"https?://\S+")


class OrganicFlow(StatesGroup):
    waiting_input    = State()
    waiting_platform = State()


def _platform_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Telegram", callback_data="platform:tg"),
        InlineKeyboardButton(text="ВКонтакте", callback_data="platform:vk"),
    ]])


@router.message(Command("start"))
async def cmd_start(m: Message, state: FSMContext):
    await state.clear()
    await state.set_state(OrganicFlow.waiting_input)
    await m.answer(
        "Привет! Ищу органику по посевам.\n\n"
        "Пришли ссылки на посевные посты — t.me/... или vk.com/wall...\n"
        "Можно сразу несколько в одном сообщении.\n\n"
        "Фразы для поиска извлеку из текстов постов автоматически. "
        "Или добавь свои — по одной строке после ссылок."
    )


@router.message(StateFilter(OrganicFlow.waiting_input, OrganicFlow.waiting_platform), F.text)
async def handle_input(m: Message, state: FSMContext):
    text = m.text or ""

    urls = URL_RE.findall(text)

    # — парсим все ссылки
    parsing_msg = await m.answer("Читаю посты…")
    posts = []
    for url in urls:
        post = await parse_link(url)
        if post:
            posts.append(post)
    await parsing_msg.delete()

    # — ручные фразы: строки без ссылок
    text_no_urls = URL_RE.sub("", text)
    manual_seeds = [
        line.strip()
        for line in text_no_urls.splitlines()
        if len(line.strip()) >= 4
    ]

    if not posts and not manual_seeds:
        await m.answer(
            "Не нашла ни ссылок, ни фраз.\n"
            "Пришли ссылки на посевные посты (t.me/... или vk.com/wall...)."
        )
        return

    # — фразы: сначала ручные, потом автоизвлечённые из текстов постов
    auto_seeds = extract_seeds_from_posts([p.text for p in posts if p.text]) if posts else []
    seeds = list(dict.fromkeys(manual_seeds + auto_seeds))[:12]  # дедуп, макс 12

    if not seeds:
        await m.answer(
            "Не удалось извлечь фразы из постов.\n"
            "Напиши поисковые слова вручную — по одной строке."
        )
        return

    # — временной диапазон
    timestamps = [p.timestamp for p in posts if p.timestamp > 0]
    since_ts = min(timestamps) if timestamps else int(time.time()) - ORGANIC_WINDOW_DAYS * 86400
    until_ts = since_ts + ORGANIC_WINDOW_DAYS * 86400
    since_str = datetime.fromtimestamp(since_ts, tz=timezone.utc).strftime("%Y-%m-%d")
    until_str = datetime.fromtimestamp(until_ts, tz=timezone.utc).strftime("%Y-%m-%d")

    await state.set_state(OrganicFlow.waiting_platform)
    await state.update_data(seeds=seeds, since_ts=since_ts, until_ts=until_ts)

    seeds_preview = "\n".join(f"• {s}" for s in seeds)
    await m.answer(
        f"<b>Посты:</b> {len(posts)} · <b>Диапазон:</b> {since_str} — {until_str}\n\n"
        f"<b>Фразы для поиска ({len(seeds)}):</b>\n{seeds_preview}\n\n"
        "Где искать?",
        reply_markup=_platform_kb(),
    )


@router.callback_query(OrganicFlow.waiting_platform, F.data.startswith("platform:"))
async def handle_platform(cb: CallbackQuery, state: FSMContext):
    platform = cb.data.split(":")[1]
    data = await state.get_data()
    seeds: list[str] = data.get("seeds", [])
    since_ts: int    = data.get("since_ts", 0)
    until_ts: int    = data.get("until_ts", 0)

    # Состояние не чистим: фразы остаются, чтобы поиск по второй соцсети
    # не требовал заново присылать ссылки и заново парсить посты.
    await cb.answer()

    label = "Telegram" if platform == "tg" else "ВКонтакте"
    wait = await cb.message.edit_text(f"Ищу в {label}… может занять 1–2 минуты.")

    try:
        if platform == "tg":
            results, diag = await search_telemetr(seeds, since_ts, until_ts)
        else:
            results, diag = await search_vk(seeds, since_ts, until_ts)
    except Exception as e:
        logger.error("Search error platform=%s: %s", platform, e, exc_info=True)
        await wait.edit_text(f"Ошибка поиска: <code>{esc(str(e))}</code>")
        await state.set_state(OrganicFlow.waiting_platform)
        return

    logger.info("Search done platform=%s results=%d diag=%s", platform, len(results), diag)

    if not results:
        await wait.edit_text(
            f"Ничего не найдено в {label}.\n\n"
            f"Фраз: {len(seeds)}\n"
            f"Диагностика: <code>{esc(diag)}</code>",
            reply_markup=_platform_kb(),
        )
        await state.set_state(OrganicFlow.waiting_platform)
        return

    if platform == "tg":
        total_views = sum(int(r.get("views") or r.get("views_count") or 0) for r in results)
        await wait.edit_text(fmt_tg_summary(since_ts, until_ts, len(results), total_views))
        for it in results[:MAX_CARDS]:
            try:
                await cb.message.answer(fmt_tg_card(it), disable_web_page_preview=True)
            except Exception as e:
                logger.warning("Failed to send TG card: %s", e)
    else:
        total_views = sum(r.get("views", 0) for r in results)
        await wait.edit_text(fmt_vk_summary(since_ts, until_ts, len(results), total_views))
        for it in results[:MAX_CARDS]:
            try:
                await cb.message.answer(fmt_vk_card(it), disable_web_page_preview=True)
            except Exception as e:
                logger.warning("Failed to send VK card: %s", e)

    if ORGANIC_DEBUG:
        await cb.message.answer(f"Диагностика: <code>{esc(diag)}</code>\nФразы: {seeds}")

    await state.set_state(OrganicFlow.waiting_platform)
    await cb.message.answer(
        "Готово! Можно поискать те же фразы в другой соцсети "
        "или прислать следующий посев.",
        reply_markup=_platform_kb(),
    )
