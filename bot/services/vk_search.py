"""
Поиск органики во ВКонтакте через newsfeed.search.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import httpx

from bot.services import cache
from bot.utils.text import contains_phrase

logger = logging.getLogger(__name__)

VK_API = "https://api.vk.com/method"


def _cfg() -> Dict[str, Any]:
    return {
        "token":     os.getenv("VK_TOKEN", "").strip(),
        "max_pages": int(os.getenv("VK_MAX_PAGES", "5") or 5),
        # ВК отдаёт views далеко не у каждого поста: у записей из личных
        # профилей счётчика нет вовсе. Ненулевой порог отсеивает их все.
        "min_views": int(os.getenv("VK_MIN_VIEWS", "0") or 0),
        "strict":    os.getenv("VK_STRICT", "1") == "1",
    }


_contains = contains_phrase


def _text_of(it: Dict[str, Any]) -> str:
    """
    Весь текст записи. У репоста собственный text пустой, а оригинал лежит в
    copy_history — а органика во ВКонтакте это чаще всего именно репост.
    Подписи к вложениям тоже считаются: посев нередко уезжает в подпись к фото.
    """
    parts: List[str] = []

    def add(value: Any) -> None:
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())

    add(it.get("text"))

    for src in it.get("copy_history") or []:
        if isinstance(src, dict):
            add(src.get("text"))
            for att in src.get("attachments") or []:
                _add_attachment_text(att, add)

    for att in it.get("attachments") or []:
        _add_attachment_text(att, add)

    return " ".join(parts).strip()


def _add_attachment_text(att: Any, add) -> None:
    if not isinstance(att, dict):
        return
    body = att.get(att.get("type") or "")
    if isinstance(body, dict):
        for key in ("text", "title", "caption", "description"):
            add(body.get(key))


def _compact(it: Dict[str, Any]) -> Dict[str, Any]:
    """Вложения раздувают дамп на килобайты ссылок и прячут полезные поля."""
    out = {k: v for k, v in it.items() if k not in ("attachments", "copy_history")}
    out["attachments"] = [a.get("type") for a in it.get("attachments") or [] if isinstance(a, dict)]
    out["copy_history_texts"] = [
        (src.get("text") or "")[:200]
        for src in it.get("copy_history") or []
        if isinstance(src, dict)
    ]
    out["_text_of"] = _text_of(it)[:300]
    return out

# newsfeed.search доступен только по пользовательскому токену
_TOKEN_ERRORS = {5, 15, 27, 28}


class VkApiError(RuntimeError):
    def __init__(self, code: int, msg: str):
        self.code = code
        hint = ""
        if code in _TOKEN_ERRORS:
            hint = (
                "\n\nМетод newsfeed.search работает только с пользовательским "
                "токеном ВК. Сервисный токен и токен сообщества его не открывают."
            )
        super().__init__(f"VK API error {code}: {msg}{hint}")


async def _call(
    client: httpx.AsyncClient,
    token: str,
    method: str,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    r = await client.get(
        f"{VK_API}/{method}",
        params={"v": "5.199", "access_token": token, **params},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        err = data["error"]
        raise VkApiError(int(err.get("error_code") or 0), str(err.get("error_msg") or ""))
    return data["response"]


async def search_vk(
    seeds: List[str],
    since_ts: int,
    until_ts: int,
) -> Tuple[List[Dict[str, Any]], str]:
    cfg = _cfg()
    if not cfg["token"]:
        raise RuntimeError("VK_TOKEN is not set")

    results: List[Dict[str, Any]] = []
    diag_parts = []
    seen: set[str] = set()
    raw_sample: Optional[Dict[str, Any]] = None
    last_error: Optional[Exception] = None
    skipped_views = 0
    skipped_dupes = 0
    skipped_no_text = 0
    skipped_no_match = 0

    async with httpx.AsyncClient() as client:
        for seed in seeds:
            ckey = cache.make_key("vk", seed, since_ts, until_ts, cfg["max_pages"])

            cached = cache.get(ckey)
            if cached is not None:
                items_all: List[Dict[str, Any]] = cached
                logger.info("VK seed=%r: %d items from cache", seed, len(items_all))
            else:
                items_all = []
                next_from = None

                for _page in range(cfg["max_pages"]):
                    params: Dict[str, Any] = {
                        "q": seed,
                        "count": 50,
                        "start_time": since_ts,
                        "end_time": until_ts,
                    }
                    if next_from:
                        params["start_from"] = next_from

                    try:
                        resp = await _call(client, cfg["token"], "newsfeed.search", params)
                    except Exception as e:
                        logger.error("VK search error seed=%r: %s", seed, e)
                        last_error = e
                        break

                    items = resp.get("items", [])
                    next_from = resp.get("next_from")
                    if not items:
                        break
                    items_all.extend(items)

                    # Страница без дословных совпадений — дальше только шум
                    if not any(_contains(seed, _text_of(it)) for it in items):
                        logger.info("VK seed=%r: stop at page %d, no exact hits", seed, _page + 1)
                        break
                    if not next_from:
                        break

                cache.set(ckey, items_all)

            if items_all and raw_sample is None:
                raw_sample = items_all[0]

            matched = 0
            for it in items_all:
                views = (it.get("views") or {}).get("count", 0)
                if views < cfg["min_views"]:
                    skipped_views += 1
                    continue
                text = _text_of(it)
                if not text:
                    skipped_no_text += 1
                    continue
                if cfg["strict"] and not _contains(seed, text):
                    skipped_no_match += 1
                    continue

                url = f"https://vk.com/wall{it.get('owner_id')}_{it.get('id')}"
                if url in seen:
                    skipped_dupes += 1
                    continue
                seen.add(url)

                matched += 1
                results.append({
                    "date":    it.get("date", 0),
                    "views":   views,
                    "url":     url,
                    "excerpt": text[:200] + ("…" if len(text) > 200 else ""),
                    "_seed":   seed,
                })

            logger.info("VK seed=%r fetched=%d matched=%d", seed, len(items_all), matched)
            diag_parts.append(f"'{seed}': {matched}/{len(items_all)}")

    # Ошибку API нельзя прятать за «ничего не найдено»: чаще всего это
    # неподходящий токен, и без текста ошибки это не диагностируется.
    if not results and last_error is not None:
        raise last_error

    results.sort(key=lambda r: r["date"], reverse=True)
    diag = (
        "VK: " + "; ".join(diag_parts)
        + f" | no_text={skipped_no_text}, no_match={skipped_no_match}, "
        + f"low_views={skipped_views}, dupes={skipped_dupes} | {cache.stats()}"
    )
    if os.getenv("ORGANIC_DEBUG", "0") == "1" and raw_sample is not None:
        sample = json.dumps(_compact(raw_sample), ensure_ascii=False, default=str)
        diag += "\n\nСырой ответ: " + sample[:1500]
    return results, diag
