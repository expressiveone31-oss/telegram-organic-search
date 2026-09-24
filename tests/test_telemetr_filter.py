"""
Фильтр точного вхождения фразы: органика проходит, тематический мусор — нет.
Реальные примеры из выдачи Telemetr по посеву про путепровод у Москва-Сити.
"""
from bot.services.telemetr_search import _body_of, _contains_seed, _normalize

SEED = "Сейчас возводим путепровод над Шмитовским проездом длиной больше 50 метров"

ORGANIC = (
    '🛣 Развиваем улично-дорожную сеть в районе делового центра "Москва-Сити". '
    "Сейчас возводим путепровод над Шмитовским проездом длиной больше 50 метров. "
    "Уже готовы две опоры и подпорные стены."
)
NOISE_EVENT = "🤩 НОЧЬ В ДЖУНГЛЯХ🤩 25 сентября. Этой ночью Москва-Сити превратится в джунгли."
NOISE_LOUVRE = "✅ Париж на минималках: у «Афимолла» в Москва-Сити вырос «Лувр с AliExpress»"


def test_organic_passes():
    assert _contains_seed(SEED, ORGANIC)


def test_noise_sharing_only_topic_is_rejected():
    assert not _contains_seed(SEED, NOISE_EVENT)
    assert not _contains_seed(SEED, NOISE_LOUVRE)


def test_normalize_ignores_quotes_case_and_yo():
    assert _normalize('«Ёлка»  Растёт') == "елка растет"


def test_quoted_seed_matches_unquoted_body():
    assert _contains_seed('"Москва-Сити"', "живу в Москва-Сити давно")


def test_body_read_from_any_known_key():
    for key in ("text", "title", "caption", "post_text", "message"):
        assert _body_of({key: ORGANIC}) == ORGANIC


def test_body_empty_for_unknown_key():
    # пустой body => пост отбрасывается вызывающим кодом, а не проходит насквозь
    assert _body_of({"unexpected_field": ORGANIC}) == ""
