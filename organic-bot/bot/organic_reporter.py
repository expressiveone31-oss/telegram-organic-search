from __future__ import annotations
import os
import time
from dataclasses import dataclass
from typing import List, Dict, Iterable, Tuple, Optional

# --- Core data model ---------------------------------------------------------

@dataclass
class PostHit:
    platform: str            # 'vk' | 'tg'
    url: str
    published_at: int        # unix ts (UTC)
    reach: Optional[int]     # views/просмотры; None if неизвестно
    matched_phrases: List[str]

# --- N-gram generator from seed texts ---------------------------------------

RU_STOP = {
    "и","а","но","что","как","к","на","в","во","за","от","по","не","из","до","для","или","же","то","у","о","об","с","со","над","под","без","при","ли","бы","же","ну"
}

def tokenize(text: str) -> List[str]:
    return [t.strip(".,!?:;()[]{}<>\"'«»—–-") for t in text.lower().split()]  # простейший токенайзер

def build_phrases(seed_texts: Iterable[str], n_min: int = 4, n_max: int = 8) -> List[str]:
    seen = set()
    phrases: List[str] = []
    for seed in seed_texts:
        toks = [t for t in tokenize(seed) if t and t not in RU_STOP]
        for n in range(n_max, n_min - 1, -1):
            for i in range(0, max(0, len(toks) - n + 1)):
                frag = " ".join(toks[i:i+n])
                if len(frag) >= 20 and frag not in seen:  # отсекаем слишком короткое
                    seen.add(frag)
                    phrases.append(f'"{frag}"')  # точный поиск в кавычках
    # Добавим собственные якоря (одно-двухсловные), если встречаются
    anchors = set()
    for seed in seed_texts:
        for kw in ("кибердеревня","робогозин","кибер деревня","cybervillage"):
            if kw in seed.lower():
                anchors.add(kw)
    phrases.extend(sorted(anchors))
    return phrases[:200]  # защитимся от взрыва запросов

# --- VK adapter (API) --------------------------------------------------------

import httpx

class VKClient:
    def __init__(self, token: str, v: str = "5.199"):
        self.token = token
        self.v = v
        self.client = httpx.Client(timeout=30)

    def _get(self, method: str, **params):
        params.update({"access_token": self.token, "v": self.v})
        r = self.client.get(f"https://api.vk.com/method/{method}", params=params)
        r.raise_for_status()
        data = r.json()
        if "error" in data:
            raise RuntimeError(f"VK API error {data['error']}")
        return data["response"]

    def search_posts(self, query: str, start_time: int, end_time: int, count: int = 200) -> List[Dict]:
        # newsfeed.search даёт смешанную ленту, но подходит для фраз
        resp = self._get(
            "newsfeed.search",
            q=query,
            count=min(200, count),
            extended=0,
            start_time=start_time,
            end_time=end_time,
        )
        return resp.get("items", [])

    def get_reach_and_url(self, item: Dict) -> Tuple[Optional[int], str]:
        owner_id = item.get("owner_id")
        post_id = item.get("id")
        views = None
        if isinstance(item.get("views"), dict):
            views = item["views"].get("count")
        # Сформируем URL
        if owner_id and post_id:
            url = f"https://vk.com/wall{owner_id}_{post_id}"
        else:
            url = ""
        return views, url

# --- TGStat adapter (API) ----------------------------------------------------

class TGStatClient:
    """Мини-обёртка. Нужен токен TGStat API. Конкретный эндпоинт и поля — у их API,
    но тут делаем безопасную обобщённую обёртку, возвращающую link + views."""
    def __init__(self, token: str):
        self.token = token
        self.client = httpx.Client(timeout=30)

    def search_posts(self, query: str, start_time: int, end_time: int, limit: int = 100) -> List[Dict]:
        # Документация TGStat может отличаться версией. Типичный формат: GET /posts/search?token=...&q=...&startDate=...&endDate=...
        # Мы нормализуем возможные параметры. При необходимости подстройте под вашу версию API.
        params = {
            "token": self.token,
            "q": query,
            "startDate": start_time,
            "endDate": end_time,
            "limit": min(100, limit),
        }
        r = self.client.get("https://api.tgstat.ru/posts/search", params=params)
        r.raise_for_status()
        data = r.json()
        if data.get("status") != "ok":
            raise RuntimeError(f"TGStat API error: {data}")
        # Нормализуем к списку
        items = data.get("response", {}).get("items", [])
        return items

    @staticmethod
    def normalize_item(item: Dict) -> Tuple[Optional[int], str]:
        # TGStat обычно возвращает поля channel, link, views, date
        link = item.get("link") or item.get("url") or ""
        views = item.get("views")
        return views, link

