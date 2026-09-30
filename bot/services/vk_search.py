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
from bot.utils.text import contains_phrase, phrase_overlap

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
        # список стен через запятую, если глобальный поиск их не видит
        "owners":    _parse_owner_list(os.getenv("VK_WALL_OWNERS", "")),
    }


def _parse_owner_list(raw: str) -> List[int]:
    out: List[int] = []
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if part.lstrip("-").isdigit():
            out.append(int(part))
    return out


_contains = contains_phrase

# newsfeed.search склеивает слова через AND. Длинное предложение из 8+ слов
# почти всегда даёт 0 записей — индекс не находит документ, где есть все сразу.
# В API уходит короткое окно, полное предложение проверяем у себя.
_QUERY_STOP = {
    "в", "на", "по", "из", "за", "к", "у", "о", "об", "и", "а", "но", "не",
    "что", "как", "это", "мы", "вы", "они", "он", "она", "я", "бы", "уже",
    "еще", "ещё", "там", "тут", "для", "при", "без", "или", "то", "же",
}
_QUERY_WINDOW = 5


def _clean_query(seed: str) -> str:
    return " ".join(
        seed.replace("«", " ").replace("»", " ").replace('"', " ")
        .replace("“", " ").replace("”", " ").split()
    )


def queries_for_seed(seed: str) -> List[str]:
    """Запросы к API: короткое характерное окно, затем полная фраза."""
    clean = _clean_query(seed)
    if not clean:
        return []
    words = clean.split()
    out: List[str] = []
    if len(words) > _QUERY_WINDOW:
        window = _best_window(words, _QUERY_WINDOW)
        if window:
            out.append(window)
        tail = " ".join(words[-_QUERY_WINDOW:])
        if tail.lower() != (window or "").lower():
            out.append(tail)
    out.append(clean)
    seen: set[str] = set()
    uniq: List[str] = []
    for q in out:
        key = q.lower()
        if key not in seen:
            seen.add(key)
            uniq.append(q)
    return uniq


def _best_window(words: List[str], size: int) -> str:
    best, best_score = "", -1
    for i in range(0, len(words) - size + 1):
        window = words[i : i + size]
        score = sum(
            2 if len(w) >= 5 else 1
            for w in window
            if w.lower() not in _QUERY_STOP and len(w) >= 4
        )
        if score > best_score:
            best_score, best = score, " ".join(window)
    return best


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


async def _search_wall(
    client: httpx.AsyncClient,
    token: str,
    owner_id: int,
    query: str,
) -> List[Dict[str, Any]]:
    """Поиск по одной стене. Кавычки в wall.search означают точную фразу."""
    clean = _clean_query(query)
    if not clean:
        return []
    params = {"owner_id": owner_id, "query": f'"{clean}"', "count": 100}
    try:
        resp = await _call(client, token, "wall.search", params)
    except Exception as e:
        logger.error("VK wall.search owner=%s q=%r: %s", owner_id, clean, e)
        try:
            resp = await _call(
                client, token, "wall.search",
                {"owner_id": owner_id, "query": clean, "count": 100},
            )
        except Exception:
            return []
    if isinstance(resp, list):
        return [x for x in resp if isinstance(x, dict)]
    return list(resp.get("items") or [])


async def search_vk(
    seeds: List[str],
    since_ts: int,
    until_ts: int,
    owners: Optional[List[int]] = None,
) -> Tuple[List[Dict[str, Any]], str]:
    cfg = _cfg()
    if not cfg["token"]:
        raise RuntimeError("VK_TOKEN is not set")
    owners = list(dict.fromkeys(list(owners or []) + cfg["owners"]))

    results: List[Dict[str, Any]] = []
    diag_parts = []
    seen: set[str] = set()
    raw_sample: Optional[Dict[str, Any]] = None
    last_error: Optional[Exception] = None
    skipped_views = 0
    skipped_dupes = 0
    skipped_no_text = 0
    skipped_no_match = 0
    closest: List[str] = []

    async with httpx.AsyncClient() as client:
        for seed in seeds:
            ckey = cache.make_key(
                "vk", seed, since_ts, until_ts, cfg["max_pages"], "qwin5",
                ",".join(map(str, owners or ())),
            )

            cached = cache.get(ckey)
            if cached is not None:
                items_all: List[Dict[str, Any]] = cached
                logger.info("VK seed=%r: %d items from cache", seed, len(items_all))
            else:
                items_all = []
                seen_posts: set[tuple] = set()
                for query in queries_for_seed(seed):
                    next_from = None
                    barren = 0
                    for _page in range(cfg["max_pages"]):
                        params: Dict[str, Any] = {
                            "q": query,
                            "count": 50,
                            "start_time": since_ts,
                            "end_time": until_ts,
                        }
                        if next_from:
                            params["start_from"] = next_from

                        try:
                            resp = await _call(client, cfg["token"], "newsfeed.search", params)
                        except Exception as e:
                            logger.error("VK search error seed=%r q=%r: %s", seed, query, e)
                            last_error = e
                            break

                        items = resp.get("items", [])
                        next_from = resp.get("next_from")
                        if not items:
                            break

                        for it in items:
                            key = (it.get("owner_id"), it.get("id"))
                            if key in seen_posts:
                                continue
                            seen_posts.add(key)
                            items_all.append(it)

                        page_hits = sum(1 for it in items if _contains(seed, _text_of(it)))
                        barren = barren + 1 if page_hits == 0 else 0
                        if barren >= 2 or not next_from:
                            break

                for owner_id in owners or []:
                    wall_q = (queries_for_seed(seed) or [seed])[0]
                    for it in await _search_wall(client, cfg["token"], owner_id, wall_q):
                        key = (it.get("owner_id"), it.get("id"))
                        if key in seen_posts:
                            continue
                        seen_posts.add(key)
                        items_all.append(it)

                cache.set(ckey, items_all)

            if items_all and raw_sample is None:
                raw_sample = items_all[0]

            matched = 0
            best_miss: Optional[tuple[float, str]] = None
            for it in items_all:
                views = (it.get("views") or {}).get("count", 0)
                if views < cfg["min_views"]:
                    skipped_views += 1
                    continue
                text = _text_of(it)
                ts = int(it.get("date") or 0)
                if ts and (ts < since_ts or ts > until_ts):
                    continue
                if not text:
                    skipped_no_text += 1
                    continue
                if cfg["strict"] and not _contains(seed, text):
                    skipped_no_match += 1
                    score = phrase_overlap(seed, text)
                    if best_miss is None or score > best_miss[0]:
                        best_miss = (score, text[:180].replace("\n", " "))
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
            if best_miss and matched == 0:
                closest.append(f"{best_miss[0]:.0%} {best_miss[1]}")

    # Ошибку API нельзя прятать за «ничего не найдено»: чаще всего это
    # неподходящий токен, и без текста ошибки это не диагностируется.
    if not results and last_error is not None:
        raise last_error

    results.sort(key=lambda r: r["date"], reverse=True)
    diag = (
        "VK: " + "; ".join(diag_parts)
        + f" | no_text={skipped_no_text}, no_match={skipped_no_match}, "
        + f"low_views={skipped_views}, dupes={skipped_dupes}, walls={len(owners or [])} | {cache.stats()}"
    )
    if closest:
        diag += "\n\nБлижайшие промахи:\n" + "\n".join(f"• {c}" for c in closest[:8])
    if os.getenv("ORGANIC_DEBUG", "0") == "1" and raw_sample is not None:
        sample = json.dumps(_compact(raw_sample), ensure_ascii=False, default=str)
        diag += "\n\nСырой ответ: " + sample[:1500]
    return results, diag
