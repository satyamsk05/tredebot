import os
import json
import logging
import time
import asyncio
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes, ConversationHandler
from dotenv import load_dotenv

from app.db import async_get_last_n_candles, async_get_stats_period, async_get_recent_trades
from app.trading.trader import async_get_balance, async_get_virtual_balance, async_update_virtual_balance
from app.api.polymarket_api import async_get_active_market, async_get_last_trade_price, async_place_bet
from app.config import INTERVAL, INITIAL_BET_AMOUNT, TELEGRAM_TOKEN, DRY_RUN, COINS
from app.trading.martingale import BET_SEQUENCE, Martingale
from app.bot.strings import t, get_config, get_theme, STRINGS

# Ensure logs directory exists
os.makedirs("logs", exist_ok=True)

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

# Global Cache for Winnings (to show on Main Menu)
_cached_unclaimed = 0.0
# Track start time for 'Session-Only' Trends (Aligned to 15m interval, looking back 1 hour for warm start)
BOT_START_TIME = ((int(time.time()) // 900) * 900) - 3600

def log_info(msg):
    logging.info(f"UI INFO: {msg}")

def log_error(msg):
    logging.error(f"UI ERROR: {msg}")

def log_activity(action, update: Update = None):
    # Logs both to the main log and a streamlined activity file
    user = update.effective_user.first_name if update and update.effective_user else "Unknown"
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} - {user}: {action}\n"
    logging.info(f"ACTIVITY: {user} - {action}")
    try:
        with open("logs/telegram_activity.log", "a") as f:
            f.write(line)
    except Exception:
        pass

def save_chat_id(chat_id):
    try:
        with open("data/chat_id.txt", "w") as f:
            f.write(str(chat_id))
    except Exception:
        pass

def get_main_menu():
    paused = os.path.exists("pause.flag")
    start_stop_btn = t("btn_start") if paused else t("btn_stop")
    
    # Consolidated 3-column grid
    rows = [
        [start_stop_btn, t("btn_balance"), t("btn_live")],
        [t("btn_status"), t("btn_manual"), t("btn_history")],
        [t("btn_trends"), t("btn_settings")]
    ]
    
    # Add Claim if winnings exist
    global _cached_unclaimed
    if _cached_unclaimed > 0:
        rows.append([t("btn_claim")])
        
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

def get_settings_menu():
    buttons = [
        [t("btn_report"), "📅 7-Day Stats"],
        [t("btn_help"), t("btn_back")]
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)




def get_manual_menu(tf=15):
    return ReplyKeyboardMarkup(
        [
            [f"🟢 UP $3", f"🔴 DOWN $3"],
            [f"🟢 UP $10", f"🔴 DOWN $10"],
            [f"🎯 {t('btn_custom')} UP", f"🎯 {t('btn_custom')} DOWN"],
            [t("btn_back")]
        ],
        resize_keyboard=True
    )

WAITING_FOR_AMOUNT = 1
WAITING_FOR_LIMIT = 3
WAITING_FOR_CONFIRM = 4

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
    
    # Helper: convert lightweight Markdown (*bold*, `code`) to HTML and escape safely
    import re, html
    def _md_to_html(msg: str) -> str:
        s = html.escape(msg)
        s = re.sub(r'\*(.*?)\*', r'<b>\1</b>', s)
        s = re.sub(r'`(.*?)`', r'<code>\1</code>', s)
        return s
    
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
                        text=_md_to_html(msg),
                        parse_mode="HTML"
                    )
    except Exception as e:
        logging.error(f"Notification check error: {e}")

    # --- ALSO: Refresh Winning Cache every 15s (approx) ---
    if not hasattr(check_notifications, "_last_win_check"):
        check_notifications._last_win_check = 0 # Forces immediate check on first run
    
    now = time.time()
    if now - check_notifications._last_win_check >= 15 or check_notifications._last_win_check == 0:
        check_notifications._last_win_check = now
        try:
            from app.api.polymarket_api import fetch_redeemable_positions_from_api
            from app.config import FUNDER_ADDRESS, WALLET_ADDRESS
            
            # Scan both primary and legacy funder for a smooth transition
            wallets = list(set(filter(None, [WALLET_ADDRESS, FUNDER_ADDRESS])))
            total = 0.0
            for w in wallets:
                r = await fetch_redeemable_positions_from_api(w)
                total += sum(p['payout'] for p in r)
            
            global _cached_unclaimed
            _cached_unclaimed = total
            if _cached_unclaimed > 0:
                logging.info(f"Background check: Found ${total:.2f} winnings.")
        except:
            pass