# --- Search orchestration ----------------------------------------------------

def search_vk_and_tg(
    seed_texts: Iterable[str],
    start_time: int,
    end_time: int,
    vk_token: Optional[str] = None,
    tgstat_token: Optional[str] = None,
    max_queries_per_source: int = 80,
    sleep_between: float = 0.35,
) -> List[PostHit]:
    phrases = build_phrases(seed_texts)

    results: List[PostHit] = []

    if vk_token:
        vk = VKClient(vk_token)
        n = 0
        for q in phrases:
            if n >= max_queries_per_source:
                break
            try:
                items = vk.search_posts(q, start_time, end_time)
                for it in items:
                    views, url = vk.get_reach_and_url(it)
                    if not url:
                        continue
                    results.append(PostHit(
                        platform="vk",
                        url=url,
                        published_at=it.get("date", 0),
                        reach=views,
                        matched_phrases=[q],
                    ))
            except Exception as e:
                # логируем и продолжаем
                print("VK error:", e)
            n += 1
            time.sleep(sleep_between)

    if tgstat_token:
        tg = TGStatClient(tgstat_token)
        n = 0
        for q in phrases:
            if n >= max_queries_per_source:
                break
            try:
                items = tg.search_posts(q, start_time, end_time)
                for it in items:
                    views, link = tg.normalize_item(it)
                    if not link:
                        continue
                    results.append(PostHit(
                        platform="tg",
                        url=link,
                        published_at=it.get("date") or it.get("timestamp") or 0,
                        reach=views,
                        matched_phrases=[q],
                    ))
            except Exception as e:
                print("TGStat error:", e)
            n += 1
            time.sleep(sleep_between)

    # Дедуп по ссылке
    uniq: Dict[str, PostHit] = {}
    for r in results:
        key = r.url
        if key not in uniq:
            uniq[key] = r
        else:
            # держим запись с бОльшим reach и объединяем фразы
            if (r.reach or -1) > (uniq[key].reach or -1):
                r.matched_phrases = list({*uniq[key].matched_phrases, *r.matched_phrases})
                uniq[key] = r
            else:
                uniq[key].matched_phrases = list({*uniq[key].matched_phrases, *r.matched_phrases})

    # Отсортируем: по reach desc, затем по дате
    final = sorted(uniq.values(), key=lambda x: ((x.reach or -1), x.published_at), reverse=True)
    return final

# --- Telegram message rendering ---------------------------------------------

def format_number(n: Optional[int]) -> str:
    if n is None:
        return "—"
    s = f"{n:,}".replace(",", " ")
    return s

def render_message(results: List[PostHit], title: str, period_text: str, limit: int = 120) -> str:
    """
    Возвращает один текст для отправки в Telegram:
    - Только ссылка и охват на строку, как просил заказчик.
    - Укладывается в 4096 символов; если не влезает, обрежем по limit записей.
    """
    header = f"{title}\n{period_text}\nВсего найдено: {len(results)}\n\n"

    lines = [f"• {format_number(r.reach)} — {r.url}" for r in results[:limit]]
    body = "\n".join(lines)
    text = header + body

    # если вдруг > 4096 символов — усечём по числу элементов
    while len(text) > 4096 and len(lines) > 0:
        lines = lines[:-1]
        body = "\n".join(lines)
        text = header + body
    return text

# --- Simple CLI for testing --------------------------------------------------
if __name__ == "__main__":
    import argparse, json, time
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", help="Path to txt or json with seed texts", required=True)
    parser.add_argument("--from", dest="from_dt", type=int, required=True, help="start ts (UTC)")
    parser.add_argument("--to", dest="to_dt", type=int, required=True, help="end ts (UTC)")
    parser.add_argument("--vk-token", dest="vk_token")
    parser.add_argument("--tgstat-token", dest="tgstat_token")
    args = parser.parse_args()

    # load seeds
    seeds: List[str] = []
    if args.seeds.endswith(".json"):
        seeds = json.load(open(args.seeds))
    else:
        seeds = [line.strip() for line in open(args.seeds, encoding="utf-8") if line.strip()]

    hits = search_vk_and_tg(
        seeds,
        start_time=args.from_dt,
        end_time=args.to_dt,
        vk_token=args.vk_token,
        tgstat_token=args.tgstat_token,
    )

    msg = render_message(hits, "Органические публикации", "Тестовый запуск")
    print(msg)
