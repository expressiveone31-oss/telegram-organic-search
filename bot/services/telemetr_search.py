from typing import List, Dict, Optional
import requests
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Пример токена и URL API — замените на актуальные значения
TELEM_TOKEN = "YOUR_TELEM_TOKEN_HERE"  # замените на реальный токен
TELEM_API_URL = "https://api.example.com/telemetry"  # замените на реальный URL


def search_telemetr(
    query: str,
    since: str,  # формат: "YYYY-MM-DD"
    until: str,  # формат: "YYYY-MM-DD"
    limit: int = 50,
    offset: int = 0
) -> List[Dict]:
    """
    Функция поиска телеметрии по запросу.
    Выполняет HTTP-запрос к API телеметрии и возвращает результаты.

    :param query: поисковый запрос (например, "error", "response_time")
    :param since: начальная дата (включительно), формат "YYYY-MM-DD"
    :param until: конечная дата (включительно), формат "YYYY-MM-DD"
    :param limit: лимит результатов (максимум 1000)
    :param offset: смещение для пагинации
    :return: список словарей с результатами поиска
    """
    try:
        headers = {
            "Authorization": f"Bearer {TELEM_TOKEN}",
            "Content-Type": "application/json"
        }

        params = {
            "q": query,
            "since": since,
            "until": until,
            "limit": limit,
            "offset": offset
        }

        response = requests.get(
            TELEM_API_URL,
            headers=headers,
            params=params,
            timeout=30
        )

        if response.status_code == 200:
            logger.info("Телеметрия найдена: %s результатов", len(response.json()))
            return response.json()
        else:
            logger.error(
                "Ошибка при поиске телеметрии: %s, %s",
                response.status_code,
                response.text
            )
            return []

    except requests.exceptions.RequestException as e:
        logger.error("Ошибка сети при поиске телеметрии: %s", str(e))
        return []
    except Exception as e:
        logger.error("Неожиданная ошибка: %s", str(e))
        return []


def get_telemetry_by_id(telemetry_id: str) -> Optional[Dict]:
    """
    Получить детальную информацию о телеметрии по ID.

    :param telemetry_id: ID записи телеметрии
    :return: словарь с данными или None, если не найдено
    """
    try:
        headers = {"Authorization": f"Bearer {TELEM_TOKEN}"}
        response = requests.get(
            f"{TELEM_API_URL}/{telemetry_id}",
            headers=headers,
            timeout=30
        )

        if response.status_code == 200:
            return response.json()
        else:
            logger.error("Ошибка получения телеметрии: %s", response.text)
            return None

    except Exception as e:
        logger.error("Ошибка при получении телеметрии: %s", str(e))
        return None


def filter_telemetry_by_status(telemetry_list: List[Dict], status: str) -> List[Dict]:
    """
    Фильтрация телеметрии по статусу.

    :param telemetry_list: список записей телеметрии
    :param status: статус для фильтрации (например, "error", "warning")
    :return: отфильтрованный список
    """
    return [item for item in telemetry_list if item.get("status") == status]


# Пример использования (можно удалить или закомментировать)
if __name__ == "__main__":
    # Пример поиска ошибок за последнюю неделю
    results = search_telemetr(
        query="error",
        since="2023-10-01",
        until="2023-10-07",
        limit=10
    )
    print("Найденные ошибки:", results)

    # Пример получения детальной информации
    if results:
        first_item = results[0]
        detailed = get_telemetry_by_id(first_item["id"])
        print("Детальная информация:", detailed)
