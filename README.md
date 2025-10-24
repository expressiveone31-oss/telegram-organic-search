# Telegram Organic Search Bot (VK + TGStat)

Телеграм-бот, который ищет органические публикации в VK и Telegram по вашим подводкам и присылает список:
`охват — ссылка`.

## Быстрый старт (Railway)
1) Загрузите содержимое репозитория в GitHub (как есть, из этого архива).
2) В Railway → New Project → Deploy from GitHub → выберите репозиторий.
3) В Variables добавьте:
   - TELEGRAM_BOT_TOKEN
   - VK_TOKEN
   - TGSTAT_TOKEN
4) Railway сам обнаружит `Procfile` и запустит команду `worker: python bot/main.py`.

## Локальный запуск
```
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python bot/main.py
```

## Файлы
- bot/organic_reporter.py — поиск по VK и TGStat
- bot/main.py — телеграм-бот на aiogram
- Procfile — запуск на Railway (worker)
- runtime.txt — версия Python для Railway
- requirements.txt — зависимости
- .env.example — образец переменных окружения
- seeds.txt — пример подводок (каждая с новой строки)
