from aiogram import Dispatcher
from bot.handlers.telemetr_search import router as telemetr_router
def setup_routers(dp: Dispatcher):
    dp.include_router(telemetr_router)
