import os
import json
import logging
import time
import asyncio
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes, ConversationHandler
from dotenv import load_dotenv

from app.db import get_last_n_candles, get_24h_stats
from app.trading.trader import get_balance, get_virtual_balance, update_virtual_balance
from app.api.btc_api import get_active_btc_market, get_last_trade_price, place_btc_bet
from app.config import INTERVAL, INITIAL_BET_AMOUNT, TELEGRAM_TOKEN, DRY_RUN
from app.trading.martingale import BET_SEQUENCE, Martingale
import json

from logging.handlers import RotatingFileHandler

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        RotatingFileHandler(
            "logs/telegram_bot.log",
            maxBytes=5 * 1024 * 1024,  # 5 MB
            backupCount=2
        )
    ]
)

# Silence noisy libraries
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)

def get_main_menu():
    paused = os.path.exists("pause.flag")
    btn_text = "▶️ START BOT" if paused else "🛑 STOP BOT"
    return ReplyKeyboardMarkup(
        [
            [btn_text],
            ["📈 Status", "💰 Balance"],
            ["📊 History", "📉 Live Price"],
            ["🎯 Manual Trade", "🛠️ Settings"]
        ],
        resize_keyboard=True
    )

SETTINGS_MENU = ReplyKeyboardMarkup(
    [
        ["🏆 Performance", "🔄 Reset L1"],
        ["📊 Daily Report", "🆘 Help"],
        ["🔙 Back"]
    ],
    resize_keyboard=True
)

MANUAL_TRADE_MENU = ReplyKeyboardMarkup(
    [
        ["🟢 UP $5", "🟢 UP $10"],
        ["🔴 DOWN $5", "🔴 DOWN $10"],
        ["🎯 Custom UP", "🎯 Custom DOWN"],
        ["🔙 Back"]
    ],
    resize_keyboard=True
)

WAITING_FOR_AMOUNT = 1

NOTIFY_FILE = "data/telegram_notify.json"
CHAT_ID_FILE = "data/telegram_chat_id.txt"

# ── Helpers ──
def log_activity(command, update: Update):
    user = update.effective_user.first_name if update.effective_user else "User"
    try:
        with open("logs/telegram_activity.log", "a") as f:
            f.write(f"{user}: {command}\n")
    except Exception:
        pass

def save_chat_id(chat_id):
    """Save chat ID so main.py can send proactive notifications."""
    try:
        with open(CHAT_ID_FILE, "w") as f:
            f.write(str(chat_id))
    except Exception:
        pass

def get_chat_id():
    try:
        if os.path.exists(CHAT_ID_FILE):
            with open(CHAT_ID_FILE, "r") as f:
                return int(f.read().strip())
    except Exception:
        pass
    return None

# ── Notification Checker (Proactive Alerts) ──
async def check_notifications(context: ContextTypes.DEFAULT_TYPE):
    """Periodically check for notifications from main.py and send them to Telegram."""
    chat_id = get_chat_id()
    if not chat_id:
        return
    
    if not os.path.exists(NOTIFY_FILE):
        return
    
    try:
        with open(NOTIFY_FILE, "r") as f:
            notifications = json.load(f)
        
        # Clear the file immediately
        os.remove(NOTIFY_FILE)
        
        if isinstance(notifications, list):
            for notif in notifications:
                msg = notif.get("message", "")
                if msg:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=msg,
                        parse_mode="Markdown"
                    )
    except Exception as e:
        logging.error(f"Notification check error: {e}")

