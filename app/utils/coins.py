from app.config import COINS

active_coins={coin:True for coin in COINS}

def enable_coin(c):
    active_coins[c]=True

def disable_coin(c):
    active_coins[c]=False

def get_active():
    return [c for c,v in active_coins.items() if v]
