
import os, asyncio, logging
from aiogram import Bot, Dispatcher
from bot.entrypoints.commands import router as commands_router

logging.basicConfig(level=logging.INFO)

async def main():
    bot_token = os.getenv("BOT_TOKEN","").strip()
    if not bot_token:
        raise RuntimeError("BOT_TOKEN is not set")
    dp = Dispatcher()
    dp.include_router(commands_router)
    bot = Bot(bot_token, parse_mode="MarkdownV2")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