# ── Command Handlers ──

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("/start", update)
    log_info("TG Handler: /start hit")
    save_chat_id(update.effective_chat.id)
    
    config = get_config()
    welcome = t("welcome", 
        bet=INITIAL_BET_AMOUNT, 
        mode='DRY RUN' if DRY_RUN else 'LIVE',
        nickname=config.get("nickname", "OGBOT").upper()
    )
    
    await update.message.reply_text(welcome, reply_markup=get_main_menu(), parse_mode="Markdown")

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🏓 *PONG!* Bot is alive and well.", parse_mode="Markdown")

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("Button: Balance", update)
    log_info("TG Handler: balance hit")
    save_chat_id(update.effective_chat.id)
    
    from app.api.polymarket_api import fetch_redeemable_positions_from_api
    from app.config import WALLET_ADDRESS, FUNDER_ADDRESS
    from app.trading.trader import async_get_balance, async_get_virtual_balance
    
    # 1. Fetch Balances
    usdc_bal = await async_get_balance() 
    virt = await async_get_virtual_balance()
    
    # 2. Scan both primary and legacy funder for winnings
    wallets = list(set(filter(None, [WALLET_ADDRESS, FUNDER_ADDRESS])))
    total_unclaimed = 0
    all_redeemables = []
    
    for w in wallets:
        try:
            r = await fetch_redeemable_positions_from_api(w)
            for p in r: p['wallet'] = w
            all_redeemables.extend(r)
        except: pass
        
    total_unclaimed = sum(p['payout'] for p in all_redeemables)

    msg = (
        "💰  *FINANCIAL OVERVIEW*  💰\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📊  *Virt:*    `${virt}`\n"
        f"💵  *USDC:*    `${usdc_bal}`\n"
    )
    if FUNDER_ADDRESS and FUNDER_ADDRESS.lower() != WALLET_ADDRESS.lower():
        msg += f"👛  *Wallet:*  `{FUNDER_ADDRESS[:6]}...{FUNDER_ADDRESS[-4:]}`\n"
    else:
        msg += f"👛  *Wallet:*  `{WALLET_ADDRESS[:6]}...{WALLET_ADDRESS[-4:]}`\n"
        
    msg += "━━━━━━━━━━━━━━━━━━━━\n"
    
    if total_unclaimed > 0:
        msg += f"🎁  *Pending:*  `${total_unclaimed:.2f}`\n"
        msg += "👉 _Use button below to claim._"
    else:
        msg += "✨ _All winnings claimed!_"
    
    msg += "\n━━━━━━━━━━━━━━━━━━━━"
    
    global _cached_unclaimed
    _cached_unclaimed = total_unclaimed

    # Consistent grid for sub-menus too
    buttons = [
        [t("btn_status"), t("btn_balance"), t("btn_history")],
        [t("btn_live"), t("btn_manual"), t("btn_report")],
        [t("btn_back")]
    ]
    
    if total_unclaimed > 0:
        buttons.insert(2, [t("btn_claim")])

    logging.info("Sending balance response to user.")
    await update.message.reply_text(
        msg, 
        reply_markup=get_main_menu(), # No more sub-menu with 2nd Back button
        parse_mode="Markdown"
    )

