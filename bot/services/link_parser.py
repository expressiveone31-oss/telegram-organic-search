"""
Парсинг ссылок на посты TG и VK.
Возвращает текст поста и unix-timestamp даты публикации.
"""
from __future__ import annotations

import os
import re
import logging
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

TG_URL_RE       = re.compile(r"https?://t\.me/(?:s/)?([A-Za-z0-9_]+)/(\d+)")
VK_URL_RE       = re.compile(r"https?://vk\.(?:com|ru)/wall(-?\d+)_(\d+)")
VK_SHORT_URL_RE = re.compile(r"https?://vk\.(?:com|ru)/[^?#]+\?w=wall(-?\d+)_(\d+)")

# Стоп-слова — не идут в поисковые фразы
_STOPWORDS = {
    # предлоги
    "и", "в", "на", "с", "по", "из", "за", "к", "у", "о", "об", "при", "под",
    "над", "без", "для", "про", "через", "перед", "между", "среди",
    # союзы
    "а", "но", "или", "что", "как", "если", "когда", "чтобы", "потому",
    "также", "тоже", "либо", "хотя", "пока",
    # местоимения
    "это", "все", "там", "тут", "мы", "вы", "они", "он", "она", "я", "то",
    "ваши", "наши", "свои", "такой", "такая", "такое", "такие", "этот",
    "эта", "эти", "того", "этого", "свой", "сами", "сама", "само",
    # частицы/наречия
    "уже", "ещё", "еще", "только", "бы", "не", "да", "нет", "же", "вот",
    "здесь", "там", "тут", "очень", "quite", "very",
    # глаголы-связки и частые глаголы
    "стала", "стало", "стали", "была", "было", "были", "есть", "будет",
    "бывает", "можно", "нужно", "надо", "хотел", "хочет", "могут",
    # вопросительные
    "что", "где", "кто", "как", "зачем", "почему", "куда", "откуда",
    # обращения / типичный мусор посевов
    "ваши", "ответы", "смешные", "предположения", "подписчики", "друзья",
    "читатели", "только", "просто", "очень", "сеть", "сети",
}


@dataclass
class ParsedPost:
    platform: str   # "tg" | "vk"
    url: str
    text: str
    timestamp: int  # unix


async def parse_tg_link(url: str) -> Optional[ParsedPost]:
    m = TG_URL_RE.search(url)
    if not m:
        return None
    channel, post_id = m.group(1), m.group(2)
    preview_url = f"https://t.me/{channel}/{post_id}?embed=1&mode=tme"
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            r = await client.get(preview_url, headers={"User-Agent": "Mozilla/5.0"})
            html = r.text

        text_m = re.search(
            r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
            html, re.S
        )
        text = ""
        if text_m:
            raw = text_m.group(1)
            text = re.sub(r"<[^>]+>", " ", raw)
            text = re.sub(r"\s+", " ", text).strip()

        dt_m = re.search(r'datetime="([^"]+)"', html)
        ts = 0
        if dt_m:
            from datetime import datetime
            try:
                dt = datetime.fromisoformat(dt_m.group(1).replace("Z", "+00:00"))
                ts = int(dt.timestamp())
            except Exception:
                pass

        if not text and not ts:
            return None

        logger.info("TG parsed %s: ts=%d text=%r", url, ts, text[:80])
        return ParsedPost(platform="tg", url=url, text=text, timestamp=ts)

    except Exception as e:
        logger.error("TG parse error %s: %s", url, e)
        return None


async def parse_vk_link(url: str) -> Optional[ParsedPost]:
    vk_token = os.getenv("VK_TOKEN", "").strip()
    if not vk_token:
        raise RuntimeError("VK_TOKEN is not set")

    m = VK_URL_RE.search(url) or VK_SHORT_URL_RE.search(url)
    if not m:
        return None
    owner_id, post_id = m.group(1), m.group(2)

    params = {
        "posts": f"{owner_id}_{post_id}",
        "v": "5.199",
        "access_token": vk_token,
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get("https://api.vk.com/method/wall.getById", params=params)
            data = r.json()

        if "error" in data:
            logger.error("VK API error parsing %s: %s", url, data["error"])
            return None

        items = data.get("response", {}).get("items") or data.get("response", [])
        if not items:
            return None

        post = items[0]
        text = post.get("text", "")
        ts = post.get("date", 0)
        logger.info("VK parsed %s: ts=%d text=%r", url, ts, text[:80])
        return ParsedPost(platform="vk", url=url, text=text, timestamp=ts)

    except Exception as e:
        logger.error("VK parse error %s: %s", url, e)
        return None


async def parse_link(url: str) -> Optional[ParsedPost]:
    if "t.me" in url:
        return await parse_tg_link(url)
    if "vk.com" in url or "vk.ru" in url:
        return await parse_vk_link(url)
    return None


def _clean_text(text: str) -> str:
    """Убирает ссылки, эмодзи, лишние пробелы. Сохраняет оригинальный порядок слов."""
    text = re.sub(r"https?://\S+", "", text)
    # убираем эмодзи через диапазон Unicode
    text = re.sub(r"[\U00010000-\U0010ffff]", "", text)
    # убираем спецсимволы кроме букв, цифр, пробелов, дефиса, точки
    text = re.sub(r"[^\w\s\-\.]", " ", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _token_words(text: str) -> list[str]:
    """Токенизирует текст в слова, сохраняя оригинальный регистр и порядок."""
    clean = _clean_text(text)
    # берём только слова из букв (без цифр, знаков)
    return re.findall(r"[а-яёА-ЯЁa-zA-Z]+", clean)


def extract_seeds_from_posts(texts: list[str]) -> list[str]:
    """
    Извлекает поисковые фразы — скользящие окна 4 слов из оригинального текста.

    Органика чаще всего является дословным копипастом посева, поэтому:
    - сохраняем оригинальный порядок и регистр слов
    - берём окна по 4 слова (достаточно уникально, не слишком длинно)
    - пропускаем окна где есть стоп-слова (служебные, вопросительные и т.д.)
    - приоритет фразам которые встречаются в нескольких посевах
    """
    if not texts:
        return []

    from collections import Counter
    phrase_count: Counter = Counter()
    all_phrases: list[str] = []

    for text in texts:
        words = _token_words(text)
        seen_in_this_text: set[str] = set()

        for size in (4, 3):  # сначала 4 слова, потом 3
            for i in range(len(words) - size + 1):
                window = words[i:i + size]
                # пропускаем если первое, последнее или более 1 слова в окне — стоп-слово
                stop_count = sum(1 for w in window if w.lower() in _STOPWORDS)
                if window[0].lower() in _STOPWORDS or window[-1].lower() in _STOPWORDS or stop_count > 1:
                    continue
                phrase = " ".join(window)
                if phrase not in seen_in_this_text:
                    seen_in_this_text.add(phrase)
                    phrase_count[phrase] += 1
                    all_phrases.append(phrase)

    if not phrase_count:
        return []

    # Сортируем: сначала те что встречаются в нескольких посевах, потом длиннее
    def _score(phrase: str) -> tuple:
        return (phrase_count[phrase], len(phrase.split()))

    # Дедуп с сохранением порядка важности
    seen: set[str] = set()
    chosen: list[str] = []
    for phrase in sorted(set(all_phrases), key=_score, reverse=True):
        if phrase in seen:
            continue
        # не берём если эта фраза — подстрока уже выбранной
        if any(phrase in ch for ch in chosen):
            continue
        seen.add(phrase)
        chosen.append(phrase)
        if len(chosen) >= 6:
            break

    return chosen
