"""
Кэш и ранняя остановка постраничного обхода: считаем реальные обращения к API.
"""
import asyncio

import pytest

from bot.services import cache, telemetr_search

SEED = "Сейчас возводим путепровод над Шмитовским проездом"
ORGANIC = f"Развиваем сеть у Москва-Сити. {SEED} длиной больше 50 метров."
NOISE = "НОЧЬ В ДЖУНГЛЯХ: Москва-Сити превратится в джунгли."


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    cache.clear()
    monkeypatch.setenv("TELEMETR_TOKEN", "test-token")
    monkeypatch.setenv("TELEMETR_PAGES", "5")
    monkeypatch.setenv("TELEMETR_MIN_VIEWS", "0")
    monkeypatch.setenv("CACHE_TTL_SECONDS", "3600")


def _stub_pages(monkeypatch, pages):
    """Подменяет сетевой слой; возвращает список фактически запрошенных страниц."""
    requested = []

    async def fake_fetch(client, token, query, since, until, page):
        requested.append(page)
        return pages.get(page, [])

    monkeypatch.setattr(telemetr_search, "_fetch_page", fake_fetch)
    return requested


def _full_page(text):
    return [{"text": text, "stats": {"views": 1000}, "url": f"u{i}"} for i in range(50)]


def test_second_identical_search_makes_no_requests(monkeypatch):
    requested = _stub_pages(monkeypatch, {1: _full_page(ORGANIC), 2: _full_page(ORGANIC)})

    first, _ = asyncio.run(telemetr_search.search_telemetr([SEED], 0, 86400))
    calls_after_first = len(requested)
    second, _ = asyncio.run(telemetr_search.search_telemetr([SEED], 0, 86400))

    assert calls_after_first > 0
    assert len(requested) == calls_after_first, "второй поиск не должен ходить в API"
    assert len(second) == len(first)


def test_pagination_stops_when_page_has_no_exact_hits(monkeypatch):
    # первая страница — сплошной шум, дальше листать незачем
    requested = _stub_pages(monkeypatch, {p: _full_page(NOISE) for p in range(1, 6)})

    results, _ = asyncio.run(telemetr_search.search_telemetr([SEED], 0, 86400))

    assert results == []
    assert requested == [1], f"должна запрашиваться только 1 страница, а не {requested}"


def test_cache_disabled_by_zero_ttl(monkeypatch):
    monkeypatch.setenv("CACHE_TTL_SECONDS", "0")
    requested = _stub_pages(monkeypatch, {1: _full_page(ORGANIC)})

    asyncio.run(telemetr_search.search_telemetr([SEED], 0, 86400))
    calls_after_first = len(requested)
    asyncio.run(telemetr_search.search_telemetr([SEED], 0, 86400))

    assert len(requested) == calls_after_first * 2, "при TTL=0 кэш должен быть выключен"


def test_min_views_retuned_without_new_requests(monkeypatch):
    requested = _stub_pages(monkeypatch, {1: _full_page(ORGANIC)})

    loose, _ = asyncio.run(telemetr_search.search_telemetr([SEED], 0, 86400))
    calls = len(requested)

    monkeypatch.setenv("TELEMETR_MIN_VIEWS", "5000")
    strict, _ = asyncio.run(telemetr_search.search_telemetr([SEED], 0, 86400))

    assert len(requested) == calls, "смена порога не должна дёргать API"
    assert loose and not strict
