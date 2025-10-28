# bot/services/telemetr_search.py
# -*- coding: utf-8 -*-

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

# =============================
# ENV / настройки
# =============================

TELEM_TOKEN = (os.getenv("TELEMETR_TOKEN") or "").strip()

# Кавычки вокруг запроса (для строгого поиска у Telemetr)
TELEM_USE_QUOTES = (os.getenv("TELEMETR_USE_QUOTES", "1") == "1")

# Требовать точного вхождения семени в тексте поста (на нашей стороне)
TELEM_REQUIRE_EXACT = (os.getenv("TELEMETR_REQUIRE_EXACT", "0") == "1")

# Если у поста нет текста (только медиа/ссылка), доверять самому факту попадания в Telemetr
TELEM_TRUST_QUERY = (os.getenv("TELEMETR_TRUST_QUERY", "1") == "1")

# Минимум просмотров (фильтр на нашей стороне)
TELEM_MIN_VIEWS = int(os.getenv("TELEMETR_MIN_VIEWS", "0") or 0)

# Сколько страниц Telemetr запрашивать (по 50 элементов каждая)
TELEM_PAGES = max(1, int(os.getenv("TELEMETR_PAGES", "2") or 2))

TELEM_BASE_URL = "https://api.telemetr.me"


# =============================
# Вспомогательные функции
# =============================

def _normalize_seed(seed: str) -> str:
    """
    Подготавливаем поисковую фразу к запросу Telemetr.
    Если включены кавычки — оборачиваем в двойные.
    """
    s = (seed or "").strip()
    if not s:
        return s
    if TELEM_USE_QUOTES and not (s.startswith('"') and s.endswith('"')):
        s = f"\"{s}\""
    return s


def _as_dict(it: Any) -> Dict[str, Any]:
    """
    Telemetr в "items" может вернуть как словари, так и строки.
    Приводим к унифицированному виду словаря, чтобы дальше не ловить .get на str.
    """
    if isinstance(it, dict):
        return it
    if isinstance(it, str):
        return {"text": it}
    # неизвестная форма — вернём пустой словарь (будет отброшено)
    return {}


def _body_from_item(d: Dict[str, Any]) -> str:
    """
    Собираем человекочитаемый текст поста из безопасных полей.
    Игнорируем любые вложенные структуры, которые могут ломать форматирование.
    """
    parts: List[str] = []
    for key in ("title", "text", "caption"):
        v = d.get(key)
        if isinstance(v, str) and v.strip():
            parts.append(v.strip())
    return "\n".join(parts).strip()


def _contains_exact(needle: str, haystack: str) -> bool:
    """Простой точный матч (регистр сохраняем — так честнее для фраз)."""
    return bool(needle and haystack and needle in haystack)


def _views_of(d: Dict[str, Any]) -> int:
    """
    Достаём число просмотров из разных возможных ключей.
    Если не удаётся — возвращаем 0.
    """
    v = d.get("views")
    if v is None:
        v = d.get("views_count")
    try:
        return int(v or 0)
    except Exception:
        return 0


def _link_of(d: Dict[str, Any]) -> str:
    """
    Ссылка для показа пользователю: display_url > url > link.
    """
    for k in ("display_url", "url", "link"):
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


# =============================
# Работа с API Telemetr
# =============================

