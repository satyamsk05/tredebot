import os
import json
import logging
import time
import asyncio
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes, ConversationHandler
from dotenv import load_dotenv

from app.db import async_get_last_n_candles, async_get_24h_stats
from app.trading.trader import async_get_balance, async_get_virtual_balance, async_update_virtual_balance
from app.api.btc_api import async_get_active_btc_market, async_get_last_trade_price, async_place_btc_bet
from app.config import INTERVAL, INITIAL_BET_AMOUNT, TELEGRAM_TOKEN, DRY_RUN
from app.trading.martingale import BET_SEQUENCE, Martingale
from app.bot.strings import t, get_config, get_theme

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
    btn_text = t("btn_start") if paused else t("btn_stop")
    return ReplyKeyboardMarkup(
        [
            [btn_text],
            [t("btn_status"), t("btn_balance")],
            [t("btn_history"), t("btn_live")],
            [t("btn_manual"), t("btn_settings")]
        ],
        resize_keyboard=True
    )

def get_settings_menu():
    config = {"btc_5m": True, "btc_15m": False}
    if os.path.exists("data/market_config.json"):
        try:
            with open("data/market_config.json", "r") as f:
                config = json.load(f)
        except: pass
    
    m5 = "✅" if config.get("btc_5m") else "❌"
    m15 = "✅" if config.get("btc_15m") else "❌"
    
    return ReplyKeyboardMarkup(
        [
            [f"{m5} BTC 5M", f"{m15} BTC 15M"],
            [t("btn_perf"), t("btn_reset")],
            [t("btn_report"), t("btn_appearance")],
            [t("btn_back")]
        ],
        resize_keyboard=True
    )

def get_appearance_menu():
    config = get_config()
    lang_flag = "🇮🇳" if config.get("language") == "hi" else "🇺🇸"
    theme_icon = "⚡️" if config.get("theme") == "neon" else "📜"
    
    return ReplyKeyboardMarkup(
        [
            [f"{lang_flag} {t('btn_lang')}", f"{theme_icon} {t('btn_theme')}"],
            [t("btn_nick"), t("btn_back")]
        ],
        resize_keyboard=True
    )

def get_manual_menu(tf=5):
    return ReplyKeyboardMarkup(
        [
            [f"🟢 UP $5", f"🟢 UP $10"],
            [f"🔴 DOWN $5", f"🔴 DOWN $10"],
            [f"🎯 {t('btn_custom')} UP", f"🎯 {t('btn_custom')} DOWN"],
            [f"⏱️ {t('btn_tf')}: {tf}M", t("btn_back")]
        ],
        resize_keyboard=True
    )

