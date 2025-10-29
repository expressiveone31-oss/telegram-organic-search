
from __future__ import annotations
import re
from typing import Tuple
from aiogram import Router, F
from aiogram.types import Message
from bot.services.telemetr_search import search_telemetr
from bot.utils.formatting import esc, fmt_result_card, fmt_summary

router = Router()

DATE_RE = re.compile(r"\s*(\d{4})[.\-/–— ](\d{2})[.\-/–— ](\d{2})\s*[–—-]\s*(\d{4})[.\-/–— ](\d{2})[.\-/–— ](\d{2})\s*")

def _parse_range(text: str) -> Tuple[str, str] | None:
    t = (text or "").strip().replace("\u2013", "-").replace("\u2014", "-")
    m = DATE_RE.fullmatch(t)
    if not m:
        return None
    y1, m1, d1, y2, m2, d2 = m.groups()
    return f"{y1}-{m1}-{d1}", f"{y2}-{m2}-{d2}"

@router.message(F.text == "/start")
async def cmd_start(m: Message):
    await m.answer("Привет! Я бот поиска по <b>Телеграм</b>.\nОтправь диапазон дат в формате <code>YYYY-MM-DD  —  YYYY-MM-DD</code>.")

_user_ranges: dict[int, Tuple[str, str]] = {}

@router.message(F.text.regexp(r"\d{4}.*\d{4}"))
async def set_range(m: Message):
    parsed = _parse_range(m.text or "")
    if not parsed:
        await m.answer("Не смог разобрать даты. Пример: <code>2025-10-22  —  2025-10-25</code>")
        return
    _user_ranges[m.from_user.id] = parsed
    await m.answer(f"Диапазон принят: <b>{parsed[0]} — {parsed[1]}</b>.\nТеперь пришли подводки или поисковые фразы (по одной на строке).\nКогда закончишь — просто отправь сообщение.")

@router.message(F.text)
async def receive_seeds(m: Message):
    uid = m.from_user.id
    if uid not in _user_ranges:
        return
    seeds_raw = [s.strip() for s in (m.text or "").splitlines() if s.strip()]
    if not seeds_raw:
        await m.answer("Пришли хотя бы одну фразу — по одной на строке.")
        return
    since, until = _user_ranges.pop(uid)
    await m.answer("Запускаю поиск... Это может занять до 1–2 минут при большом количестве источников.\n"
                   f"<b>Диапазон:</b> {since} — {until}\n<b>Фраз:</b> {len(seeds_raw)}")
    try:
        results, diag = await search_telemetr(seeds_raw, since, until)
    except Exception as e:
        await m.answer(f"⚠️ Ошибка поиска: <code>{esc(str(e))}</code>")
        return
    if not results:
        await m.answer("По заданным параметрам ничего не найдено.")
        return
    total_views = sum(int(r.get('views') or 0) for r in results)
    await m.answer(fmt_summary(since, until, len(results), total_views))
    for it in results[:12]:
        await m.answer(fmt_result_card(it))
