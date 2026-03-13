import time
import sys
import os
import json
import logging
import subprocess
import signal as sys_signal
from datetime import datetime

from app.config import INTERVAL, DRY_RUN, INITIAL_BET_AMOUNT
from app.logger import ui, log_info, log_success, log_warning, log_error, log_trade, log_countdown, log_telegram, log_status, print_summary, print_result_banner, log_network_error
from app.db import save_candle, get_last_n_candles, save_trade
from app.api.btc_api import get_active_btc_market, get_last_trade_price, place_btc_bet
from app.trading.strategy import check_signal
from app.trading.martingale import Martingale
from app.trading.trader import get_balance, get_virtual_balance, update_virtual_balance

# Configure logging to file only (Console is managed by SimpleLogger)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - %(message)s',
    handlers=[
        logging.FileHandler("logs/btc_bot.log")
    ]
)

# Silence noisy libraries
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("requests").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)

NOTIFY_FILE = "data/telegram_notify.json"

def send_telegram_notify(message):
    """Write a notification to the JSON file for Telegram bot to pick up."""
    try:
        notifications = []
        if os.path.exists(NOTIFY_FILE):
            with open(NOTIFY_FILE, "r") as f:
                notifications = json.load(f)
        notifications.append({"message": message})
        with open(NOTIFY_FILE, "w") as f:
            json.dump(notifications, f)
    except Exception:
        pass

