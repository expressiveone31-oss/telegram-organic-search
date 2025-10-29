
import asyncio, logging, os
from aiogram import Bot, Dispatcher
from bot.entrypoints.commands import setup_routers
logging.basicConfig(level=logging.INFO)
async def main():
    token = os.getenv("BOT_TOKEN","").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is not set")
    bot = Bot(token=token, parse_mode="HTML")
    dp = Dispatcher()
    setup_routers(dp)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
