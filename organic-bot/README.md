# Organic Bot (VK + TGStat)

Телеграм-бот, который ищет органические публикации в VK и Telegram по вашим подводкам и присылает список:
`охват — ссылка`.

## Быстрый старт

1) Склонируйте репозиторий и перейдите в папку:
```
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

2) Создайте `.env` на основе `.env.example` и вставьте токены:
```
TELEGRAM_BOT_TOKEN=...
VK_TOKEN=...
TGSTAT_TOKEN=...
```

3) Отредактируйте `seeds.txt` (одна подводка на строку).

4) Запустите бота:
```
python bot/main.py
```

В Telegram отправьте боту команду `/organic` — получите список «охват — ссылка».

## Структура
- `bot/organic_reporter.py` — поиск по VK API и TGStat, сбор охвата, генерация текста.
- `bot/main.py` — минимальный Телеграм-бот на aiogram.
- `seeds.txt` — ваши подводки (входные данные).
- `.env.example` — образец переменных окружения.
- `requirements.txt` — зависимости.

## Примечания
- Для VK используйте **Service Token** из кабинета разработчика VK.
- Для Telegram используйте **TGStat API** токен (тариф S+), эндпоинт `/posts/search`.
- Если сообщение становится длиннее 4096 символов, бот автоматически его укорачивает.
