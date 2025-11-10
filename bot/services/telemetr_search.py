import logging
import asyncio
import aiohttp
from typing import Tuple, List, Dict, Any
from datetime import datetime, timedelta

# Настройка логирования
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Глобальные настройки (задайте свои значения)
TELEM_TOKEN = None  # Замените на ваш токен
TELEM_DATE_TO_INCLUSIVE = True  # Флаг включения конечной даты
TELEM_BASE_URL = "https://api.example.com"  # Замените на URL вашего API


def _plus_one_day(date_str: str) -> str:
    """
    Добавляет один день к дате в формате YYYY-MM-DD.
    """
    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    new_date = date_obj + timedelta(days=1)
    return new_date.strftime("%Y-%m-%d")


async def _fetch_page(
    session: aiohttp.ClientSession,
    query: str,
    since: str,
    until: str,
    page: int,
    limit: int = 50,
) -> Tuple[List[Any], Dict[str, Any]]:
    """
    Выполняет запрос к API для получения данных по поисковому запросу с фильтрацией по датам.
    Включает полную обработку ошибок и логирование для диагностики.
    """
    logger.info("Запуск _fetch_page с параметрами: query=%s, since=%s, until=%s, page=%d, limit=%d",
                query, since, until, page, limit)

    # Шаг 1: Проверка наличия TELEM_TOKEN
    if not TELEM_TOKEN:
        logger.critical("Критическая ошибка: TELEMETR_TOKEN не задан. Невозможно выполнить запрос.")
        return [], {"error": "TELEMETR_TOKEN is not set"}

    # Шаг 2: Расчёт конечной даты с учётом настройки inclusivity
    try:
        date_to = _plus_one_day(until) if TELEM_DATE_TO_INCLUSIVE else until
        logger.debug("Рассчитанная дата окончания: %s (TELEM_DATE_TO_INCLUSIVE=%s)",
                    date_to, TELEM_DATE_TO_INCLUSIVE)
    except Exception as e:
        logger.error("Ошибка при расчёте даты окончания: %s", str(e))
        return [], {"error": f"Ошибка расчёта даты: {str(e)}"}

    # Шаг 3: Формирование параметров запроса
    params = {
        "query": query,
        "date_from": since,
        "date_to": date_to,
        "limit": str(limit),
        "page": str(page),
    }
    logger.debug("Параметры запроса сформированы: %s", params)

    headers = {"Authorization": f"Bearer {TELEM_TOKEN}"}
    logger.debug("Заголовки запроса: %s", headers)

    # Шаг 4: Выполнение HTTP-запроса
    try:
        async with session.get(
            url=f"{TELEM_BASE_URL}/channels/posts/search",
            params=params,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=60)  # увеличенный таймаут
        ) as resp:
            logger.info("HTTP-запрос отправлен. Статус ответа: %d", resp.status)

            # Проверка HTTP-статуса
            if resp.status != 200:
                error_msg = f"HTTP ошибка: {resp.status} - {resp.reason}"
                logger.error(error_msg)
                return [], {"error": error_msg}

            # Шаг 5: Парсинг JSON-ответа
            try:
                data = await resp.json(content_type=None)
                logger.debug("JSON-ответ успешно распарсен")
            except aiohttp.ContentTypeError as e:
                text = await resp.text()
                error_msg = f"Ошибка парсинга JSON: {text} ({e})"
                logger.error(error_msg)
                return [], {"error": error_msg}
            except Exception as e:
                error_msg = f"Неожиданная ошибка при парсинге JSON: {str(e)}"
                logger.exception(error_msg)
                return [], {"error": error_msg}

            # Шаг 6: Валидация структуры ответа
            if not isinstance(data, dict):
                error_msg = f"Ответ API не является словарем: {type(data)}"
                logger.error(error_msg)
                return [], {"error": error_msg}

            if data.get("status") != "ok":
                error_msg = f"Неверный статус ответа API: {data.get('status')}"
                logger.error(error_msg)
                return [], {"error": error_msg}

            # Шаг 7: Извлечение данных
            resp_obj = data.get("response", {})
            items = resp_obj.get("items", [])
            meta = {
                "count": resp_obj.get("count"),
                "total_count": resp_obj.get("total_count"),
                "page": page,
                "limit": limit
            }

            logger.info("Данные успешно получены. Количество элементов: %d", len(items))
            logger.debug("Метаданные: %s", meta)

            return items, meta

    except aiohttp.ClientError as e:
        error_msg = f"Ошибка клиента aiohttp: {type(e).__name__}: {str(e)}"
        logger.error(error_msg)
        return [], {"error": error_msg}

    except asyncio.TimeoutError:
        error_msg = "Таймаут при ожидании ответа от API (60 секунд)"
        logger.error(error_msg)
        return [], {"error": error_msg}

    except Exception as e:
        error_msg = f"Непредвиденная ошибка: {type(e).__name__}: {str(e)}"
        logger.exception("Полный стектрейс ошибки:")
        return [], {"error": error_msg}


# Пример функции для запуска запросов (можно доработать)
async def fetch_all_pages(query: str, since: str, until: str, limit: int = 50):
    """Собирает данные со всех страниц."""
    async with aiohttp.ClientSession() as session:
        all_items = []
        page = 1
        while True:
            items, meta = await _fetch_page(session, query, since, until, page, limit)
            if "error" in meta:
                logger.error("Ошибка при получении страницы %d: %s", page, meta["error"])
                break

            all_items.extend(items)
            if len(items) < limit:  # Нет больше данных
                break
            page += 1

        return all_items


if __name__ == "__main__":
    # Пример запуска (замените параметры на свои)
    asyncio.run(fetch_all_pages(
        query="example query",
        since="2023-01-01",
        until="2023-12-31",
        limit=50
    ))