WAITING_FOR_AMOUNT = 1
WAITING_FOR_NICKNAME = 2

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
    
    welcome = t("welcome", 
        bet=INITIAL_BET_AMOUNT, 
        mode='DRY RUN' if DRY_RUN else 'LIVE'
    )
    
    await update.message.reply_text(welcome, reply_markup=get_main_menu(), parse_mode="Markdown")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("Status", update)
    save_chat_id(update.effective_chat.id)
    
    now_ts = int(time.time())
    interval_sec = 5 * 60
    next_boundary = ((now_ts // interval_sec) * interval_sec) + interval_sec
    seconds_until_next = next_boundary - now_ts
    mins, secs = divmod(seconds_until_next, 60)
    
    mg = Martingale()
    
    paused = os.path.exists("pause.flag")
    status_icon = t("btn_stop") if not paused else t("btn_start")
    
    config = {"btc_5m": True, "btc_15m": False}
    if os.path.exists("data/market_config.json"):
        try:
            with open("data/market_config.json", "r") as f:
                config = json.load(f)
        except: pass
    
    msg = t("status_header") + "\n\n"
    msg += f"📡 Status: {status_icon}\n"
    msg += f"⏳ Next 5m: *{mins:02d}:{secs:02d}s*\n"
    msg += f"--------------------------\n"

    if config.get("btc_5m"):
        step5 = mg.get_step("BTC_5m")
        bet5 = mg.get_bet("BTC_5m")
        msg += f"📊 *BTC 5M*: Level {step5+1} | ${bet5}\n"
    
    if config.get("btc_15m"):
        step15 = mg.get_step("BTC_15m")
        bet15 = mg.get_bet("BTC_15m")
        msg += f"📊 *BTC 15M*: Level {step15+1} | ${bet15}\n"

    if not config.get("btc_5m") and not config.get("btc_15m"):
        msg += "⚠️ *No active timeframes!*\n"

    msg += f"\n🧪 Mode: *{'SIMULATION' if DRY_RUN else 'LIVE'}*\n"
    msg += f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    
    await update.message.reply_text(msg, parse_mode="Markdown")

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("Balance", update)
    save_chat_id(update.effective_chat.id)
    
    usdc_bal = await async_get_balance()
    v_bal = await async_get_virtual_balance()
    msg = t("balance_header") + "\n\n"
    msg += f"🧪 Virtual: *${v_bal:,.2f}*\n"
    msg += f"--------------------------\n"
    msg += f"💸 USDC: *${usdc_bal:,.2f}*\n"
    msg += f"🏦 Chain: *Polygon (POS)*\n"
    msg += f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("History", update)
    save_chat_id(update.effective_chat.id)
    
    tf = context.user_data.get("history_tf", 5)
    closes = await async_get_last_n_candles(10, interval=tf)
    
    if not closes:
        await update.message.reply_text(
            f"📂 *No {tf}m candle history found.*", 
            reply_markup=get_history_keyboard(tf),
            parse_mode="Markdown"
        )
        return
    
    msg = t("history_header", tf=tf) + "\n\n"
    seen_ts = set()
    filtered_closes = []
    
    for c in closes:
        ts = c.get('timestamp')
        if ts not in seen_ts:
            seen_ts.add(ts)
            filtered_closes.append(c)

    theme = get_theme()
    for i, c in enumerate(reversed(filtered_closes)):
        p = c['close_price']
        from datetime import datetime
        time_str = datetime.fromtimestamp(c['timestamp']).strftime('%H:%M')
        time_display = f" 🕒 `{time_str}`"
            
        icon = theme["up"] if p > 0.5 else theme["down"]
        direction = "UP" if p > 0.5 else "DOWN"
        msg += f"{icon} `#{i+1:02d}` | *{direction}* | `{p:.4f}`{time_display}\n"
    
    msg += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━"
    await update.message.reply_text(msg, reply_markup=get_history_keyboard(tf), parse_mode="Markdown")

def get_history_keyboard(tf):
    other_tf = 15 if tf == 5 else 5
    return ReplyKeyboardMarkup(
        [
            [f"📊 {t('btn_switch_to')} {other_tf}M"],
            [t("btn_back")]
        ],
        resize_keyboard=True
    )

async def toggle_history_tf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("Toggle History TF", update)
    text = update.message.text
    new_tf = 15 if "15M" in text else 5
    context.user_data["history_tf"] = new_tf
    await history(update, context)

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
    
    tf = context.user_data.get("perf_tf", 5)
    mg = Martingale()
    label = "BTC_5m" if tf == 5 else "BTC_15m"
    step = mg.get_step(label)
    bet = mg.get_bet(label)
    
    # Build sequence display
    seq_display = ""
    for i, b in enumerate(BET_SEQUENCE):
        if i == step:
            seq_display += f"➡️ *${b}*  "
        else:
            seq_display += f"${b}  "
    
    msg = t("matrix_header", tf=tf) + "\n\n"
    msg += f"📈 Position: *Level {step+1}*\n"
    msg += f"💰 Risking: *${bet}*\n"
    msg += f"--------------------------\n"
    msg += "Strategy Sequence:\n"
    msg += f"`{seq_display.replace('*', '')}`\n\n"
    msg += f"Current: *{bet} USD*"
    
    keyboard = ReplyKeyboardMarkup(
        [
            [f"🏆 {t('btn_switch_to')} {'15' if tf==5 else '5'}M"],
            [t("btn_back")]
        ],
        resize_keyboard=True
    )
    await update.message.reply_text(msg, reply_markup=keyboard, parse_mode="Markdown")

async def toggle_perf_tf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    context.user_data["perf_tf"] = 15 if "15M" in text else 5
    await performance(update, context)

async def live_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("Live Price", update)
    save_chat_id(update.effective_chat.id)
    
    tf = context.user_data.get("live_price_tf", 5)
    active = await async_get_active_btc_market(offset_minutes=0, interval=tf)
    if not active:
        await update.message.reply_text(f"❌ No active {tf}m market found.")
        return
    
    yes_price = await async_get_last_trade_price(active['yes_token'])
    no_price = await async_get_last_trade_price(active['no_token'])
    
    msg = t("odds_header", tf=tf) + "\n\n"
    msg += f"📌 {active['question']}\n"
    msg += f"--------------------------\n"
    msg += f"🟢 YES (UP):   *{yes_price}*\n"
    msg += f"🔴 NO (DOWN):  *{no_price}*\n"
    msg += f"━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    keyboard = ReplyKeyboardMarkup(
        [
            [f"📉 {t('btn_switch_to')} {'15' if tf==5 else '5'}M {t('btn_odds')}"],
            [t("btn_back")]
        ],
        resize_keyboard=True
    )
    await update.message.reply_text(msg, reply_markup=keyboard, parse_mode="Markdown")

async def toggle_live_price_tf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("Toggle LP TF", update)
    text = update.message.text
    context.user_data["live_price_tf"] = 15 if "15M" in text else 5
    await live_price(update, context)

async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("Settings", update)
    save_chat_id(update.effective_chat.id)
    
    msg = t("settings_header") + "\n\n"
    msg += f"🎯 Strategy: *BTC High Frequency*\n"
    msg += f"⏱️ Window:   *{INTERVAL} Minutes*\n"
    msg += f"🧪 State:    *{'SIMULATION' if DRY_RUN else 'LIVE'}*\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    msg += "Choose an option below 👇"
    
    await update.message.reply_text(msg, reply_markup=get_settings_menu(), parse_mode="Markdown")

async def appearance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("Appearance", update)
    await update.message.reply_text(
        t("appearance_header"), 
        reply_markup=get_appearance_menu(), 
        parse_mode="Markdown"
    )

async def toggle_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("Toggle Language", update)
    config = get_config()
    new_lang = "hi" if config.get("language") == "en" else "en"
    config["language"] = new_lang
    
    with open("data/ui_config.json", "w") as f:
        json.dump(config, f, indent=4)
        
    await update.message.reply_text(t("msg_lang_changed"), reply_markup=get_appearance_menu(), parse_mode="Markdown")

async def toggle_theme(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("Toggle Theme", update)
    config = get_config()
    new_theme = "neon" if config.get("theme") == "classic" else "classic"
    config["theme"] = new_theme
    
    with open("data/ui_config.json", "w") as f:
        json.dump(config, f, indent=4)
        
    await update.message.reply_text(
        t("msg_theme_changed", theme=new_theme.upper()), 
        reply_markup=get_appearance_menu(), 
        parse_mode="Markdown"
    )

async def start_nick_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("Start Nick Change", update)
    await update.message.reply_text(t("msg_enter_nick"), parse_mode="Markdown")
    return WAITING_FOR_NICKNAME

async def handle_nick_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_nick = update.message.text.strip()
    log_activity(f"Set Nick: {new_nick}", update)
    
    config = get_config()
    config["nickname"] = new_nick
    
    with open("data/ui_config.json", "w") as f:
        json.dump(config, f, indent=4)
        
    await update.message.reply_text(
        t("msg_nick_changed", nickname=new_nick), 
        reply_markup=get_appearance_menu(), 
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def toggle_market_keyboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text # e.g. "✅ BTC 5M"
    m_id = "btc_15m" if "15M" in text else "btc_5m"
    
    log_activity(f"Toggle {m_id}", update)
    
    config = {"btc_5m": True, "btc_15m": False}
    if os.path.exists("data/market_config.json"):
        try:
            with open("data/market_config.json", "r") as f:
                config = json.load(f)
        except: pass
    
    config[m_id] = not config.get(m_id, False)
    
    with open("data/market_config.json", "w") as f:
        json.dump(config, f)
    
    status_label = "ENABLED" if config[m_id] else "DISABLED"
    await update.message.reply_text(
        f"⚙️ *{m_id.replace('_', ' ').upper()}* is now *{status_label}*",
        reply_markup=get_settings_menu(),
        parse_mode="Markdown"
    )

# Removed markets_command since we shifted to ReplyKeyboard toggles

async def daily_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("Daily Report", update)
    save_chat_id(update.effective_chat.id)
    
    stats5 = await async_get_24h_stats(interval=5)
    stats15 = await async_get_24h_stats(interval=15)
    
    def format_tf(s, tf):
        total = s["wins"] + s["losses"]
        wr = (s["wins"] / total * 100) if total > 0 else 0
        return (
            f"📊 *BTC {tf}M STATS*\n"
            f"✅ W: *{s['wins']}* | ❌ L: *{s['losses']}* | 🔥 WR: *{wr:.1f}%*\n"
            f"💰 Net: *{'+' if s['total_profit'] >=0 else ''}${s['total_profit']:.2f}*\n"
        )

    msg = t("btn_report").upper() + "\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    msg += f"{format_tf(stats5, 5)}"
    msg += f"---------------------------\n"
    msg += f"{format_tf(stats15, 15)}"
    msg += f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    msg += f"💰 *TOTAL PROFIT: ${stats5['total_profit'] + stats15['total_profit']:.2f}*\n"
    msg += f"🌊 Total Volume: ${stats5['total_volume'] + stats15['total_volume']:.2f}\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def back_to_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("Back", update)
    await update.message.reply_text(t("btn_back") + "...", reply_markup=get_main_menu(), parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("Help", update)
    save_chat_id(update.effective_chat.id)
    theme = get_theme()
    
    msg = (
        "🆘 *COMMAND CENTER GUIDE*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📈 *{t('btn_status')}*    — Node heartbeat\n"
        f"💰 *{t('btn_balance')}*   — Financial snapshot\n"
        f"📊 *{t('btn_history')}*   — Market execution log\n"
        "---------------------------\n"
        f"📉 *{t('btn_live')}*      — Odds analysis\n"
        f"🎯 *{t('btn_manual')}*    — Direct injection\n"
        f"🏆 *{t('btn_perf')}*    — Martingale levels\n"
        f"⏱️ *Control*   — Toggle execution\n\n"
        f"_Need help? Contact support or type /start_"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

# ── Manual Trade (with custom amount) ──

async def manual_trade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("Manual Trade", update)
    save_chat_id(update.effective_chat.id)
    
    tf = context.user_data.get("manual_tf", 5)
    active = await async_get_active_btc_market(offset_minutes=0, interval=tf)
    market_name = active['question'] if active else "Unknown Market"
    
    msg = (
        "🎯 *MANUAL TRADE CENTER*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"⏱️ Selected TF: *{tf}M*\n"
        f"📌 Market: *{market_name}*\n\n"
        "Select an amount to inject a trade instantly. 👇"
    )
    
    await update.message.reply_text(msg, reply_markup=get_manual_menu(tf), parse_mode="Markdown")

async def toggle_manual_tf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("Toggle Manual TF", update)
    current_tf = context.user_data.get("manual_tf", 5)
    new_tf = 15 if current_tf == 5 else 5
    context.user_data["manual_tf"] = new_tf
    
    active = await async_get_active_btc_market(offset_minutes=0, interval=new_tf)
    market_name = active['question'] if active else "Unknown Market"
    
    msg = (
        "🎯 *MANUAL TRADE CENTER*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"⏱️ Selected TF: *{new_tf}M*\n"
        f"📌 Market: *{market_name}*\n\n"
        "Timeframe switched successfully! 👇"
    )
    await update.message.reply_text(msg, reply_markup=get_manual_menu(new_tf), parse_mode="Markdown")

async def handle_fixed_manual_trade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text # e.g. "🟢 UP $5"
    log_activity(f"Fixed MT: {text}", update)
    
    # Parse text
    direction_str = "up" if "UP" in text else "down"
    try:
        amount = float(text.split("$")[1])
    except:
        return

    tf = context.user_data.get("manual_tf", 5)
    active = await async_get_active_btc_market(offset_minutes=0, interval=tf)
    if not active:
        await update.message.reply_text(f"❌ No active {tf}m market found.")
        return
    
    if direction_str == "up":
        token = active['yes_token']
        direction = "YES (UP)"
        icon = "🟢"
    else:
        token = active['no_token']
        direction = "NO (DOWN)"
        icon = "🔴"
    
    buy_price = await async_get_last_trade_price(token)
    if not buy_price or buy_price <= 0:
        buy_price = 0.50
    shares = amount / buy_price
    
    msg_waiting = await update.message.reply_text(f"⏳ Placing *${amount}* on *{direction}*...", parse_mode="Markdown")
    
    success = await async_place_btc_bet(token, amount)
    
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
            await async_update_virtual_balance(-amount)
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
    
    if not data.startswith(("mt_", "toggle_")):
        return
    
    if data.startswith("toggle_"):
        m_id = data.replace("toggle_", "")
        config = {"btc_5m": True, "btc_15m": False}
        if os.path.exists("data/market_config.json"):
            try:
                with open("data/market_config.json", "r") as f:
                    config = json.load(f)
            except: pass
        
        # Toggle
        config[m_id] = not config.get(m_id, False)
        
        # Save
        with open("data/market_config.json", "w") as f:
            json.dump(config, f)
            
        # Update message
        def get_toggle(m): return "✅" if config.get(m) else "❌"
        keyboard = [
            [
                InlineKeyboardButton(f"{get_toggle('btc_5m')} BTC 5m", callback_data="toggle_btc_5m"),
                InlineKeyboardButton(f"{get_toggle('btc_15m')} BTC 15m", callback_data="toggle_btc_15m")
            ]
        ]
        msg = (
            "⚙️ *MARKET CONFIGURATION*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Enable or disable specific timeframes. The bot will trade all active ones simultaneously.\n\n"
            f"• BTC 5m:  *{'ENABLED' if config.get('btc_5m') else 'DISABLED'}*\n"
            f"• BTC 15m: *{'ENABLED' if config.get('btc_15m') else 'DISABLED'}*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
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
    
    active = await async_get_active_btc_market(offset_minutes=0)
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
    
    buy_price = await async_get_last_trade_price(token)
    if not buy_price or buy_price <= 0:
        buy_price = 0.50
    shares = amount / buy_price
    
    log_activity(f"MT: {direction} ${amount}", update)
    await query.edit_message_text(text=f"⏳ Placing *${amount}* on *{direction}*...", parse_mode="Markdown")
    
    success = await async_place_btc_bet(token, amount)
    
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
            await async_update_virtual_balance(-amount)
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
    tf = context.user_data.get("manual_tf", 5)
    
    try:
        amount = float(amount_text)
        if amount <= 0:
            raise ValueError()
    except ValueError:
        await update.message.reply_text("❌ Invalid amount. Please enter a positive number (e.g. `5.5`):")
        return WAITING_FOR_AMOUNT

    active = await async_get_active_btc_market(offset_minutes=0, interval=tf)
    if not active:
        await update.message.reply_text(f"❌ No active {tf}m market found.")
        return ConversationHandler.END
    
    if direction_str == "up":
        token = active['yes_token']
        direction = "YES (UP)"
        icon = "📈"
    else:
        token = active['no_token']
        direction = "NO (DOWN)"
        icon = "📉"
    
    buy_price = await async_get_last_trade_price(token)
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
    
    success = await async_place_btc_bet(token, amount)
    
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
            await async_update_virtual_balance(-amount)
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
    await update.message.reply_text("❌ Custom trade cancelled.", reply_markup=get_main_menu())
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
    manual_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🎯 Custom (UP|DOWN)$"), handle_custom_start)],
        states={WAITING_FOR_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_custom_amount)]},
        fallbacks=[CommandHandler("cancel", cancel_custom)],
        per_message=False
    )
    app.add_handler(manual_conv)

    # Conversation Handler for Nickname
    nick_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(f"^.*{t('btn_nick')}$"), start_nick_change)],
        states={WAITING_FOR_NICKNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_nick_change)]},
        fallbacks=[MessageHandler(filters.Regex(f"^{t('btn_back')}$"), appearance_command)],
        per_message=False
    )
    app.add_handler(nick_conv)
    
    # Register other handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset_martingale))
    
    # Buttons with dynamic language support (Regex matching both EN/HI)
    from app.bot.strings import STRINGS
    def r(key):
        patterns = []
        for lang in STRINGS:
            patterns.append(STRINGS[lang].get(key, key))
        return f"^.*({'|'.join(patterns)}).*$"

    app.add_handler(MessageHandler(filters.Regex(r("btn_back")), back_to_main))

    app.add_handler(MessageHandler(filters.Regex(r("btn_status")), status))
    app.add_handler(MessageHandler(filters.Regex(r("btn_balance")), balance))
    app.add_handler(MessageHandler(filters.Regex(r("btn_history")), history))
    app.add_handler(MessageHandler(filters.Regex(r("btn_manual")), manual_trade))
    app.add_handler(MessageHandler(filters.Regex(r("btn_settings")), settings_command))
    app.add_handler(MessageHandler(filters.Regex(r("btn_perf")), performance))
    app.add_handler(MessageHandler(filters.Regex(r("btn_reset")), reset_martingale))
    app.add_handler(MessageHandler(filters.Regex(r("btn_report")), daily_report))
    app.add_handler(MessageHandler(filters.Regex(r("btn_appearance")), appearance_command))
    app.add_handler(MessageHandler(filters.Regex(r("btn_lang")), toggle_language))
    app.add_handler(MessageHandler(filters.Regex(r("btn_theme")), toggle_theme))
    app.add_handler(MessageHandler(filters.Regex(r("btn_live")), live_price))

    app.add_handler(MessageHandler(filters.Regex("^(🟢 UP|🔴 DOWN) \$[0-9]+$"), handle_fixed_manual_trade))
    app.add_handler(MessageHandler(filters.Regex("^(▶️ START BOT|🛑 STOP BOT|▶️ बॉट शुरू करें|🛑 बॉट रोकें)$"), start_stop))
    app.add_handler(MessageHandler(filters.Regex("^📉 Switch to (5|15)M Odds$"), toggle_live_price_tf))
    app.add_handler(MessageHandler(filters.Regex("^(✅|❌) BTC (5M|15M)$"), toggle_market_keyboard))
    app.add_handler(MessageHandler(filters.Regex("^⏱️ TF: (5|15)M$"), toggle_manual_tf))
    app.add_handler(MessageHandler(filters.Regex("^📊 Switch to (5|15)M$"), toggle_history_tf))
    app.add_handler(MessageHandler(filters.Regex("^🏆 Switch to (5|15)M$"), toggle_perf_tf))
    app.add_handler(MessageHandler(filters.Regex("^🆘 Help$"), help_command))
    app.add_handler(CallbackQueryHandler(button_callback))
    
    # Schedule notification checker (every 5 seconds)
    app.job_queue.run_repeating(check_notifications, interval=5, first=2)
    
    logging.info("Telegram Bot UI Started!")
    app.run_polling()

if __name__ == "__main__":
    run_telegram_bot()
