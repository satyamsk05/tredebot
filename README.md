# 🤖 Polymarket Alpha Trade Bot v4.0

A professional-grade, automated trading bot for **Polymarket 5m BTC Up/Down** markets. Built for speed, reliability, and precision, featuring a premium Terminal UI and a full-featured Telegram Remote Control.

---

## 🚀 Key Features

### 💎 Premium Terminal UI
- **Live Monitoring:** Real-time dashboard showing USDC/Virtual balances, Martingale steps, and live market probabilities.
- **Smart Logging:** Categorized system logs (INFO, SUCCESS, TRADE, ERROR) with a flicker-free visual experience.
- **Auto-Sync:** Real-time countdown to the next candle closure.

### 📈 Smart Trading Strategy
- **Martingale Integration:** Sophisticated level-based betting (L1 to L7) to maximize recovery.
- **Polymarket Gamma API:** Native integration for 100% accurate market data (no Binance discrepancies).
- **Virtual Balance System:** Test strategies safely with a built-in simulation mode.
- **Slippage Protection:** Market execution optimized for best-available entry.

### 📱 Telegram Remote Control
- **Dynamic Controls:** Toggle bot START/STOP with real-time state-aware buttons.
- **Manual Injection:** Place trades manually directly from Telegram with structured amounts ($5, $10) or custom sizes.
- **Daily Performance Reports:** 24-hour PnL analysis, win/loss stats, and volume tracking.
- **Nested Settings:** Organized menu for Martingale reset, Matrix overview, and Help guides.

---

## 🛠️ Technical Stack
- **Language:** Python 3.10+
- **Bot Engine:** `python-telegram-bot` (v21.0+)
- **API Client:** `py-clob-client` (Official Polymarket SDK)
- **Database:** SQLite (Persistent trade and candle history)
- **UI Framework:** Vanilla ANSI + custom `SimpleLogger`

---

## 📦 Installation & Setup

### 1. Clone the Repository
```bash
git clone https://github.com/satyamsk05/tredebot.git
cd tredebot
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Configuration
Create a `.env` file in the root directory and add your credentials:
```env
# Polymarket API Credentials
POLY_PRIVATE_KEY=your_private_key
POLY_API_KEY=your_api_key
POLY_API_SECRET=your_api_secret
POLY_PASSPHRASE=your_passphrase
FUNDER_ADDRESS=your_wallet_address

# Telegram Configuration
TELEGRAM_TOKEN=your_bot_token

# Bot Settings
DRY_RUN=True # Set to False for real trading
INITIAL_BET_AMOUNT=3
INTERVAL=5
```

---

## 🎮 How to Use

### Start the Bot
Simply run the master script:
```bash
python run.py
```
This will launch both the **Trading Engine** and the **Telegram Interface**.

### Telegram Commands
- **📈 Status:** Get a snapshot of the current strategy state.
- **💰 Balance:** View both USDC and Virtual balances.
- **📊 Daily Report:** See how much you made in the last 24 hours.
- **🔄 Reset L1:** Manually reset the Martingale count to Level 1 ($3).
- **🛑 Stop Bot:** Emergency stop to pause all automated execution.

---

## 📁 Project Structure
- `/app`: Core logic (API, Bot, Trading Strategy)
- `/data`: Persistent storage (SQLite DB, Martingale state)
- `/logs`: Activity and error logs
- `run.py`: Master entry point

---

## ⚠️ Disclaimer
*Trading cryptocurrencies and prediction markets involves significant risk. This bot is provided for educational purposes "as-is" without any warranties. Use at your own risk.*

---

**Developed with ❤️ by Antigravity Agent**