def bot_loop():
    mg = Martingale()
    
    # Define supported markets
    MARKETS = [
        {"id": "btc_5m", "interval": 5, "label": "BTC_5m"},
        {"id": "btc_15m", "interval": 15, "label": "BTC_15m"}
    ]
    
    # Initialize Market States
    market_states = {}
    for m in MARKETS:
        market_states[m['id']] = {
            "last_ts": 0,
            "pending_bet": None,
            "startup_candles": 0
        }
    
    # Initialize UI state (Default to 5m for header)
    ui.status_data["balance"] = str(get_balance())
    ui.status_data["martingale_step"] = mg.get_step("BTC_5m")
    ui.status_data["bet_amount"] = mg.get_bet("BTC_5m")

    loop_count = 0

    log_info("Consolidating System - Launching Telegram Bot UI...")
    
    # Send startup notification to Telegram
    send_telegram_notify(
        "📈 *NODE INITIALIZED*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"⚡️ Strategy: *BTC 3-Streak Reversal*\n"
        f"---------------------------\n"
        f"💵 Base:   *${INITIAL_BET_AMOUNT}*\n"
        f"⏱️ Window:  *Multi-TF Support (5m/15m)*\n"
        f"🧪 Mode:    *{'SIMULATION' if DRY_RUN else 'LIVE'}*\n"
        f"⏰ Heartbeat: *{datetime.now().strftime('%H:%M:%S')}*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    
    # Start Telegram Bot as a separate process
    tg_process = subprocess.Popen(
        [sys.executable, "-m", "app.bot.telegram_bot"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    )
    log_info(f"Master Controller Active (Telegram PID: {tg_process.pid})")

    def cleanup(sig=None, frame=None):
        log_info("Graceful shutdown initiated...")
        if tg_process:
            if sys.platform == "win32":
                subprocess.call(['taskkill', '/F', '/T', '/PID', str(tg_process.pid)])
            else:
                tg_process.terminate()
        log_info("System stopped.")
        sys.exit(0)

    sys_signal.signal(sys_signal.SIGINT, cleanup)
    sys_signal.signal(sys_signal.SIGTERM, cleanup)

    # Main Loop
    log_status(True, ["BTC"])
    ui.update()

    while True:
        try:
            now_ts = int(time.time())
            
            # Load active markets from config
            market_config = {"btc_5m": True, "btc_15m": False}
            MARKET_CONFIG_FILE = "data/market_config.json"
            if os.path.exists(MARKET_CONFIG_FILE):
                try:
                    with open(MARKET_CONFIG_FILE, "r") as f:
                        market_config = json.load(f)
                except:
                    pass

            for m in MARKETS:
                m_id = m['id']
                if not market_config.get(m_id, False):
                    continue
                
                state = market_states[m_id]
                interval = m['interval']
                interval_sec = interval * 60
                m_floor_ts = (now_ts // interval_sec) * interval_sec
                m_label = m['label']

                # Update countdown and UI if it's 5m (primary UI market)
                if m_id == "btc_5m":
                    next_boundary = m_floor_ts + interval_sec
                    log_countdown(next_boundary - now_ts)
                    ui.update()

                if m_floor_ts > state['last_ts']:
                    # Only increment if it's not the very first immediate trigger
                    if state['last_ts'] != 0:
                        state['startup_candles'] += 1
                    state['last_ts'] = m_floor_ts
                    log_info(f"[{m_label}] CANDLE CLOSED - Processing: {datetime.fromtimestamp(m_floor_ts-interval_sec).strftime('%H:%M')}")
                    
                    try:
                        # Fetch the market that just closed
                        closed_market = get_active_btc_market(offset_minutes=-interval, interval=interval)
                        if closed_market:
                            yes_token = closed_market['yes_token']
                            close_price = get_last_trade_price(yes_token)
                            
                            if close_price is not None:
                                market_dir = "UP" if close_price > 0.5 else "DOWN"
                                trade_res = None
                                
                                # Process Pending Bet for this market
                                pending = state['pending_bet']
                                if pending and pending['timestamp'] == closed_market['timestamp']:
                                    dir_bet = pending['direction']
                                    bet_amount = pending.get('amount', mg.get_bet(m_label))
                                    if (dir_bet == "YES" and close_price > 0.5) or (dir_bet == "NO" and close_price < 0.5):
                                        log_success(f"[{m_label}] Trade WON! ({dir_bet}, Price: {close_price})")
                                        mg.win(m_label)
                                        
                                        shares = pending.get('shares', bet_amount / 0.50)
                                        payout = shares * 1.0
                                        update_virtual_balance(payout)
                                        
                                        save_trade(
                                            timestamp=int(time.time()),
                                            market_id=closed_market['market_id'],
                                            direction=dir_bet,
                                            amount=bet_amount,
                                            result="WIN",
                                            payout=payout,
                                            order_type=pending.get('order_type', "AUTO"),
                                            interval=interval
                                        )
                                        
                                        send_telegram_notify(
                                            f"🏆 *WIN: {m_label}*\n"
                                            f"━━━━━━━━━━━━━━━━━━\n"
                                            f"💰 Payout: *+${payout:.2f}*\n"
                                            f"📈 Close:  *{close_price}*\n"
                                            f"🔄 Martingale Reset\n"
                                            f"━━━━━━━━━━━━━━━━━━"
                                        )
                                        trade_res = "WIN"
                                    else:
                                        log_error(f"[{m_label}] Trade LOST! ({dir_bet}, Price: {close_price})")
                                        mg.lose(m_label)
                                        
                                        save_trade(
                                            timestamp=int(time.time()),
                                            market_id=closed_market['market_id'],
                                            direction=dir_bet,
                                            amount=bet_amount,
                                            result="LOSS",
                                            payout=0,
                                            order_type=pending.get('order_type', "AUTO"),
                                            interval=interval
                                        )
                                        
                                        send_telegram_notify(
                                            f"❌ *LOSS: {m_label}*\n"
                                            f"━━━━━━━━━━━━━━━━━━\n"
                                            f"📉 Loss:  *- ${bet_amount:.2f}*\n"
                                            f"📈 Close: *{close_price}*\n"
                                            f"⬆️ Next:  *L{mg.get_step(m_label)+1} (${mg.get_bet(m_label)})*\n"
                                            f"━━━━━━━━━━━━━━━━━━"
                                        )
                                        trade_res = "LOSS"
                                    state['pending_bet'] = None
                                
                                # Update UI banner for 5m results
                                if m_id == "btc_5m":
                                    print_result_banner(trade_res, market_dir)
                                
                                # Record candle in history
                                save_candle(
                                    market_id=closed_market['market_id'], 
                                    token_id=yes_token, 
                                    timestamp=closed_market['timestamp'], 
                                    close_price=close_price,
                                    interval=interval
                                )
                                
                                # Signal Check (3-streak reversal strategy)
                                closes_candles = get_last_n_candles(3, interval=interval)
                                closes = [c['close_price'] for c in closes_candles]
                                trade_signal = check_signal(closes)
                                
                                if trade_signal:
                                    amount = mg.get_bet(m_label)
                                    if os.path.exists("pause.flag"):
                                        log_warning(f"[{m_label}] Bot is PAUSED. Skipping trade.")
                                    elif state['startup_candles'] < 3:
                                        log_warning(f"[{m_label}] Startup: Waiting for candles ({state['startup_candles']}/3)")
                                    else:
                                        # Get market for the NEXT candle
                                        next_market = get_active_btc_market(offset_minutes=0, interval=interval)
                                        if next_market:
                                            target_token = next_market['yes_token'] if trade_signal == "YES" else next_market['no_token']
                                            current_step = mg.get_step(m_label)
                                            # L1 = Market Order (FOK), L2+ = Limit Order (GTC)
                                            order_type = "FOK" if current_step == 0 else "GTC"
                                            limit_price = 0.99 if order_type == "FOK" else 0.50
                                            
                                            if place_btc_bet(target_token, amount, price=limit_price, order_type=order_type):
                                                update_virtual_balance(-amount)
                                                actual_buy_price = get_last_trade_price(target_token) or 0.50
                                                if order_type == "GTC":
                                                    actual_buy_price = limit_price
                                                
                                                shares = amount / actual_buy_price
                                                state['pending_bet'] = {
                                                    "direction": trade_signal, 
                                                    "timestamp": next_market['timestamp'], 
                                                    "amount": amount,
                                                    "shares": shares,
                                                    "order_type": order_type
                                                }
                                                log_trade(f"[{m_label}] Placed ${amount} on {trade_signal}")
                                                
                                                exec_time = datetime.now().strftime('%H:%M:%S')
                                                send_telegram_notify(
                                                    f"🎯 *Auto Trade: {m_label}*\n"
                                                    f"━━━━━━━━━━━━━━━━━━\n"
                                                    f"⏰ Time: *{exec_time}*\n"
                                                    f"💰 Amt:  *${amount}*\n"
                                                    f"📊 Side: *{trade_signal}*\n"
                                                    f"📌 {next_market['question']}\n"
                                                    f"━━━━━━━━━━━━━━━━━━"
                                                )
                        else:
                            log_error(f"[{m_label}] Failed to fetch market at boundary.")
                    except Exception as b_err:
                        log_network_error(f"processing {m_label} boundary", b_err)

            # --- 2. FAST/POLLING LOGIC (Every Loop) ---
            
            # Sync Telegram Logs
            if os.path.exists("logs/telegram_activity.log"):
                try:
                    with open("logs/telegram_activity.log", "r") as f:
                        lines = f.readlines()
                    if lines:
                        for line in lines:
                            if line.strip(): log_telegram(line.strip())
                        open("logs/telegram_activity.log", "w").close()
                except:
                    pass

            # Sync Manual Bets (Adopt to 5m by default)
            if os.path.exists("data/manual_bet.json"):
                try:
                    with open("data/manual_bet.json", "r") as f:
                        manual_bet = json.load(f)
                    os.remove("data/manual_bet.json")
                    market_states['btc_5m']['pending_bet'] = manual_bet
                    log_trade(f"Adopted Manual Bet for 5m: {manual_bet['direction']}")
                except:
                    pass

            # Throttled Metadata (~30s)
            if loop_count % 30 == 0:
                try:
                    # Update Balance & Market Info
                    ui.status_data["balance"] = str(get_balance())
                    ui.status_data["virtual_balance"] = str(get_virtual_balance())
                    
                    # Show 5m market in header by default
                    active_market = get_active_btc_market(offset_minutes=0, interval=5)
                    if active_market:
                        ui.status_data["active_market"] = active_market['question'].replace("Bitcoin 5-minute Up/Down for ", "")
                        y_p = get_last_trade_price(active_market['yes_token'])
                        n_p = get_last_trade_price(active_market['no_token'])
                        ui.status_data["yes_price"] = f"{y_p:.4f}" if y_p is not None else "0.00"
                        ui.status_data["no_price"] = f"{n_p:.4f}" if n_p is not None else "0.00"
                    
                    ui.status_data["martingale_step"] = mg.get_step("BTC_5m")
                    ui.status_data["bet_amount"] = mg.get_bet("BTC_5m")
                except Exception as p_err:
                    log_network_error("polling status", p_err)

            loop_count += 1
            time.sleep(1)

        except KeyboardInterrupt:
            cleanup()
        except Exception as e:
            log_error(f"Error in main loop: {e}")
            time.sleep(5)

if __name__ == "__main__":
    bot_loop()