async def claim_winnings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from app.api.polymarket_api import fetch_redeemable_positions_from_api
    from app.trading.trader import async_redeem_winnings
    from app.config import WALLET_ADDRESS, FUNDER_ADDRESS
    from app.db import get_db_connection
    
    # Scan both primary and legacy funder (Transition Support)
    wallets = list(set(filter(None, [WALLET_ADDRESS, FUNDER_ADDRESS])))
    all_redeemables = []
    
    for w in wallets:
        try:
            r = await fetch_redeemable_positions_from_api(w)
            for p in r: p['wallet'] = w
            all_redeemables.extend(r)
        except: pass
    
    if not all_redeemables:
        await update.message.reply_text(t("msg_no_claims"))
        return

    total_usd = sum(p['payout'] for p in all_redeemables)
    status_msg = await update.message.reply_text(f"⏳ *Claiming ${total_usd:.2f} USDC.e...*", parse_mode="Markdown")
    
    total_claimed = 0
    success_count = 0
    
    for pos in all_redeemables:
        cond_id = pos['condition_id']
        idx = pos['outcome_index']
        wallet = pos['wallet']
        
        logging.info(f"Claiming winnings for {wallet} (Market: {cond_id[:10]})...")
        success = await async_redeem_winnings(cond_id, idx, wallet)
        
        if success:
            total_claimed += pos['payout']
            success_count += 1
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("UPDATE trades SET claimed = 1 WHERE market_id = ?", (cond_id,))
                conn.commit()
                conn.close()
            except: pass
        else:
            logging.error(f"Redemption failed for market {cond_id}")

    if success_count > 0:
        await status_msg.edit_text(f"✅ *Redemption Successful!*\nTotal Claimed: ${total_claimed:.2f} USDC.e", parse_mode="Markdown")
    else:
        await status_msg.edit_text("❌ *Redemption Failed.*\nCheck terminal logs for details (likely gasmatic issues).", parse_mode="Markdown")
            
    if success_count > 0:
        global _cached_unclaimed
        _cached_unclaimed = 0 # Reset cache after claim
        await status_msg.edit_text(t("msg_claim_done", amount=f"{total_claimed:.2f}"), parse_mode="Markdown")
        if success_count < len(all_redeemables):
            await update.message.reply_text("⚠️ Some redemptions failed. This usually happens if the account lacks native gas (MATIC) for the transaction.")
    else:
        await status_msg.edit_text("❌ Redemption failed. Check `logs/telegram_bot.log` for the exact error.")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("Button: Status", update)
    log_info("TG Handler: status hit")
    save_chat_id(update.effective_chat.id)
    
    status_icon = "🛑 STOPPED" if os.path.exists("pause.flag") else "▶️ RUNNING"

    now_ts = int(time.time())
    interval_sec = 15 * 60
    next_boundary = ((now_ts // interval_sec) * interval_sec) + interval_sec
    seconds_until_next = next_boundary - now_ts
    mins, secs = divmod(seconds_until_next, 60)
    
    mg = Martingale()

    msg = (
        f"🖥️  *OG BOTS STATUS*  🖥️\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🚦 *Engine:* {status_icon}\n"
        f"🛠️ *Mode:*   {'LIVE 💸' if not DRY_RUN else 'SIMULATION 🧪'}\n"
        f"⏳ *Next:*    `{mins:02d}:{secs:02d}`s\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
    )
    
    for c in COINS:
        label = f"{c}_15m"
        step = mg.get_step(label)
        bet = mg.get_bet(label)
        msg += f"🌟 *{c}*\n"
        msg += f"  🪜 *Level:*  `L{step+1}`\n"
        msg += f"  💰 *Next:*   `${bet}`\n"
        msg += f"┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
        
    msg += "━━━━━━━━━━━━━━━━━━━━"
    
    await update.message.reply_text(msg, reply_markup=get_main_menu(), parse_mode="Markdown")


async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("History", update)
    save_chat_id(update.effective_chat.id)
    
    trades = await async_get_recent_trades(12)
    
    msg = (
        "📜  *RECENT TRADE LOGS*  📜\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
    )
    
    if not trades:
        msg += "📂 *No trade history found yet.*\n"
    else:
        for t_data in trades:
            m_id = t_data['market_id']
            coin = m_id.split("-")[0].upper() if "-" in m_id else "SOL"
            
            from datetime import datetime
            dt = datetime.fromtimestamp(t_data['timestamp'])
            time_str = dt.strftime('%m/%d %H:%M')
            
            result_icon = "✅ WIN" if t_data['result'] == "WIN" else "❌ LOSS"
            side_icon = "🟢 UP" if t_data['direction'] == "YES" else "🔴 DOWN"
            
            profit = t_data['payout'] - t_data['amount'] if t_data['result'] == "WIN" else -t_data['amount']
            profit_str = f"{'+' if profit >= 0 else ''}${profit:.2f}"
            
            msg += f"🗓 `{time_str}`\n"
            msg += f"🪙 *{coin}* | {side_icon} | {result_icon}\n"
            msg += f"💰 *PnL:* `{profit_str}`\n"
            msg += "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
    
    msg += "━━━━━━━━━━━━━━━━━━━━"
    await update.message.reply_text(msg, reply_markup=get_main_menu(), parse_mode="Markdown")

async def trends(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("Trends", update)
    save_chat_id(update.effective_chat.id)
    
    tf = 15
    msg = f"📊 *{tf}M MARKET TRENDS (Last 10)*\n━━━━━━━━━━━━━━━━━━━━\n"
    
    async def fetch_candles(c):
        active = await async_get_active_market(coin=c, interval=tf)
        if not active: return (c, [], 0)
        try:
            candles = await async_get_last_n_candles(10, interval=tf, coin=c, min_ts=BOT_START_TIME)
            last_ts = candles[-1]['timestamp'] if candles else 0
        except Exception as e:
            logging.error(f"Error fetching candles for {c}: {e}")
            candles = []
            last_ts = 0
        return (c, candles, last_ts)

    tasks = [fetch_candles(c) for c in COINS]
    results = await asyncio.gather(*tasks)
    
    from datetime import datetime
    for c, candles, last_ts in results:
        trend_str = ""
        # Reverse to show most recent on the right
        for candle in candles[::-1]:
            price = candle.get('close_price', 0.5)
            if price >= 0.5:
                trend_str += "🟢"
            else:
                trend_str += "🔴"
        
        if not trend_str:
            trend_str = "N/A"
        
        time_label = " (N/A)"
        if last_ts > 0:
            diff_mins = int((time.time() - last_ts) / 60)
            dt = datetime.fromtimestamp(last_ts)
            time_label = f" ({dt.strftime('%H:%M')} - {diff_mins}m ago)"
            
        msg += f" {c}{time_label}\n"
        msg += f" ▎ `{trend_str}`\n"
        msg += "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"

    msg += "━━━━━━━━━━━━━━━━━━━━"
    await update.message.reply_text(msg, reply_markup=get_main_menu(), parse_mode="Markdown")

def get_history_keyboard(tf):
    return ReplyKeyboardMarkup(
        [
            [t("btn_back")]
        ],
        resize_keyboard=True
    )


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
    # Reset SOL 15m
    mg.win("SOL_15m")
    
    msg = (
        "🔄 *MARTINGALE RESET*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "✨ *Reset:* All levels → L1\n"
        "🚀 *Next:* Fresh start\n"
        "━━━━━━━━━━━━━━━━━━"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


# Performance and toggles removed


# Timeframe switchers removed

async def toggle_live_price_tf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("Refresh Live Price", update)
    await live_price(update, context)

async def live_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("Live Price", update)
    context.user_data["current_menu"] = "live"
    save_chat_id(update.effective_chat.id)
    
    tf = 15
    msg = f"📉 *{tf}M LIVE MULTI-ODDS*\n━━━━━━━━━━━━━━━━━━\n"
    
    async def fetch_odds(c):
        active = await async_get_active_market(coin=c, offset_minutes=0, interval=tf)
        if not active: return None
        y = await async_get_last_trade_price(active['yes_token'])
        n = await async_get_last_trade_price(active['no_token'])
        return (c, y, n)
        
    tasks = [fetch_odds(c) for c in COINS]
    results = await asyncio.gather(*tasks)
    
    found = False
    for res in results:
        if res:
            found = True
            c, y, n = res
            msg += f"🌟 *{c}*\n"
            msg += f"  🟢 *YES:* `${y:.2f}`  |  🔴 *NO:* `${n:.2f}`\n"
            msg += "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
            
    if not found:
        await update.message.reply_text(f"❌ No active {tf}m markets found.", reply_markup=get_main_menu())
        return
        
    msg += "━━━━━━━━━━━━━━━━━━"
    
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔄 Refresh Prices", callback_data="refresh_live")
    ]])
    
    await update.message.reply_text(msg, reply_markup=keyboard, parse_mode="Markdown")
    # Also reset keyboard to main menu to ensure user isn't stuck
    await update.message.reply_text("👇 Navigation", reply_markup=get_main_menu())

async def daily_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("Daily Report", update)
    save_chat_id(update.effective_chat.id)
    await send_stats_report(update, days=1)

async def weekly_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("Weekly Report", update)
    save_chat_id(update.effective_chat.id)
    await send_stats_report(update, days=7)

async def send_stats_report(update: Update, days=1):
    stats = await async_get_stats_period(days=days)
    
    title = "📊 TODAY'S PERFORMANCE" if days == 1 else "🏛️ 7-DAY PERFORMANCE SUMMARY"
    total = stats["wins"] + stats["losses"]
    wr = (stats["wins"] / total * 100) if total > 0 else 0
    pnl = stats["total_profit"]
    
    msg = (
        f"{title}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"📅 *Period:* `{days} Day(s)`\n"
        f"✅ *Wins:*   `{stats['wins']}`\n"
        f"❌ *Loss:*   `{stats['losses']}`\n"
        f"📊 *WinRate:* `{wr:.1f}%`\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"💹 *Volume:* `${stats['total_volume']:.2f}`\n"
        f"💰 *Total PnL:* ` {'+' if pnl >= 0 else ''}${pnl:.2f} `\n"
        "━━━━━━━━━━━━━━━━━━"
    )
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_main_menu())

