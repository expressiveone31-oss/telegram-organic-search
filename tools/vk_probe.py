#!/usr/bin/env python3
"""
Зонд для VK-поиска: почему конкретный пост не находится.

Берёт ссылку на пост, который точно существует, читает его текст через
wall.getById, а затем пробует найти его же через newsfeed.search разными
запросами — от целой фразы до пары слов, с временным окном и без него.
Дополнительно проверяет wall.search по стене того же сообщества.

Так видно, где теряется пост: наш запрос слишком длинный, мешает окно дат
или newsfeed.search просто не покрывает это сообщество.

    export VK_TOKEN=...
    python tools/vk_probe.py https://vk.ru/wall-47636806_151669
"""
from __future__ import annotations

import os
import re
import sys
import time
from typing import Any, Dict, List

import httpx

VK_API = "https://api.vk.com/method"
VERSION = "5.199"

URL_RE = re.compile(r"wall(-?\d+)_(\d+)")


def call(client: httpx.Client, method: str, **params: Any) -> Any:
    r = client.get(
        f"{VK_API}/{method}",
        params={"v": VERSION, "access_token": TOKEN, **params},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        err = data["error"]
        raise RuntimeError(f"{method}: error {err.get('error_code')} {err.get('error_msg')}")
    return data["response"]


def queries_from(text: str) -> List[tuple[str, str]]:
    """Варианты запросов от самого длинного к самому короткому."""
    first = re.split(r"[.!?\n]+", text.strip())
    first = next((s.strip() for s in first if len(s.strip()) >= 20), text.strip())
    words = first.split()
    out = [("целое предложение", first)]
    for n in (10, 8, 6, 4, 3, 2):
        if len(words) > n:
            out.append((f"первые {n} слов", " ".join(words[:n])))
    return out


def found(items: List[Dict[str, Any]], owner_id: int, post_id: int) -> bool:
    return any(
        int(it.get("owner_id", 0)) == owner_id and int(it.get("id", 0)) == post_id
        for it in items
    )


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2

    m = URL_RE.search(sys.argv[1])
    if not m:
        print("Не похоже на ссылку вида vk.com/wall-123_456")
        return 2
    owner_id, post_id = int(m.group(1)), int(m.group(2))

    with httpx.Client() as client:
        resp = call(client, "wall.getById", posts=f"{owner_id}_{post_id}")
        items = resp.get("items") if isinstance(resp, dict) else resp
        if not items:
            print("wall.getById ничего не вернул: пост удалён или недоступен по токену")
            return 1

        post = items[0]
        text = post.get("text") or ""
        if not text and post.get("copy_history"):
            text = post["copy_history"][0].get("text") or ""
        date = int(post.get("date") or 0)

        print(f"Пост:  vk.com/wall{owner_id}_{post_id}")
        print(f"Дата:  {time.strftime('%Y-%m-%d %H:%M', time.gmtime(date))} UTC")
        print(f"Текст: {text[:300]!r}")
        print(f"Репост: {'да' if post.get('copy_history') else 'нет'}")
        print()

        if not text:
            print("У поста нет текста — искать его по фразе нечем.")
            return 1

        # Окно с запасом в сутки вокруг даты поста
        start_time, end_time = date - 86400, date + 86400

        print(f"{'запрос':<22} {'длина':>5}  {'с окном дат':<14} {'без окна':<14}")
        print("-" * 62)
        for label, q in queries_from(text):
            row = [label, str(len(q))]
            for use_window in (True, False):
                params: Dict[str, Any] = {"q": q, "count": 200}
                if use_window:
                    params.update(start_time=start_time, end_time=end_time)
                try:
                    res = call(client, "newsfeed.search", **params)
                    got = res.get("items", [])
                    hit = "НАЙДЕН" if found(got, owner_id, post_id) else "нет"
                    row.append(f"{hit} ({len(got)})")
                except Exception as e:
                    row.append(f"ошибка: {e}"[:14])
            print(f"{row[0]:<22} {row[1]:>5}  {row[2]:<14} {row[3]:<14}")

        print()
        # Поиск по стене самого сообщества: покрытие newsfeed.search vs wall.search
        label, q = queries_from(text)[0]
        try:
            res = call(client, "wall.search", owner_id=owner_id, query=q, count=100)
            got = res.get("items", [])
            print(f"wall.search по стене сообщества: "
                  f"{'НАЙДЕН' if found(got, owner_id, post_id) else 'нет'} ({len(got)} записей)")
        except Exception as e:
            print(f"wall.search: {e}")

    return 0


TOKEN = os.getenv("VK_TOKEN", "").strip()
if not TOKEN:
    print("Нужен VK_TOKEN в переменных окружения")
    raise SystemExit(2)

if __name__ == "__main__":
    raise SystemExit(main())
