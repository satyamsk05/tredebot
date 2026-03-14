# 🤖 Polymarket Alpha Trade Bot v5.0 (Multi-Market)

A high-performance, automated multi-market trading bot for Polymarket. Optimized for **SOL, ETH, and BTC** 5m/15m markets. Featuring a premium real-time Terminal UI and a full-featured Telegram Remote Control.

---

## 🚀 Key Features

### 💎 Multi-Asset Support
- **Triple Profit Potential:** Trade **BTC, ETH, and SOL** simultaneously.
- **Dynamic Timeframes:** Support for both 5-minute and 15-minute intervals.
- **Granular Control:** Toggle specific market pairs (e.g., SOL 15m, BTC 5m) directly from Telegram.

### 📈 Premium Terminal UI
- **Live Monitoring:** Real-time dashboard showing USDC/Virtual balances, Martingale steps, and live market probabilities for the primary active market.
- **Multi-Asset Visibility:** The UI automatically adapts to show status for whichever markets are currently enabled.
- **Auto-Sync:** Real-time countdown to the next candle closure across all active sessions.

### 🤖 Smart Trading Strategy
- **Generalized Martingale:** Individual Martingale tracking for every asset/timeframe pair.
- **Polymarket Native API:** 100% accurate market resolution using direct Gamma API data.
- **Auto-Claim System:** Automatically redeems winning positions every 5 minutes to keep your balance liquid.
- **Simulation Mode:** Built-in `DRY_RUN` mode for risk-free strategy testing.

### 📱 Telegram Remote Control v2
- **Unified Command Center:** Start/Stop the entire node or individually toggle markets in the Settings menu.
- **Context-Aware Toggles:** Seamlessly switch between BTC, ETH, and SOL views for Status, History, and Performance.
- **Manual Injection:** Place trades manually for any active asset with structured amounts or custom sizes.
- **Global Reports:** 24-hour PnL analysis summarizing performance across all traded assets.

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
WALLET_ADDRESS=your_main_wallet
FUNDER_ADDRESS=your_funder_proxy_wallet

# Telegram Configuration
TELEGRAM_TOKEN=your_bot_token

# Bot Settings
DRY_RUN=True # Set to False for real trading
INITIAL_BET_AMOUNT=3
COINS=BTC,ETH,SOL
```

---

## 🎮 How to Use

### Start the Bot
Simply run the master script:
```bash
python run.py
```
This will launch the **Master Controller**, which manages the trading engine, the auto-claim task, and the Telegram process.

### Telegram Controls
- **🛠️ Settings -> 📈 Status**: Confirm which markets are currently trading and see the live countdown.
- **🌐 Multi-Market**: Enable or disable specific pairs (e.g., SOL 15M ✅).
- **💰 Balance**: Check USDC balance and auto-detected winnings.
- **🎁 Claim**: Manually trigger a redemption (note: the bot also auto-claims every 5m).
- **🔄 Reset L1**: Reset Martingale levels for all assets if a streak ends.

---

## 📁 Project Structure
- `/app`: Core logic (API, Bot, Trading Strategy)
- `/data`: Persistent storage (SQLite DBs, Market Config, Martingale state)
- `/logs`: categorized activity and error logs
- `run.py`: Master startup entry point

---

## ⚠️ Disclaimer
*Trading cryptocurrencies and prediction markets involves significant risk. This bot is provided for educational purposes "as-is" without any warranties. Use at your own risk.*

---

**Developed with ❤️ by Antigravity Agent**
