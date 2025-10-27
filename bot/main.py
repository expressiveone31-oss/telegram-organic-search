import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from bot.entrypoints.commands import commands_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def main():
    token = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN не задан")

    bot = Bot(token=token, parse_mode=ParseMode.HTML)
    dp = Dispatcher(storage=MemoryStorage())

    # На всякий случай убираем webhook
    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception:
        pass

    dp.include_router(commands_router)
    logger.info("Start polling…")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
