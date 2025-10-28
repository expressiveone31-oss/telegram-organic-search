
# -*- coding: utf-8 -*-
import asyncio, os
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from bot.entrypoints.commands import setup_routers

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

async def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set")
    bot = Bot(BOT_TOKEN, parse_mode=ParseMode.HTML)
    dp = Dispatcher()
    setup_routers(dp)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
