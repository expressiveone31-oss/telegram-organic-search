"""
Проблемы, видимые в карточках бота: эмодзи ломали поиск репостов,
ссылки вели на протухший joinchat, дата печаталась сырым таймстампом.
"""
from bot.services.telemetr_search import _contains_seed, _link_of, _post_id_of
from bot.utils.formatting import _fmt_date, fmt_tg_card

SEED = "⚡Москвичи, кажется, получили собственную пирамиду в честь дня города в Сити"
REPOST_NO_EMOJI = (
    "Москвичи, кажется, получили собственную пирамиду в честь дня города в Сити. "
    "Неожиданно возникшая постройка уже разлетелась на мемы 😂"
)


def test_repost_without_leading_emoji_still_matches():
    assert _contains_seed(SEED, REPOST_NO_EMOJI)


def test_emoji_inside_text_ignored_both_ways():
    assert _contains_seed("Лувр ✅ с AliExpress", "копия: Лувр с AliExpress уже стоит")
    assert _contains_seed("Лувр с AliExpress", "копия: ➖Лувр ❤️ с AliExpress уже стоит")


# Реальный элемент ответа Telemetr: ни вложенного channel, ни просмотров,
# ссылка без схемы, id канала в корне.
REAL_ITEM = {
    "id": 940,
    "date": 1788429915,
    "link": "t.me/volobuev/940",
    "channel_id": 1105810677,
    "is_forwarded": 0,
    "is_deleted": 0,
    "text": "Нам, конечно, недостаточно такого уровня рождаемости",
}


def test_scheme_added_to_bare_link():
    assert _link_of(REAL_ITEM) == "https://t.me/volobuev/940"


def test_public_channel_link_rebuilt_from_channels_index():
    it = {"link": "t.me/joinchat/AYs2WTVN3MY0Yjly/6093", "channel_id": 777}
    channels = {"777": {"id": 777, "username": "moya_moskva"}}
    assert _link_of(it, channels) == "https://t.me/moya_moskva/6093"


def test_private_channel_falls_back_to_internal_link():
    it = {"link": "t.me/joinchat/AYs2WTVN3MY0Yjly/6093", "channel_id": 1105810677}
    assert _link_of(it) == "https://t.me/c/1105810677/6093"


def test_internal_id_strips_minus_100_prefix():
    it = {"link": "t.me/joinchat/hash/6093", "channel_id": -1001105810677}
    assert _link_of(it) == "https://t.me/c/1105810677/6093"


def test_normal_public_link_left_alone():
    it = {"link": "https://t.me/moya_moskva/6093", "channel_id": 1}
    assert _link_of(it) == "https://t.me/moya_moskva/6093"


def test_card_falls_back_to_username_when_channel_unknown():
    card = fmt_tg_card({
        "date": 1788429915,
        "_link": "https://t.me/volobuev/940",
        "_username": "volobuev",
        "text": "текст",
    })
    assert "@volobuev" in card


def test_card_hides_views_when_api_gives_none():
    card = fmt_tg_card({"date": 1788429915, "_link": "https://t.me/x/1", "text": "текст"})
    assert "👀" not in card


def test_post_id_recovered_from_joinchat_tail():
    assert _post_id_of({"url": "https://t.me/joinchat/AYs2WTVN3MY0Yjly/6093"}) == "6093"


def test_date_rendered_from_unix_timestamp():
    assert _fmt_date(1788809518) == "2026-09-07 19:31"
    assert _fmt_date("1788809518") == "2026-09-07 19:31"


def test_date_rendered_from_iso_string():
    assert _fmt_date("2026-09-07T19:31:58Z") == "2026-09-07 19:31"


def test_card_shows_views_resolved_by_search():
    card = fmt_tg_card({
        "channel": {"title": "Моя Москва"},
        "date": 1788809518,
        "_views": 12345,
        "text": "текст поста",
        "_link": "https://t.me/moya_moskva/6093",
    })
    assert "12,345" in card
    assert "1788809518" not in card