async def _fetch_page(
    session: aiohttp.ClientSession,
    query: str,
    since: str,
    until: str,
    page: int,
    limit: int = 50,
) -> Tuple[List[Any], Dict[str, Any]]:
    """
    Возвращает items (как есть — str|dict) и метаданные.
    Никаких .get на items здесь не делаем.
    """
    if not TELEM_TOKEN:
        raise RuntimeError("TELEMETR_TOKEN is not set")

    params = {
        "query": query,
        "date_from": since,
        "date_to": until,
        "limit": str(limit),
        "page": str(page),
    }
    headers = {"Authorization": f"Bearer {TELEM_TOKEN}"}

    url = f"{TELEM_BASE_URL}/channels/posts/search"
    async with session.get(url, params=params, headers=headers, timeout=30) as resp:
        # Telemetr может отдавать application/json; charset=utf-8, иногда без content-type
        data = await resp.json(content_type=None)

    if not isinstance(data, dict):
        return [], {"error": "non-dict-response", "raw": data}

    if data.get("status") != "ok":
        return [], {"error": data}

    resp_obj = data.get("response") or {}
    items = resp_obj.get("items") or []
    if not isinstance(items, list):
        # на всякий
        items = []

    meta = {
        "count": resp_obj.get("count"),
        "total_count": resp_obj.get("total_count"),
        "page": page,
    }
    return items, meta


# =============================
# Публичная функция поиска
# =============================

async def search_telemetr(
    seeds: List[str],
    since: str,
    until: str,
    *,
    session: Optional[aiohttp.ClientSession] = None,
) -> Tuple[List[Dict[str, Any]], str]:
    """
    Ищем посты в Telemetr по списку фраз `seeds` и диапазону дат.
    Возвращаем:
      - список совпадений (словарей с нормализованными полями)
      - строку-диагностику
    """
    seeds_raw = [s.strip() for s in (seeds or []) if s and s.strip()]
    if not seeds_raw:
        return [], "Telemetr: нет фраз для поиска"

    seeds_q = [_normalize_seed(s) for s in seeds_raw]

    diag: List[str] = []
    diag.append(
        f"Telemetr diag: exact={'on' if TELEM_REQUIRE_EXACT else 'off'}, "
        f"quotes={'on' if TELEM_USE_QUOTES else 'off'}, "
        f"trust_no_text={'on' if TELEM_TRUST_QUERY else 'off'}, "
        f"min_views={TELEM_MIN_VIEWS}, pages={TELEM_PAGES}"
    )

    own_session = False
    if session is None:
        own_session = True
        session = aiohttp.ClientSession()

    matched: List[Dict[str, Any]] = []
    total_candidates = 0

    try:
        for idx, raw_seed in enumerate(seeds_raw):
            q = seeds_q[idx]

            fetched_total = 0
            malformed = 0
            after_views = 0
            local_matched = 0

            items_all: List[Any] = []

            # Пагинация
            for page in range(1, TELEM_PAGES + 1):
                try:
                    items, meta = await _fetch_page(session, q, since, until, page)
                except Exception as e:
                    diag.append(f"seed='{raw_seed}': fetch page={page} error: {e!r}")
                    break

                fetched_total += len(items)
                items_all.extend(items)

                # Если пришло меньше 50, дальше страниц скорее всего нет
                if len(items) < 50:
                    break

            # Нормализуем items → dict
            norm: List[Dict[str, Any]] = []
            for it in items_all:
                d = _as_dict(it)
                if not d:
                    malformed += 1
                    continue
                # фильтр по просмотрам
                if _views_of(d) >= TELEM_MIN_VIEWS:
                    norm.append(d)
            after_views = len(norm)

            # Локальная проверка соответствия (если запрошен точный матч)
            for d in norm:
                body = _body_from_item(d)
                ok = True
                if TELEM_REQUIRE_EXACT:
                    if body:
                        ok = _contains_exact(raw_seed, body)
                    else:
                        # если текста нет, можно «доверять» попаданию в Telemetr как подтверждению
                        ok = TELEM_TRUST_QUERY

                if ok:
                    d["_seed"] = raw_seed
                    d["_link"] = _link_of(d)
                    matched.append(d)
                    local_matched += 1

            total_candidates += after_views
            diag.append(
                f"seed='{raw_seed}': fetched={fetched_total}, malformed={malformed}, "
                f"after_views={after_views}, matched={local_matched}"
            )

        diag.append(f"total_candidates={total_candidates}, total_matched={len(matched)}")
        return matched, "\n".join(diag)

    finally:
        if own_session:
            await session.close()
