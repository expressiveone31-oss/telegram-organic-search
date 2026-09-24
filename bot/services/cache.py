"""
Кэш сырых ответов поисковых API в памяти процесса.

Кладём то, что вернул API, до фильтрации — тогда правка порогов отсева
(min_views и т.п.) не требует новых запросов к API.

Память живёт до рестарта, а Railway передеплоивает на каждый пуш. Этого хватает
для повторных прогонов одного посева; переживающий деплой кэш — это том с SQLite.
"""
from __future__ import annotations

import logging
import os
import time
from collections import OrderedDict
from typing import Any, Optional, Tuple

logger = logging.getLogger(__name__)

_store: "OrderedDict[str, Tuple[float, Any]]" = OrderedDict()
_hits = 0
_misses = 0


def _ttl() -> int:
    return int(os.getenv("CACHE_TTL_SECONDS", "3600") or 0)


def _max_entries() -> int:
    return max(1, int(os.getenv("CACHE_MAX_ENTRIES", "500") or 500))


def make_key(*parts: Any) -> str:
    return "|".join(str(p) for p in parts)


def get(key: str) -> Optional[Any]:
    global _hits, _misses
    ttl = _ttl()
    if ttl <= 0:
        return None

    entry = _store.get(key)
    if entry is None:
        _misses += 1
        return None

    stored_at, value = entry
    if time.time() - stored_at > ttl:
        _store.pop(key, None)
        _misses += 1
        return None

    _store.move_to_end(key)
    _hits += 1
    return value


def set(key: str, value: Any) -> None:
    if _ttl() <= 0:
        return
    _store[key] = (time.time(), value)
    _store.move_to_end(key)
    while len(_store) > _max_entries():
        _store.popitem(last=False)


def stats() -> str:
    return f"cache hit={_hits} miss={_misses} size={len(_store)}"


def clear() -> None:
    global _hits, _misses
    _store.clear()
    _hits = 0
    _misses = 0
