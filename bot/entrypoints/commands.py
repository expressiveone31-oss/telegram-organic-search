from aiogram import Router, types, F
from aiogram.filters import CommandStart

commands_router = Router(name="commands")


@commands_router.message(CommandStart())
async def start_cmd(m: types.Message):
    await m.answer(
        "Привет! Я бот поиска по <b>Телеграм</b>.\n"
        "Отправь диапазон дат в формате <code>YYYY-MM-DD — YYYY-MM-DD</code>, "
        "затем — фразы для поиска (по одной на строке)."
    )


@commands_router.message(F.text == "/ping")
async def ping(m: types.Message):
    await m.answer("pong")
