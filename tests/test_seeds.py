"""
Извлечение поисковых фраз. Реальный ввод из отладочного прогона: пользователь
вставляет кусок текста поста, а не выверенную фразу.
"""
from bot.services.link_parser import (
    _clean_for_sentences,
    extract_manual_seeds,
    extract_seeds_from_posts,
)

PASTED = "🔮Таинственная пирамида выросла посреди Москва Сити. Ваши предположения, что там? Только смешные ответы"


def test_pasted_block_is_split_into_sentences():
    seeds = extract_manual_seeds(PASTED)
    assert "Таинственная пирамида выросла посреди Москва Сити" in seeds
    # склейка из трёх предложений дословно почти никогда не совпадёт
    assert PASTED not in seeds


def test_call_to_action_dropped_from_manual_input():
    seeds = extract_manual_seeds(PASTED)
    assert not any(s.lower().startswith(("ваши", "только")) for s in seeds)


def test_manual_keeps_short_deliberate_phrase():
    # для посевов порог 20 символов, для ручного ввода ниже
    assert extract_manual_seeds("пирамида в Сити") == ["пирамида в Сити"]
    assert extract_seeds_from_posts(["пирамида в Сити"]) == []


def test_clean_strips_emoji_outside_the_f300_block():
    assert _clean_for_sentences("⚡️Москвичи получили пирамиду 🔮") == "Москвичи получили пирамиду"


def test_urls_removed_before_splitting():
    assert "t.me" not in " ".join(extract_manual_seeds("Пирамида в Сити https://t.me/x/1 стала мемом"))
