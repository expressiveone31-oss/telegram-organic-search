import os, time, asyncio
from aiogram import Bot, Dispatcher, executor, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.dispatcher import FSMContext
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
dp = Dispatcher(bot, storage=MemoryStorage())

# ----- Helpers -----
def load_seeds_from_file(p: Path) -> list[str]:
    if p.exists():
        return [line.strip() for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
    return []

def load_default_seeds() -> list[str]:
    p = Path(SEEDS_FILE)
    seeds = load_seeds_from_file(p)
    if seeds:
        return seeds
    # запасной вариант — чтобы команда работала даже без файла
    return [
        "Когда робот из «Кибердеревни» шарит больше, чем человеческий начальник",
        "Иногда будущее приходит слишком буквально",
    ]

# ----- States -----
class OrganicFlow(StatesGroup):
    waiting_for_seeds = State()

@dp.message_handler(commands=["start", "help"])
async def start_cmd(message: types.Message):
    await message.answer(
        "Привет! Я ищу органические публикации в VK и TG по вашим подводкам.\n\n"
        "Команды:\n"
        "• /organic — я попрошу подводки и запущу поиск\n"
        "• /organic_default — использую подводки из seeds.txt\n"
        "• /cancel — отменить текущий шаг"
    )

@dp.message_handler(commands=["organic"])
async def organic_ask_for_seeds(message: types.Message, state: FSMContext):
    await OrganicFlow.waiting_for_seeds.set()
    await message.answer(
        "Пришли подводки одним сообщением (каждая с новой строки), "
        "или отправь .txt файл. Затем я начну поиск за последние "
        f"{DAYS} дней.\n\nКоманда /cancel — отмена."
    )

@dp.message_handler(commands=["cancel"], state="*")
async def cancel(message: types.Message, state: FSMContext):
    await state.finish()
    await message.answer("Ок, отменила. Готова к новым командам.")

# --- Принимаем .txt файл с подводками
@dp.message_handler(content_types=[types.ContentType.DOCUMENT], state=OrganicFlow.waiting_for_seeds)
async def receive_file(message: types.Message, state: FSMContext):
    doc = message.document
    if not doc.file_name.lower().endswith(".txt"):
        await message.answer("Нужен именно .txt файл (одна подводка на строку). Попробуй ещё раз или пришли текстом.")
        return
    file = await bot.get_file(doc.file_id)
    file_bytes = await bot.download_file(file.file_path)
    content = file_bytes.read().decode("utf-8", errors="ignore")
    seeds = [line.strip() for line in content.splitlines() if line.strip()]
    await run_search_and_reply(message, seeds)
    await state.finish()

# --- Принимаем подводки просто текстом
@dp.message_handler(lambda m: m.text, state=OrganicFlow.waiting_for_seeds)
async def receive_text(message: types.Message, state: FSMContext):
    lines = [line.strip() for line in message.text.splitlines() if line.strip()]
    if not lines:
        await message.answer("Я не вижу подводок. Пришли их текстом (по строке на подводку) или отправь .txt файл.")
        return
    await run_search_and_reply(message, lines)
    await state.finish()

# --- Старый режим: берём seeds.txt
@dp.message_handler(commands=["organic_default"])
async def organic_default(message: types.Message):
    seed_texts = load_default_seeds()
    await message.answer("Ищу органику по подводкам из seeds.txt… ⏳")
    await run_search_and_reply(message, seed_texts)

# ----- Поиск и ответ -----
async def run_search_and_reply(message: types.Message, seed_texts: list[str]):
    now = int(time.time())
    start_time = now - DAYS * 24 * 3600
    end_time = now

    try:
        await message.answer(f"Приняла {len(seed_texts)} подводок. Ищу органику… это может занять до минуты ⏳")
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
    except Exception as e:
        await message.answer(f"Что-то пошло не так: {e}")

if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