# ── Command Handlers ──

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("/start", update)
    save_chat_id(update.effective_chat.id)
    
    welcome = (
        "📈 *POLYMARKET TRADING HUB*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "⚡️ *BTC 5m Up/Down Alpha*\n"
        f"---------------------------\n"
        f"💵 Base Bet: *${INITIAL_BET_AMOUNT}*\n"
        f"⏱️ Interval: *{INTERVAL}m Candles*\n"
        f"🧪 Protocol: *{'DRY RUN' if DRY_RUN else 'LIVE'}*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Dashboard controlling active... 👇"
    )
    
    await update.message.reply_text(welcome, reply_markup=get_main_menu(), parse_mode="Markdown")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("Status", update)
    save_chat_id(update.effective_chat.id)
    
    now_ts = int(time.time())
    interval_sec = INTERVAL * 60
    next_boundary = ((now_ts // interval_sec) * interval_sec) + interval_sec
    seconds_until_next = next_boundary - now_ts
    mins, secs = divmod(seconds_until_next, 60)
    
    mg = Martingale()
    step = mg.get_step("BTC")
    bet = BET_SEQUENCE[step]
    
    paused = os.path.exists("pause.flag")
    status_icon = "⏸️ PAUSED" if paused else "🟢 ACTIVE"
    
    msg = (
        f"🖥️ *STRATEGY DASHBOARD*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📡 Status: {status_icon}\n"
        f"⏳ Next Batch: *{mins:02d}:{secs:02d}s*\n"
        f"--------------------------\n"
        f"🎯 Market: *BTC 5m Up/Down*\n"
        f"📊 Step: *Level {step+1}*\n"
        f"💰 Bet Size: *${bet}*\n"
        f"🧪 Mode: *{'SIMULATION' if DRY_RUN else 'LIVE'}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("Balance", update)
    save_chat_id(update.effective_chat.id)
    
    usdc_bal = get_balance()
    v_bal = get_virtual_balance()
    msg = (
        f"💰 *FINANCIAL OVERVIEW*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🧪 Virtual: *${v_bal:,.2f}*\n"
        f"--------------------------\n"
        f"💸 USDC: *${usdc_bal:,.2f}*\n"
        f"🏦 Chain: *Polygon (POS)*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("History", update)
    save_chat_id(update.effective_chat.id)
    
    closes = get_last_n_candles(10)
    
    if not closes:
        await update.message.reply_text("📂 *No candle history found.*", parse_mode="Markdown")
        return
    
    hist_text = "📊 *MARKET HISTORY LOG*\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    seen_ts = set()
    filtered_closes = []
    
    for c in closes:
        # Use either timestamp for dicts or index placeholder for old data
        ts = c.get('timestamp') if isinstance(c, dict) else id(c)
        if ts not in seen_ts:
            seen_ts.add(ts)
            filtered_closes.append(c)

    for i, c in enumerate(reversed(filtered_closes)):
        if isinstance(c, dict):
            p = c['close_price']
            from datetime import datetime
            time_str = datetime.fromtimestamp(c['timestamp']).strftime('%H:%M')
            time_display = f" 🕒 `{time_str}`"
        else:
            p = c
            time_display = ""
            
        icon = "🟢" if p > 0.5 else "🔴"
        direction = "UP" if p > 0.5 else "DOWN"
        hist_text += f"{icon} `#{i+1:02d}` | *{direction}* | `{p:.4f}`{time_display}\n"
    
    hist_text += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━"
    await update.message.reply_text(hist_text, parse_mode="Markdown")

async def start_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_chat_id(update.effective_chat.id)
    if os.path.exists("pause.flag"):
        log_activity("Start", update)
        os.remove("pause.flag")
        await update.message.reply_text(
            "▶️ *Bot Started!*\n\nTrading execution is now active.",
            reply_markup=get_main_menu(),
            parse_mode="Markdown"
        )
    else:
        log_activity("Stop", update)
        with open("pause.flag", "w") as f:
            f.write("paused")
        await update.message.reply_text(
            "🛑 *Bot Stopped!*\n\nThe bot will analyze but will *not* place trades until started again.",
            reply_markup=get_main_menu(),
            parse_mode="Markdown"
        )

async def reset_martingale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("/reset", update)
    save_chat_id(update.effective_chat.id)
    
    mg = Martingale()
    mg.win("BTC") # This resets step to 0 (L1)
    
    msg = (
        "🔄 *MARTINGALE RESET*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "✅ Level has been reset to *L1* ($3).\n"
        "🚀 Next trade will start fresh."
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def performance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("Performance", update)
    save_chat_id(update.effective_chat.id)
    
    mg = Martingale()
    step = mg.get_step("BTC")
    bet = BET_SEQUENCE[step]
    
    # Build sequence display
    seq_display = ""
    for i, b in enumerate(BET_SEQUENCE):
        if i == step:
            seq_display += f"➡️ *${b}*  "
        else:
            seq_display += f"${b}  "
    
    msg = (
        "🏆 *MARTINGALE MATRIX*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📈 Position: *L{step+1}*\n"
        f"💰 Risking: *${bet}*\n"
        f"--------------------------\n"
        f"Strategy Sequence:\n"
        f"`{seq_display.replace('*', '')}`\n\n"
        f"Current: *{bet} USD*"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def live_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("Live Price", update)
    save_chat_id(update.effective_chat.id)
    
    active = get_active_btc_market(offset_minutes=0)
    if not active:
        await update.message.reply_text("❌ No active market found.")
        return
    
    yes_price = get_last_trade_price(active['yes_token'])
    no_price = get_last_trade_price(active['no_token'])
    
    msg = (
        "📉 *REAL-TIME PROBABILITIES*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📌 {active['question']}\n"
        f"--------------------------\n"
        f"🟢 YES (UP):   *{yes_price}*\n"
        f"🔴 NO (DOWN):  *{no_price}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("Settings", update)
    save_chat_id(update.effective_chat.id)
    
    msg = (
        "🛠️ *NODE SETTINGS & TOOLS*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🎯 Strategy: *BTC 5m Momentum*\n"
        f"⏱️ Window:   *{INTERVAL} Minutes*\n"
        f"🧪 State:    *{'SIMULATION' if DRY_RUN else 'LIVE'}*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Choose an option below 👇"
    )
    await update.message.reply_text(msg, reply_markup=SETTINGS_MENU, parse_mode="Markdown")

async def daily_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("Daily Report", update)
    save_chat_id(update.effective_chat.id)
    
    stats = get_24h_stats()
    
    total_trades = stats["wins"] + stats["losses"]
    win_rate = (stats["wins"] / total_trades * 100) if total_trades > 0 else 0
    
    msg = (
        "📊 *24H PERFORMANCE REPORT*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"✅ Wins:       *{stats['wins']}*\n"
        f"❌ Losses:     *{stats['losses']}*\n"
        f"📈 Win Rate:   *{win_rate:.1f}%*\n"
        f"---------------------------\n"
        f"💰 Net Profit: *{'+' if stats['total_profit'] >=0 else ''}${stats['total_profit']:.2f}*\n"
        f"📊 Volume:     *${stats['total_volume']:.2f}*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "_Note: Data started recording now._"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def back_to_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("Back", update)
    await update.message.reply_text("🔙 *Returning to Main Menu*", reply_markup=get_main_menu(), parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("Help", update)
    save_chat_id(update.effective_chat.id)
    
    msg = (
        "🆘 *COMMAND CENTER GUIDE*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📈 *Status*    — Node heartbeat\n"
        "💰 *Balance*   — Financial snapshot\n"
        "📊 *History*   — Market execution log\n"
        "---------------------------\n"
        "📉 *Live*      — Odds analysis\n"
        "🎯 *Manual*    — Direct injection\n"
        "🏆 *Matrix*    — Martingale levels\n"
        "⏱️ *Control*   — Toggle execution\n\n"
        "_Need help? Contact support or type /start_"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

# ── Manual Trade (with custom amount) ──

async def manual_trade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("Manual Trade", update)
    save_chat_id(update.effective_chat.id)
    
    active = get_active_btc_market(offset_minutes=0)
    market_name = active['question'] if active else "Unknown Market"
    
    msg = (
        "🎯 *MANUAL TRADE CENTER*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📌 Market: *{market_name}*\n\n"
        "Select an amount from the keyboard to inject a trade instantly. 👇"
    )
    
    await update.message.reply_text(msg, reply_markup=MANUAL_TRADE_MENU, parse_mode="Markdown")

async def handle_fixed_manual_trade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text # e.g. "🟢 UP $5"
    log_activity(f"Fixed MT: {text}", update)
    
    # Parse text
    direction_str = "up" if "UP" in text else "down"
    try:
        amount = float(text.split("$")[1])
    except:
        return

    active = get_active_btc_market(offset_minutes=0)
    if not active:
        await update.message.reply_text("❌ No active market found.")
        return
    
    if direction_str == "up":
        token = active['yes_token']
        direction = "YES (UP)"
        icon = "🟢"
    else:
        token = active['no_token']
        direction = "NO (DOWN)"
        icon = "🔴"
    
    buy_price = get_last_trade_price(token)
    if not buy_price or buy_price <= 0:
        buy_price = 0.50
    shares = amount / buy_price
    
    msg_waiting = await update.message.reply_text(f"⏳ Placing *${amount}* on *{direction}*...", parse_mode="Markdown")
    
    success = place_btc_bet(token, amount)
    
    if success:
        try:
            with open("data/manual_bet.json", "w") as f:
                signal_dir = "YES" if direction_str == "up" else "NO"
                json.dump({
                    "direction": signal_dir, 
                    "timestamp": active['timestamp'], 
                    "amount": amount,
                    "buy_price": buy_price,
                    "shares": shares,
                    "order_type": "Manual"
                }, f)
            update_virtual_balance(-amount)
        except Exception as e:
            logging.error(f"Failed to sync manual bet: {e}")

        from datetime import datetime
        exec_time = datetime.now().strftime('%H:%M:%S')
        
        msg = (
            f"🎯 *Manual Trade Executed*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"⏰ Time: *{exec_time}*\n"
            f"--------------------------\n"
            f"💰 Amount: *${amount}*\n"
            f"--------------------------\n"
            f"📊 Position: *{direction}*\n"
            f"--------------------------\n"
            f"🪙 Shares: *{shares:.2f}* (@ {buy_price:.2f})\n"
            f"--------------------------\n"
            f"⚙️ Order Type: *Manual*\n"
            f"--------------------------\n"
            f"📌 Market: *{active['question']}*\n"
            f"--------------------------\n"
            f"{'🧪 DRY RUN MODE' if DRY_RUN else '💸 LIVE ORDER PLACED'}\n"
            f"{'No real funds used.' if DRY_RUN else 'Real funds dedicated.'}"
        )
        await msg_waiting.edit_text(text=msg, parse_mode="Markdown")
    else:
        await msg_waiting.edit_text(text="❌ Failed to place order. Check terminal logs.")

async def handle_custom_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    direction = "UP" if "UP" in text else "DOWN"
    context.user_data["custom_direction"] = direction.lower()
    
    await update.message.reply_text(
        text=f"🎯 *Custom {direction} Trade*\n\nReply with the amount you want to bet (e.g. `5.5` or `10`):",
        parse_mode="Markdown"
    )
    return WAITING_FOR_AMOUNT

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if not data.startswith("mt_"):
        return
    
    if data.startswith("mt_custom_"):
        direction = data.replace("mt_custom_", "")
        context.user_data["custom_direction"] = direction
        await query.edit_message_text(
            text=f"✍️ *Custom {direction.upper()} Trade*\n\nReply with the amount you want to bet (e.g. `5.5` or `10`):",
            parse_mode="Markdown"
        )
        return WAITING_FOR_AMOUNT
    
    # Parse: mt_up_5 or mt_down_10
    parts = data.split("_")
    if len(parts) != 3:
        return
    
    direction_str = parts[1]  # "up" or "down"
    amount = int(parts[2])
    
    active = get_active_btc_market(offset_minutes=0)
    if not active:
        await query.edit_message_text(text="❌ No active market found.")
        return
    
    if direction_str == "up":
        token = active['yes_token']
        direction = "YES (UP)"
        icon = "📈"
    else:
        token = active['no_token']
        direction = "NO (DOWN)"
        icon = "📉"
    
    buy_price = get_last_trade_price(token)
    if not buy_price or buy_price <= 0:
        buy_price = 0.50
    shares = amount / buy_price
    
    log_activity(f"MT: {direction} ${amount}", update)
    await query.edit_message_text(text=f"⏳ Placing *${amount}* on *{direction}*...", parse_mode="Markdown")
    
    success = place_btc_bet(token, amount)
    
    if success:
        try:
            with open("data/manual_bet.json", "w") as f:
                import json
                signal_dir = "YES" if direction_str == "up" else "NO"
                json.dump({
                    "direction": signal_dir, 
                    "timestamp": active['timestamp'], 
                    "amount": amount,
                    "buy_price": buy_price,
                    "shares": shares,
                    "order_type": "Manual"
                }, f)
            update_virtual_balance(-amount)
        except Exception as e:
            logging.error(f"Failed to sync manual bet: {e}")

        from datetime import datetime
        exec_time = datetime.now().strftime('%H:%M:%S')
        
        msg = (
            f"🎯 *Manual Trade Executed*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"⏰ Time: *{exec_time}*\n"
            f"--------------------------\n"
            f"💰 Amount: *${amount}*\n"
            f"--------------------------\n"
            f"📊 Position: *{direction}*\n"
            f"--------------------------\n"
            f"🪙 Shares: *{shares:.2f}* (@ {buy_price:.2f})\n"
            f"--------------------------\n"
            f"⚙️ Order Type: *Manual*\n"
            f"--------------------------\n"
            f"📌 Market: *{active['question']}*\n"
            f"--------------------------\n"
            f"{'🧪 DRY RUN MODE' if DRY_RUN else '💸 LIVE ORDER PLACED'}\n"
            f"{'No real funds used.' if DRY_RUN else 'Real funds dedicated.'}"
        )
        await query.edit_message_text(text=msg, parse_mode="Markdown")
    else:
        await query.edit_message_text(text="❌ Failed to place order. Check terminal logs.")

async def handle_custom_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    amount_text = update.message.text
    direction_str = context.user_data.get("custom_direction", "up")
    
    try:
        amount = float(amount_text)
        if amount <= 0:
            raise ValueError()
    except ValueError:
        await update.message.reply_text("❌ Invalid amount. Please enter a positive number (e.g. `5.5`):")
        return WAITING_FOR_AMOUNT

    active = get_active_btc_market(offset_minutes=0)
    if not active:
        await update.message.reply_text("❌ No active market found.")
        return ConversationHandler.END
    
    if direction_str == "up":
        token = active['yes_token']
        direction = "YES (UP)"
        icon = "📈"
    else:
        token = active['no_token']
        direction = "NO (DOWN)"
        icon = "📉"
    
    buy_price = get_last_trade_price(token)
    if not buy_price or buy_price <= 0:
        buy_price = 0.50
    shares = amount / buy_price
    
    # Log activity
    user = update.effective_user.first_name if update.effective_user else "User"
    try:
        with open("logs/telegram_activity.log", "a") as f:
            f.write(f"{user}: MT Custom {direction_str.upper()} ${amount}\n")
    except Exception:
        pass

    msg_waiting = await update.message.reply_text(f"⏳ Placing *${amount}* on *{direction}*...", parse_mode="Markdown")
    
    success = place_btc_bet(token, amount)
    
    if success:
        try:
            with open("data/manual_bet.json", "w") as f:
                signal_dir = "YES" if direction_str == "up" else "NO"
                json.dump({
                    "direction": signal_dir, 
                    "timestamp": active['timestamp'], 
                    "amount": amount,
                    "buy_price": buy_price,
                    "shares": shares,
                    "order_type": "Manual (Custom)"
                }, f)
            update_virtual_balance(-amount)
        except Exception as e:
            logging.error(f"Failed to sync manual bet: {e}")

        from datetime import datetime
        exec_time = datetime.now().strftime('%H:%M:%S')
        
        msg = (
            f"🎯 *Custom Trade Executed*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"⏰ Time: *{exec_time}*\n"
            f"--------------------------\n"
            f"💰 Amount: *${amount}*\n"
            f"--------------------------\n"
            f"📊 Position: *{direction}*\n"
            f"--------------------------\n"
            f"🪙 Shares: *{shares:.2f}* (@ {buy_price:.2f})\n"
            f"--------------------------\n"
            f"⚙️ Order Type: *Manual Custom*\n"
            f"--------------------------\n"
            f"📌 Market: *{active['question']}*\n"
            f"--------------------------\n"
            f"{'🧪 DRY RUN MODE' if DRY_RUN else '💸 LIVE ORDER PLACED'}\n"
            f"{'No real funds used.' if DRY_RUN else 'Real funds dedicated.'}"
        )
        await msg_waiting.edit_text(text=msg, parse_mode="Markdown")
    else:
        await msg_waiting.edit_text(text="❌ Failed to place order. Check terminal logs.")
    
    return ConversationHandler.END

async def cancel_custom(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Custom trade cancelled.", reply_markup=MAIN_MENU)
    return ConversationHandler.END

# ── Bot Runner ──

def run_telegram_bot():
    if not TELEGRAM_TOKEN:
        logging.error("TELEGRAM_TOKEN not found in .env!")
        return
    
    if os.path.exists("logs/telegram_activity.log"):
        os.remove("logs/telegram_activity.log")
    
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    # Conversation Handler for Manual Trades
    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🎯 Custom (UP|DOWN)$"), handle_custom_start)],
        states={
            WAITING_FOR_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_custom_amount)]
        },
        fallbacks=[CommandHandler("cancel", cancel_custom)],
        per_message=False
    )
    app.add_handler(conv_handler)
    
    # Register other handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset_martingale))
    app.add_handler(MessageHandler(filters.Regex("^📈 Status$"), status))
    app.add_handler(MessageHandler(filters.Regex("^💰 Balance$"), balance))
    app.add_handler(MessageHandler(filters.Regex("^📊 History$"), history))
    app.add_handler(MessageHandler(filters.Regex("^🎯 Manual Trade$"), manual_trade))
    app.add_handler(MessageHandler(filters.Regex("^(🟢 UP|🔴 DOWN) \$[0-9]+$"), handle_fixed_manual_trade))
    app.add_handler(MessageHandler(filters.Regex("^(▶️ START BOT|🛑 STOP BOT)$"), start_stop))
    app.add_handler(MessageHandler(filters.Regex("^🔄 Reset L1$"), reset_martingale))
    app.add_handler(MessageHandler(filters.Regex("^🏆 Performance$"), performance))
    app.add_handler(MessageHandler(filters.Regex("^📉 Live Price$"), live_price))
    app.add_handler(MessageHandler(filters.Regex("^🛠️ Settings$"), settings_command))
    app.add_handler(MessageHandler(filters.Regex("^📊 Daily Report$"), daily_report))
    app.add_handler(MessageHandler(filters.Regex("^🔙 Back$"), back_to_main))
    app.add_handler(MessageHandler(filters.Regex("^🆘 Help$"), help_command))
    app.add_handler(CallbackQueryHandler(button_callback))
    
    # Schedule notification checker (every 5 seconds)
    app.job_queue.run_repeating(check_notifications, interval=5, first=2)
    
    logging.info("Telegram Bot UI Started!")
    app.run_polling()

if __name__ == "__main__":
    run_telegram_bot()
