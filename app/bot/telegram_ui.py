from telegram import ReplyKeyboardMarkup
from app.config import COINS

MAIN_MENU = ReplyKeyboardMarkup(
[
["📊 History","💰 Balance"],
["📈 Status","⚙ Settings"],
["▶ Start","⏹ Stop"],
["🪙 Coins"]
],
resize_keyboard=True
)

def COINS_MARKUP():
    buttons = []
    # Create toggle buttons for each coin
    for coin in COINS:
        buttons.append([f"Toggle {coin}"])
    buttons.append(["🔙 Back"])
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)
