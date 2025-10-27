
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Отмена", callback_data="cancel")
    ]])
