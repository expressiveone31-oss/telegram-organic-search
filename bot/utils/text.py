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
# Невидимые склейки эмодзи: селекторы вариации и zero-width joiner
_INVISIBLE = frozenset({"\ufe0f", "\ufe0e", "\u200d"})


def strip_emoji(s: str) -> str:
    """Убирает эмодзи и пиктограммы: категория So покрывает и ⚡ (U+26A1), и 🔮."""
    return "".join(
        ch for ch in s
        if ch not in _INVISIBLE and unicodedata.category(ch) != "So"
    )


def normalize_for_match(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = _QUOTES_RE.sub("", s)
    s = strip_emoji(s)
    s = s.replace("ё", "е")
    return _SPACES_RE.sub(" ", s).strip()


def contains_phrase(needle: str, haystack: str) -> bool:
    return normalize_for_match(needle) in normalize_for_match(haystack)