async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("Button: Settings", update)
    log_info("TG Handler: settings_command hit")
    save_chat_id(update.effective_chat.id)
    
    msg = (
        f"🛠 *OG BOTS SETTINGS*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"⚙️ *Mode:* {'LIVE 💸' if not DRY_RUN else 'SIMULATION 🧪'}\n"
        "📡 *Strat:* Reversal Alpha\n"
        "⏱ *Window:* 15m Frame\n"
        "━━━━━━━━━━━━━━━━━━"
    )
    
    await update.message.reply_text(msg, reply_markup=get_settings_menu(), parse_mode="Markdown")

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
        f"📉 *{t('btn_live')}*      — Odds analysis\n"
        f"🎯 *{t('btn_manual')}*    — Direct injection\n"
        f"🏆 *{t('btn_perf')}*    — Martingale levels\n"
        "---------------------------\n"
        f"⏱️ *Control*   — Toggle execution\n\n"
        f"_Need help? Contact support or type /start_"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

# ── Manual Trade (with custom amount) ──

async def handle_tf_switch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Consolidated handler to avoid overlapping btn_switch_to matches."""
    menu = context.user_data.get("current_menu", "history")
    if menu == "manual":
        return await toggle_manual_tf(update, context)
    elif menu == "history":
        return await toggle_history_tf(update, context)
    elif menu == "perf":
        return await toggle_perf_tf(update, context)
    elif menu == "live":
        return await toggle_live_price_tf(update, context)
    else:
        # Default to history if unknown
        return await toggle_history_tf(update, context)

async def manual_trade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("Manual Trade", update)
    context.user_data["current_menu"] = "manual"
    save_chat_id(update.effective_chat.id)
            
    tf = 15
    coin = context.user_data.get("manual_coin", "SOL")
    active = await async_get_active_market(coin=coin, interval=tf)
    
    msg = (
        "🎯 *MANUAL TRADE*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"⏰ *Time:* {time.strftime('%H:%M:%S')}\n"
        f"📍 *Market:* {coin} Up/Down\n"
        f"📅 {active.get('question', '').split('Up or Down ')[-1] if active else 'No market'}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Change the coin below, or select an amount to inject 👇"
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{'✅ ' if coin == c else ''}{c}", callback_data=f"set_manual_{c}") for c in COINS]
    ])
    
    await update.message.reply_text(msg, reply_markup=get_manual_menu(tf), parse_mode="Markdown")
    await update.message.reply_text("🪙 Coin Selection:", reply_markup=keyboard)

async def toggle_manual_tf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_activity("Toggle Manual TF", update)
    current_tf = context.user_data.get("manual_tf", 5)
    new_tf = 15 if current_tf == 5 else 5
    context.user_data["manual_tf"] = new_tf
    
    coin = context.user_data.get("manual_coin", "BTC")
    active = await async_get_active_market(coin=coin, interval=new_tf)
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

    tf = context.user_data.get("manual_tf", 15)
    coin = context.user_data.get("manual_coin", "SOL")
    active = await async_get_active_market(coin=coin, interval=tf)
    if not active:
        await update.message.reply_text(f"❌ No active {coin} {tf}m market found.")
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
    
    success = await async_place_bet(token, amount, coin=coin)
    
    if success:
        try:
            with open("data/manual_bet.json", "w") as f:
                signal_dir = "YES" if direction_str == "up" else "NO"
                json.dump({
                    "coin": coin,
                    "market_id": active['market_id'],
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
            "🎯 *MANUAL TRADE*\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"⏰ *Time:* {exec_time}\n"
            f"💰 *Amt:* `${amount}`\n"
            f"↕️ *Side:* {direction}\n"
            f"📊 *Shares:* `{shares:.2f} @ {buy_price:.2f}`\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"📍 *Market:* {active['question']}\n"
            f"🛠 *Mode:* {'SIMULATION 🧪' if DRY_RUN else 'LIVE 💸'}\n"
            "━━━━━━━━━━━━━━━━━━"
        )
        await msg_waiting.edit_text(text=msg, parse_mode="Markdown")
    else:
        logging.error(f"Fixed manual trade failed for token {token} and amount {amount}")
        await msg_waiting.edit_text(text=f"❌ Failed to place order (${amount}). Check terminal logs for detailed error.")

async def handle_custom_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    direction = "UP" if "UP" in text else "DOWN"
    context.user_data["custom_direction"] = direction.lower()
    
    await update.message.reply_text(
        text=t("msg_manual_amount"),
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([[t("btn_cancel_trade")]], resize_keyboard=True)
    )
    return WAITING_FOR_AMOUNT

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == "refresh_live":
        tf = 15
        msg = f"📉 *{tf}M LIVE MULTI-ODDS*\n━━━━━━━━━━━━━━━━━━\n"
        
        async def fetch_odds(c):
            active = await async_get_active_market(coin=c, offset_minutes=0, interval=tf)
            if not active: return None
            y = await async_get_last_trade_price(active['yes_token'])
            n = await async_get_last_trade_price(active['no_token'])
            return (c, y, n)
            
        tasks = [fetch_odds(c) for c in COINS]
        results = await asyncio.gather(*tasks)
        
        found = False
        for res in results:
            if res:
                found = True
                c, y, n = res
                msg += f"🌟 *{c}*\n"
                msg += f"  🟢 *YES:* `${y:.2f}`  |  🔴 *NO:* `${n:.2f}`\n"
                msg += "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
                
        if not found:
            await query.answer("❌ Market error", show_alert=True)
            return
            
        msg += "━━━━━━━━━━━━━━━━━━\n"
        msg += f"_Updated: {time.strftime('%H:%M:%S')}_"
        
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔄 Refresh Prices", callback_data="refresh_live")
        ]])
        
        try:
            await query.edit_message_text(msg, reply_markup=keyboard, parse_mode="Markdown")
            await query.answer("✅ Updated!")
        except:
            await query.answer("Prices are already up to date.")
        return
        
    if data.startswith("set_manual_"):
        coin = data.split("_")[2]
        context.user_data["manual_coin"] = coin
        await query.answer(f"✅ Selected Token: {coin}")
        
        # update inline keyboard to show active choice
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"{'✅ ' if coin == c else ''}{c}", callback_data=f"set_manual_{c}") for c in COINS]
        ])
        await query.edit_message_text("🪙 Coin Selection:", reply_markup=keyboard)
        return

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
        
        keyboard = []
        current_row = []
        for coin in [c.upper() for c in COINS]:
            for tf in [5, 15]:
                key = f"{coin.lower()}_{tf}m"
                current_row.append(InlineKeyboardButton(f"{get_toggle(key)} {coin} {tf}m", callback_data=f"toggle_{key}"))
                if len(current_row) == 2:
                    keyboard.append(current_row)
                    current_row = []
        if current_row: keyboard.append(current_row)

        items_str = ""
        for k, v in config.items():
            if v:
                items_str += f"• {k.replace('_', ' ').upper()}: *ENABLED*\n"
        
        msg = (
            "⚙️ *MARKET CONFIGURATION*\n"
            "——————————————————\n\n"
            "Enable or disable specific timeframes. The bot will trade all active ones simultaneously.\n\n"
            f"{items_str if items_str else '⚠️ No active markets!'}"
            "——————————————————"
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
    
    coin = context.user_data.get("manual_coin", "BTC")
    active = await async_get_active_market(coin=coin, offset_minutes=0)
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
    
    success = await async_place_bet(token, amount, coin=coin)
    
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
            "🎯 *MANUAL TRADE*\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"⏰ *Time:* {exec_time}\n"
            f"💰 *Amt:* `${amount}`\n"
            f"↕️ *Side:* {direction}\n"
            f"📊 *Shares:* `{shares:.2f} @ {buy_price:.2f}`\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"📍 *Market:* {active['question']}\n"
            f"🛠 *Mode:* {'SIMULATION 🧪' if DRY_RUN else 'LIVE 💸'}\n"
            "━━━━━━━━━━━━━━━━━━"
        )
        await query.edit_message_text(text=msg, parse_mode="Markdown")
    else:
        logging.error(f"Manual trade failed for token {token} and amount {amount}")
        await query.edit_message_text(text=f"❌ Failed to place order (${amount}). Check terminal logs for detailed error.")

async def handle_custom_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    amount_text = update.message.text
    try:
        amount = float(amount_text)
        if amount <= 0: raise ValueError()
        context.user_data["custom_amount"] = amount
    except ValueError:
        await update.message.reply_text("❌ " + t("msg_invalid_price")) 
        return WAITING_FOR_AMOUNT

    await update.message.reply_text(
        text=t("msg_manual_limit"),
        parse_mode="Markdown"
    )
    return WAITING_FOR_LIMIT

async def handle_custom_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    limit_text = update.message.text
    try:
        limit = float(limit_text)
        if not (0.01 <= limit <= 0.99): raise ValueError()
        context.user_data["custom_limit"] = limit
    except ValueError:
        await update.message.reply_text(t("msg_invalid_price"))
        return WAITING_FOR_LIMIT

    # Show confirmation
    side = context.user_data["custom_direction"].upper()
    amount = context.user_data["custom_amount"]
    
    msg = t("msg_manual_confirm", side=side, amount=amount, price=limit)
    
    # Use Inline Keyboard for self-cleaning UI
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm & Place", callback_data="manual_confirm")],
        [InlineKeyboardButton("❌ Cancel", callback_data="manual_cancel")]
    ])
    
    await update.message.reply_text(msg, reply_markup=keyboard, parse_mode="Markdown")
    return WAITING_FOR_CONFIRM

async def handle_trade_confirm_inline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "manual_cancel":
        await query.edit_message_text("❌ Trade Cancelled.", reply_markup=None)
        return ConversationHandler.END

    # Place trade
    direction_str = context.user_data["custom_direction"]
    amount = context.user_data["custom_amount"]
    limit_price = context.user_data["custom_limit"]
    tf = context.user_data.get("manual_tf", 5)
    
    coin = context.user_data.get("manual_coin", "BTC")
    active = await async_get_active_market(coin=coin, interval=tf)
    if not active:
        await query.edit_message_text("❌ Market Expired.")
        return ConversationHandler.END
        
    token = active['yes_token'] if direction_str == "up" else active['no_token']
    
    await query.edit_message_text(f"⏳ Placing Manual Limit Order: *${amount}* @ *{limit_price}*...", parse_mode="Markdown")
    
    try:
        success = await async_place_bet(token, amount, coin=coin, price=limit_price, order_type="GTC")
        
        if success:
            # Sync to main processing
            try:
                with open("data/manual_bet.json", "w") as f:
                    json.dump({
                        "direction": "YES" if direction_str == "up" else "NO",
                        "timestamp": active['timestamp'],
                        "amount": amount,
                        "buy_price": limit_price,
                        "shares": amount / limit_price,
                        "order_type": "Manual Limit"
                    }, f, indent=4)
                await async_update_virtual_balance(-amount)
            except Exception as fe:
                log_error(f"Manual bet file error: {fe}")

            success_msg = (
                "✅ *ORDER PLACED*\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"💰 *Amt:* `${amount}`\n"
                f"↕️ *Side:* {direction_str.upper()}\n"
                f"🎯 *Limit:* `{limit_price}`\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "Wait for candle boundary to process result or hit level."
            )
            await query.edit_message_text(success_msg, parse_mode="Markdown")
        else:
            await query.edit_message_text("❌ Order Failed. Check keys or balance.")
    except Exception as ee:
        log_error(f"Manual placement error: {ee}")
        await query.edit_message_text(f"❌ Error: {str(ee)[:50]}")
        
    return ConversationHandler.END

async def async_notify_fill(coin, direction, amount, price):
    """Called from main.py when a manual limit order is filled"""
    chat_id = None
    if os.path.exists("data/chat_id.txt"):
        try:
            with open("data/chat_id.txt", "r") as f:
                chat_id = f.read().strip()
        except: pass
    
    if not chat_id: return
    
    from telegram import Bot
    bot = Bot(token=TELEGRAM_TOKEN)
    
    msg = (
        "🔔 *LIMIT FILLED*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"📡 *Asset:* {coin}\n"
        f"💰 *Amt:* `${amount}`\n"
        f"↕️ *Side:* {direction}\n"
        f"🎯 *Price:* `{price}`\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Your manual limit order has been executed on the market."
    )
    try:
        await bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Failed to send fill notification: {e}")

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

    # Dynamic language support helper
    import re
    def r(key):
        pattern = re.escape(STRINGS["en"].get(key, key))
        return f"(?i)({pattern})"
    
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    # Conversation Handler for Manual Trades
    manual_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r"^🎯 Custom (UP|DOWN)$"), handle_custom_start)],
        states={
            WAITING_FOR_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_custom_amount)],
            WAITING_FOR_LIMIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_custom_limit)],
            WAITING_FOR_CONFIRM: [CallbackQueryHandler(handle_trade_confirm_inline)],
        },
        fallbacks=[CommandHandler("cancel", cancel_custom), MessageHandler(filters.Regex(r("btn_cancel_trade")), cancel_custom)],
        per_message=False
    )
    app.add_handler(manual_conv)

    
    # Register other handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset_martingale))
    app.add_handler(CommandHandler("ping", ping))
    
    # Buttons with dynamic language support (Regex matching both EN/HI)

    app.add_handler(MessageHandler(filters.Regex(r("btn_back")), back_to_main))

    app.add_handler(MessageHandler(filters.Regex(r("btn_status")), status))
    app.add_handler(MessageHandler(filters.Regex(r("btn_balance")), balance))
    app.add_handler(MessageHandler(filters.Regex(r("btn_history")), history))
    app.add_handler(MessageHandler(filters.Regex(r("btn_trends")), trends))
    app.add_handler(MessageHandler(filters.Regex(r("btn_manual")), manual_trade))
    app.add_handler(MessageHandler(filters.Regex(r("btn_settings")), settings_command))
    app.add_handler(MessageHandler(filters.Regex(r("btn_back_settings")), settings_command))
    app.add_handler(MessageHandler(filters.Regex(r("btn_reset")), reset_martingale))
    app.add_handler(MessageHandler(filters.Regex(r("btn_report")), daily_report))
    app.add_handler(MessageHandler(filters.Regex(r"📅 7-Day Stats"), weekly_report))
    app.add_handler(MessageHandler(filters.Regex(r("btn_live")), live_price))
    app.add_handler(MessageHandler(filters.Regex(r("btn_claim")), claim_winnings))

    app.add_handler(MessageHandler(filters.Regex(r"^(🟢 UP|🔴 DOWN) \$[0-9]+$"), handle_fixed_manual_trade))
    app.add_handler(MessageHandler(filters.Regex(r("btn_start")), start_stop))
    app.add_handler(MessageHandler(filters.Regex(r("btn_stop")), start_stop))
    
    app.add_handler(MessageHandler(filters.Regex(r("btn_refresh")), toggle_live_price_tf))
    
    # Multi-market and legacy toggles removed
    
    app.add_handler(MessageHandler(filters.Regex(r("btn_help")), help_command))
    app.add_handler(MessageHandler(filters.Regex(r"📅 7-Day Stats"), weekly_report))
    app.add_handler(CallbackQueryHandler(button_callback))
    
    # Schedule notification checker (every 5 seconds)
    app.job_queue.run_repeating(check_notifications, interval=5, first=2)
    
    logging.info(f"Telegram Bot UI Started! (PID: {os.getpid()})")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    run_telegram_bot()
