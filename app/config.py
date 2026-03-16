import os
from dotenv import load_dotenv

load_dotenv(override=True)

# Telegram
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Trading Keys
POLY_API_KEY = os.getenv("POLY_API_KEY")
POLY_API_SECRET = os.getenv("POLY_API_SECRET")
POLY_PASSPHRASE = os.getenv("POLY_PASSPHRASE")
POLY_PRIVATE_KEY = os.getenv("POLY_PRIVATE_KEY") or os.getenv("PRIVATE_KEY")
funder = os.getenv("POLY_FUNDER") or os.getenv("FUNDER_ADDRESS")
FUNDER_ADDRESS = None if funder and funder.startswith("your_") else funder
wallet = os.getenv("WALLET_ADDRESS")
WALLET_ADDRESS = None if wallet and wallet.startswith("your_") else wallet

# Builder API Keys (Gasless Redemption)
BUILDER_API_KEY = os.getenv("BUILDER_API_KEY")
BUILDER_SECRET = os.getenv("BUILDER_SECRET")
BUILDER_PASSPHRASE = os.getenv("BUILDER_PASSPHRASE")
RELAYER_URL = os.getenv("RELAYER_URL", "https://relayer-v2.polymarket.com") 

# Network Settings
RPC_URL = os.getenv("RPC_URL", "https://polygon-rpc.com")

# Strategy & Intervals
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
INTERVAL = int(os.getenv("INTERVAL", "5"))
INITIAL_BET_AMOUNT = int(os.getenv("INITIAL_BET_AMOUNT", "3"))
VIRTUAL_BALANCE_START = float(os.getenv("VIRTUAL_BALANCE_START", "500.00"))
# COINS = os.getenv("COINS", "BTC,ETH,SOL").split(",")
COINS = ["SOL"]
ENABLE_5M = os.getenv("ENABLE_5M", "true").lower() == "true"
ENABLE_15M = os.getenv("ENABLE_15M", "true").lower() == "true"

# Advanced / Hardcoded
WS_URL = "wss://ws-live-data.polymarket.com"
BINANCE_WS_URL = "wss://stream.binance.com:9443/ws"

WS_MARKET_IDS = {
    "ethusdt": "ETH",
    "solusdt": "SOL"
}
