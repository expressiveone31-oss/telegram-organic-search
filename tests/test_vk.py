"""
Поиск во ВКонтакте: молчаливые отсевы и проглоченные ошибки API.
"""
import asyncio

import pytest

from bot.services import cache, vk_search

SEED = "Загадочная пирамида в Москва Сити стала героиней мемов"
ORGANIC = f"⚡️{SEED}. Горожане уже шутят про восьмое чудо света."


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    cache.clear()
    monkeypatch.setenv("VK_TOKEN", "test-token")
    monkeypatch.setenv("CACHE_TTL_SECONDS", "0")
    for key in ("VK_MIN_VIEWS", "VK_MAX_PAGES", "VK_STRICT", "ORGANIC_DEBUG"):
        monkeypatch.delenv(key, raising=False)


def _stub(monkeypatch, pages=None, error=None):
    async def fake_call(client, token, method, params):
        if error is not None:
            raise error
        return pages

    monkeypatch.setattr(vk_search, "_call", fake_call)


def _post(text, views=None, owner=-1, pid=1):
    it = {"text": text, "date": 1788809518, "owner_id": owner, "id": pid}
    if views is not None:
        it["views"] = {"count": views}
    return it


def test_emoji_does_not_break_matching(monkeypatch):
    _stub(monkeypatch, {"items": [_post(ORGANIC)], "next_from": None})
    results, _ = asyncio.run(vk_search.search_vk([SEED], 0, 99999999999))
    assert len(results) == 1


def test_posts_without_view_counter_are_kept(monkeypatch):
    # у записей из личных профилей счётчика просмотров нет вовсе
    _stub(monkeypatch, {"items": [_post(ORGANIC, views=None)], "next_from": None})
    results, _ = asyncio.run(vk_search.search_vk([SEED], 0, 99999999999))
    assert len(results) == 1, "нулевой порог просмотров не должен их отсеивать"


def test_api_error_is_not_hidden_behind_empty_result(monkeypatch):
    _stub(monkeypatch, error=vk_search.VkApiError(15, "Access denied"))
    with pytest.raises(vk_search.VkApiError):
        asyncio.run(vk_search.search_vk([SEED], 0, 99999999999))


def test_token_error_explains_user_token_requirement():
    assert "пользовательским" in str(vk_search.VkApiError(5, "auth failed"))


def test_same_post_matched_by_two_seeds_returned_once(monkeypatch):
    other = "Горожане уже шутят про восьмое чудо света"
    _stub(monkeypatch, {"items": [_post(ORGANIC)], "next_from": None})
    results, _ = asyncio.run(vk_search.search_vk([SEED, other], 0, 99999999999))
    assert len(results) == 1


def test_repost_text_read_from_copy_history(monkeypatch):
    # у репоста собственный text пустой, оригинал лежит в copy_history
    repost = {"text": "", "date": 1788809518, "owner_id": -2, "id": 7,
              "copy_history": [{"text": ORGANIC}]}
    _stub(monkeypatch, {"items": [repost], "next_from": None})
    results, _ = asyncio.run(vk_search.search_vk([SEED], 0, 99999999999))
    assert len(results) == 1, "репост органики должен находиться"


def test_text_read_from_attachment_caption(monkeypatch):
    post = {"text": "", "date": 1788809518, "owner_id": -3, "id": 8,
            "attachments": [{"type": "link", "link": {"title": ORGANIC}}]}
    _stub(monkeypatch, {"items": [post], "next_from": None})
    results, _ = asyncio.run(vk_search.search_vk([SEED], 0, 99999999999))
    assert len(results) == 1


def test_diagnostics_separate_no_text_from_no_match(monkeypatch):
    posts = [
        {"text": "", "date": 1, "owner_id": -4, "id": 9},
        {"text": "совсем другая новость", "date": 1, "owner_id": -4, "id": 10},
    ]
    _stub(monkeypatch, {"items": posts, "next_from": None})
    _, diag = asyncio.run(vk_search.search_vk([SEED], 0, 99999999999))
    assert "no_text=1" in diag
    assert "no_match=1" in diag


def test_debug_sample_drops_attachment_noise(monkeypatch):
    monkeypatch.setenv("ORGANIC_DEBUG", "1")
    post = {"text": ORGANIC, "date": 1, "owner_id": -5, "id": 11,
            "attachments": [{"type": "photo", "photo": {"sizes": [{"url": "x" * 3000}]}}]}
    _stub(monkeypatch, {"items": [post], "next_from": None})
    _, diag = asyncio.run(vk_search.search_vk([SEED], 0, 99999999999))
    assert "userapi" not in diag and "xxxx" not in diag
    assert '"attachments": ["photo"]' in diag


def test_hyphenated_city_name_matches_seed_with_space(monkeypatch):
    seed = "Стеклянная пирамида выросла посреди Москва Сити"
    post = _post("Стеклянная пирамида выросла посреди Москва-Сити. Горожане шутят.")
    _stub(monkeypatch, {"items": [post], "next_from": None})
    results, _ = asyncio.run(vk_search.search_vk([seed], 0, 99999999999))
    assert len(results) == 1


def test_closest_miss_shown_when_nothing_matched(monkeypatch):
    _stub(monkeypatch, {"items": [_post("Прогулка к величественной пирамиде в Москва-Сити")], "next_from": None})
    _, diag = asyncio.run(vk_search.search_vk([SEED], 0, 99999999999))
    assert "Ближайшие промахи" in diag


def test_noise_is_still_rejected(monkeypatch):
    _stub(monkeypatch, {"items": [_post("НОЧЬ В ДЖУНГЛЯХ в Москва-Сити")], "next_from": None})
    results, _ = asyncio.run(vk_search.search_vk([SEED], 0, 99999999999))
    assert results == []


def test_long_seed_becomes_a_short_and_window():
    # newsfeed.search AND'ит все слова: 8-словная фраза в диагностике давала 0/0
    qs = vk_search.queries_for_seed(SEED)
    assert qs[0] != SEED
    assert len(qs[0].split()) == 5
    assert SEED in qs


def test_falls_back_when_full_phrase_returns_nothing(monkeypatch):
    async def fake_call(client, token, method, params):
        q = params["q"]
        if q == SEED:
            return {"items": [], "next_from": None}
        return {"items": [_post(ORGANIC)], "next_from": None}

    monkeypatch.setattr(vk_search, "_call", fake_call)
    results, _ = asyncio.run(vk_search.search_vk([SEED], 0, 99999999999))
    assert len(results) == 1


def test_typographic_quotes_stripped_from_query():
    qs = vk_search.queries_for_seed("В такую «эчпочмачную» мы бы сходили")
    assert all("«" not in q and "»" not in q for q in qs)


def test_wall_search_finds_post_newsfeed_misses(monkeypatch):
    methods = []

    async def fake_call(client, token, method, params):
        methods.append(method)
        if method == "wall.search":
            return {"items": [_post(ORGANIC, owner=-47636806, pid=151669)]}
        return {"items": [], "next_from": None}

    monkeypatch.setattr(vk_search, "_call", fake_call)
    results, diag = asyncio.run(
        vk_search.search_vk([SEED], 0, 99999999999, owners=[-47636806])
    )
    assert "wall.search" in methods
    assert len(results) == 1
    assert "walls=1" in diag
    assert "151669" in results[0]["url"]
