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


def test_public_channel_link_rebuilt_from_username():
    it = {
        "url": "https://t.me/joinchat/AYs2WTVN3MY0Yjly/6093",
        "channel": {"username": "moya_moskva"},
    }
    assert _link_of(it) == "https://t.me/moya_moskva/6093"


def test_private_channel_falls_back_to_internal_link():
    it = {
        "url": "https://t.me/joinchat/AYs2WTVN3MY0Yjly/6093",
        "channel": {"id": -1001234567890},
    }
    assert _link_of(it) == "https://t.me/c/1234567890/6093"


def test_normal_public_link_left_alone():
    it = {"url": "https://t.me/moya_moskva/6093", "channel": {"username": "other"}}
    assert _link_of(it) == "https://t.me/moya_moskva/6093"


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
