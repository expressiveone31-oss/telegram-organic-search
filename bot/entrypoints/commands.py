from aiogram import Dispatcher
from bot.handlers.organic import router as organic_router


def setup_routers(dp: Dispatcher) -> None:
    dp.include_router(organic_router)
