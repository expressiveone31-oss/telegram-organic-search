# bot/handlers/telemetr_search.py
# -*- coding: utf-8 -*-

from __future__ import annotations

import re
from datetime import datetime
from typing import List, Tuple

from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

from bot.services.telemetr_search import search_telemetr

router = Router(name="telemetr_router")


# ------------------------- FSM -------------------------

class TelemetrStates(StatesGroup):
    waiting_range = State()
    waiting_seeds = State()


# --------------------- date parsing ---------------------

_DASHES = "\u2012\u2013\u2014\u2015\u2212-"  # разные тире и минус + обычный дефис
_NBSP = "\u00A0"

def _normalize_spaces(s: str) -> str:
    # NBSP -> space, компактные множественные пробелы
    return re.sub(r"[ \t" + _NBSP + r"]+", " ", s.strip(), flags=re.UNICODE)

def _normalize_dashes(s: str) -> str:
    # все тире -> обычный дефис
    return re.sub("[" + _DASHES + "]", "-", s)

def _normalize_separators(s: str) -> str:
    # точки и слеши в датах -> дефис
    # 2025.10.23 / 2025/10/23 -> 2025-10-23
    s = re.sub(r"(\d{4})[./](\d{1,2})[./](\d{1,2})", r"\1-\2-\3", s)
    s = re.sub(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", r"\1-\2-\3", s)
    return s

def _to_ymd(s: str) -> str:
    """
    Преобразуем одну дату к формату YYYY-MM-DD.
    Поддержка:
      - YYYY-MM-DD
      - DD-MM-YYYY
    """
    s = s.strip()
    # ISO
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        y, mo, d = map(int, m.groups())
        return f"{y:04d}-{mo:02d}-{d:02d}"

    # DD-MM-YYYY
    m = re.fullmatch(r"(\d{1,2})-(\d{1,2})-(\d{4})", s)
    if m:
        d, mo, y = map(int, m.groups())
        return f"{y:04d}-{mo:02d}-{d:02d}"

    raise ValueError(f"bad date: {s!r}")

def _parse_range(text: str) -> Tuple[str, str]:
    """
    Принимает строку с диапазоном и возвращает (since, until) в YYYY-MM-DD.
    Терпима к:
      - разным тире (– — − -)
      - лишним/неразрывным пробелам
      - форматам дат (YYYY-MM-DD / YYYY.MM.DD / YYYY/MM/DD / DD.MM.YYYY / DD-MM-YYYY)
    """
    s = _normalize_spaces(text)
    s = _normalize_dashes(s)
    s = _normalize_separators(s)

    # допускаем один дефис в роли «минуса» и второй как разделитель — поэтому ищем
    # именно разделитель между датами: пробел? - пробел?
    # Примеры: "2025-10-23 - 2025-10-24", "2025-10-23-2025-10-24"
    # Разрешим один дефис в качестве разделителя, окружённый пробелами или нет.
    parts = re.split(r"\s*-\s*", s)
    if len(parts) != 2:
        # возможно использовали длинное тире без пробелов — уже нормализовано в дефис,
        # значит всё равно разделилось неверно -> попробуем самый правый дефис как разделитель:
        i = s.rfind("-")
        if i <= 0:
            raise ValueError("no delimiter")
        parts = [s[:i], s[i+1:]]

    left, right = parts[0], parts[1]
    since = _to_ymd(left)
    until = _to_ymd(right)

    # sanity-check
    if datetime.fromisoformat(until) < datetime.fromisoformat(since):
        since, until = until, since

    return since, until


# ---------------------- handlers ----------------------

@router.message(F.text == "/start")
async def start(msg: Message, state: FSMContext):
    await state.clear()
    await msg.answer(
        "Привет! Я бот поиска по **Телеграм**.\n"
        "Отправь диапазон дат в формате `YYYY-MM-DD  —  YYYY-MM-DD`.\n"
        "Поддерживаются также `DD.MM.YYYY` и `YYYY.MM.DD`, можно с обычным дефисом.\n"
        "Пример: `2025-10-22 — 2025-10-25`",
        parse_mode="Markdown"
    )
    await state.set_state(TelemetrStates.waiting_range)


@router.message(TelemetrStates.waiting_range)
async def got_range(msg: Message, state: FSMContext):
    text = msg.text or ""
    try:
        since, until = _parse_range(text)
    except Exception:
        await msg.reply("Не смог разобрать даты. Пример: `2025-10-22  —  2025-10-25`", parse_mode="Markdown")
        return

    await state.update_data(since=since, until=until)
    await msg.answer(
        f"Диапазон принят: **{since} — {until}**.\n"
        "Теперь пришли подводки или поисковые фразы (по одной на строке).\n"
        "Когда закончишь — просто отправь сообщение.",
        parse_mode="Markdown"
    )
    await state.set_state(TelemetrStates.waiting_seeds)


@router.message(TelemetrStates.waiting_seeds)
async def got_seeds_and_search(msg: Message, state: FSMContext):
    raw = (msg.text or "").strip()
    seeds: List[str] = [s.strip() for s in raw.splitlines() if s.strip()]
    if not seeds:
        await msg.reply("Не вижу фраз. Пришли по одной на строке.")
        return

    data = await state.get_data()
    since = data.get("since")
    until = data.get("until")

    await msg.answer("Запускаю поиск… Это может занять до 1–2 минут при большом количестве источников.")

    try:
        found, diag = await search_telemetr(seeds, since, until)
    except Exception as e:
        await msg.reply(f"⚠️ Ошибка поиска: {e!r}")
        return

    # краткая сводка
    total = len(found)
    by_seed = {}
    for it in found:
        by_seed.setdefault(it.get("_seed", ""), 0)
        by_seed[it.get("_seed", "")] += 1

    lines = [
        "Итоги поиска",
        f"Диапазон: **{since} — {until}**",
        f"Фраз: {len(seeds)}",
        f"Совпадений всего: **{total}**",
    ]
    if by_seed:
        lines.append("")
        lines.append("По фразам:")
        for s, n in by_seed.items():
            lines.append(f"• {s} — {n}")

    await msg.answer("\n".join(lines), parse_mode="Markdown")

    if not found:
        await msg.answer("❗По заданным параметрам ничего не найдено.")
        return

    # первые 10 результатов — ссылки
    shown = 0
    for it in found:
        link = it.get("_link") or ""
        body = (it.get("_body") or "").strip()
        if not link:
            continue
        shown += 1
        preview = body[:300] + ("…" if len(body) > 300 else "")
        await msg.answer(f"🔗 {link}\n\n{preview}")
        if shown >= 10:
            break

    # Диагностика в виде скрытого кода (чтобы не засорять чат)
    await msg.answer(f"```\n{diag}\n```", parse_mode="Markdown")

    await state.clear()
