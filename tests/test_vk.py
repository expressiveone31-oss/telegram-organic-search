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


def test_noise_is_still_rejected(monkeypatch):
    _stub(monkeypatch, {"items": [_post("НОЧЬ В ДЖУНГЛЯХ в Москва-Сити")], "next_from": None})
    results, _ = asyncio.run(vk_search.search_vk([SEED], 0, 99999999999))
    assert results == []
