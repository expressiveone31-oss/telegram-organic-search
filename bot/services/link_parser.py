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
    """Убирает ссылки, спецсимволы, эмодзи, лишние пробелы."""
    text = re.sub(r"https?://\S+", "", text)
    # убираем эмодзи и спецсимволы (всё что не буква/цифр/пробел/дефис)
    text = re.sub(r"[^\w\s\-]", " ", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _words_from_text(text: str) -> list[str]:
    """Слова 4+ букв, не стоп-слова."""
    return [
        w.lower()
        for w in re.findall(r"[а-яёА-ЯЁa-zA-Z]{4,}", _clean_text(text))
        if w.lower() not in _STOPWORDS
    ]


def extract_seeds_from_posts(texts: list[str]) -> list[str]:
    """
    Извлекает поисковые фразы из текстов посевов.

    Стратегия:
    1. Из каждого текста берём окна 3-4 значимых слова (триграммы и квадраграммы)
    2. Приоритет — фразы чьи слова встречаются в НЕСКОЛЬКИХ посевах
       (это и есть общая тема, а не уникальная формулировка одного поста)
    3. Отсекаем фразы где есть слово короче 4 букв — значит туда попало
       служебное слово
    """
    if not texts:
        return []

    # Слова из каждого текста
    per_text: list[list[str]] = [_words_from_text(t) for t in texts]

    # Частота слов по всем текстам (в скольких текстах встречается)
    from collections import Counter
    word_doc_freq: Counter = Counter()
    for words in per_text:
        for w in set(words):
            word_doc_freq[w] += 1

    seeds: list[str] = []

    for words in per_text:
        # Только триграммы — квадраграммы слишком часто захватывают случайные слова
        for size in (3,):
            for i in range(len(words) - size + 1):
                phrase_words = words[i:i + size]
                # Все слова должны быть 4+ букв (стоп-слова уже отфильтрованы,
                # но могут проскочить короткие нейтральные)
                if any(len(w) < 4 for w in phrase_words):
                    continue
                phrase = " ".join(phrase_words)
                seeds.append((phrase, phrase_words))

    if not seeds:
        return []

    # Сортируем: сначала фразы где больше слов встречается в нескольких текстах
    def _score(item: tuple) -> float:
        phrase, words = item
        if len(texts) == 1:
            return float(len(words))
        cross_text_score = sum(word_doc_freq[w] for w in words)
        return float(cross_text_score * len(words))

    seeds.sort(key=_score, reverse=True)

    # Дедупликация: не берём фразу если она подстрока уже выбранной
    chosen: list[str] = []
    chosen_set: set[str] = set()
    for phrase, _ in seeds:
        if phrase in chosen_set:
            continue
        # не добавляем если эта фраза уже содержится в более длинной выбранной
        already_covered = any(phrase in ch for ch in chosen)
        if not already_covered:
            chosen.append(phrase)
            chosen_set.add(phrase)
        if len(chosen) >= 6:
            break

    return chosen
