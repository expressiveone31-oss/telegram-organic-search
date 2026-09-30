"""
Сравнение текстов при поиске органики.

Органика — дословный копипаст посева, но «дословный» в реальности означает
«с точностью до оформления»: регистра, кавычек, ё/е и эмодзи. Репост часто
отличается от посева только ведущим значком, поэтому при сравнении всё это
выбрасывается. Логика общая для Telegram и ВКонтакте: раньше у каждого была
своя копия, и правка в одной не доезжала до другой.
"""
from __future__ import annotations

import re
import unicodedata

_QUOTES_RE = re.compile(r"[«»„“”\"'`]")
_SPACES_RE = re.compile(r"\s+")
# Дефис, тире, пунктуация: «Москва Сити» должно совпасть с «Москва-Сити»
_PUNCT_RE = re.compile(r"[^\w]+", flags=re.UNICODE)
# Невидимые склейки эмодзи: селекторы вариации и zero-width joiner
_INVISIBLE = frozenset({"\ufe0f", "\ufe0e", "\u200d", "\u00ad"})


def strip_emoji(s: str) -> str:
    """Убирает эмодзи и пиктограммы: категория So покрывает и ⚡ (U+26A1), и 🔮."""
    return "".join(
        ch for ch in s
        if ch not in _INVISIBLE and unicodedata.category(ch) != "So"
    )


def normalize_for_match(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = strip_emoji(s)
    s = s.replace("ё", "е")
    s = _QUOTES_RE.sub(" ", s)
    s = _PUNCT_RE.sub(" ", s)
    return _SPACES_RE.sub(" ", s).strip()


def contains_phrase(needle: str, haystack: str) -> bool:
    return normalize_for_match(needle) in normalize_for_match(haystack)


def phrase_overlap(needle: str, haystack: str) -> float:
    """Доля значимых слов фразы, которые вообще есть в тексте. Для диагностики промахов."""
    words = [w for w in normalize_for_match(needle).split() if len(w) >= 4]
    if not words:
        return 0.0
    hay = set(normalize_for_match(haystack).split())
    return sum(1 for w in words if w in hay) / len(words)
