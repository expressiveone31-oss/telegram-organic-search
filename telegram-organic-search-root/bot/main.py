import os, time
from aiogram import Bot, Dispatcher, executor, types
from dotenv import load_dotenv
from pathlib import Path

from organic_reporter import search_vk_and_tg, render_message

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
VK_TOKEN = os.getenv("VK_TOKEN")
TGSTAT_TOKEN = os.getenv("TGSTAT_TOKEN")
DAYS = int(os.getenv("ORGANIC_DAYS", "30"))
SEEDS_FILE = os.getenv("SEEDS_FILE", "seeds.txt")

bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher(bot)

def load_seeds() -> list[str]:
    p = Path(SEEDS_FILE)
    if p.exists():
        return [line.strip() for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
    # запасной вариант — вставь сюда свои подводки
    return [
        "Когда робот из «Кибердеревни» шарит больше, чем человеческий начальник",
        "Иногда будущее приходит слишком буквально",
    ]

@dp.message_handler(commands=["start", "help"])
async def start_cmd(message: types.Message):
    await message.answer(
        "Привет! Я ищу органические публикации в VK и TG по вашим подводкам.\n"
        "Команда: /organic — пришлю список «охват — ссылка»."
    )

@dp.message_handler(commands=["organic"])
async def organic_cmd(message: types.Message):
    seed_texts = load_seeds()

    now = int(time.time())
    start_time = now - DAYS * 24 * 3600
    end_time = now

    await message.answer("Ищу органику… это может занять до минуты ⏳")

    results = search_vk_and_tg(
        seed_texts,
        start_time,
        end_time,
        vk_token=VK_TOKEN,
        tgstat_token=TGSTAT_TOKEN,
    )

    text = render_message(
        results,
        title="Органические публикации",
        period_text=f"Последние {DAYS} дней"
    )
    await message.answer(text, disable_web_page_preview=True)

if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
