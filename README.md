# 🤖 OG BOTS: Polymarket Alpha v5.1
---
A high-performance, automated trading bot for Polymarket. Optimized for **SOL 15m** Reversal strategy. Featuring a premium real-time Terminal UI, **Smart Catch-up** logic, and an **Inline Remote Control** via Telegram.

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
- **Smart Catch-up Logic**: Automatically detects and executes missed signals if resumed within 5 minutes of a candle start.
- **Reversal Streak Alpha**: Advanced signal checking for trend reversals (3-streak pattern).
- **Generalized Martingale**: Fixed recovery sequence ($3, $6, $13, $28, $60) to stay in the game.
- **Polymarket Native API**: 100% accurate market resolution using direct Gamma API data.
- **Auto-Claim System**: Automatically redeems winning positions every 5 minutes to keep your balance liquid.
- **Simulation Mode**: Built-in `DRY_RUN` mode for risk-free strategy testing.

### 📱 Telegram Remote OG Control
- **Inline Refresh**: Real-time "🔄 Refresh Price" buttons directly on price messages.
- **Premium Layout**: Optimized 3-column main menu for fast one-tap navigation.
- **Auto-Fill Notifications**: Instant alerts when manual or auto limit orders are filled.
- **Consolidated Settings**: All secondary tools (Help, Daily Report) neatly organized in a clean sub-menu.
- **Context-Aware Toggles**: Seamlessly switch views for Status, History, and Performance.

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
