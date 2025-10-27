import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode

from bot.entrypoints.commands import commands_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def main():
    token = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN не задан")

    # HTML вместо MarkdownV2 — меньше проблем с экранированием
    bot = Bot(token=token, parse_mode=ParseMode.HTML)
    dp = Dispatcher()

    # Сносим возможный старый вебхук (иначе long-polling может «молчать»)
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Webhook удалён, переключаемся на long-polling")
    except Exception as e:
        logger.warning(f"Не удалось удалить webhook: {e}")

    # Роутеры (обработчики команд)
    dp.include_router(commands_router)

    logger.info("Start polling…")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
