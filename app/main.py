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
    
    # Initialize UI state
    ui.status_data["balance"] = str(get_balance())
    ui.status_data["martingale_step"] = mg.get_step("BTC")
    ui.status_data["bet_amount"] = mg.get_bet("BTC")

    last_processed_ts = 0
    pending_bet = None
    loop_count = 0
    startup_candles_processed = 0

    log_info("Consolidating System - Launching Telegram Bot UI...")
    
    # Send startup notification to Telegram
    send_telegram_notify(
        "📈 *NODE INITIALIZED*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"⚡️ Strategy: *BTC 5m Momentum*\n"
        f"---------------------------\n"
        f"💵 Base:   *${INITIAL_BET_AMOUNT}*\n"
        f"⏱️ Window:  *{INTERVAL}m Candles*\n"
        f"🧪 Mode:    *{'SIMULATION' if DRY_RUN else 'LIVE'}*\n"
        f"⏰ Heartbeat: *{datetime.now().strftime('%H:%M:%S')}*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    
    # Start Telegram Bot as a separate process (Let it manage its own Rotating logger)
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

    # Main Loop (Sequential Scrolling Logs)
    log_status(True, ["BTC"])
    ui.update()

    while True:
        try:
            now_ts = int(time.time())
            interval_sec = INTERVAL * 60
            floor_ts = (now_ts // interval_sec) * interval_sec
            next_boundary = floor_ts + interval_sec
            seconds_until_next = next_boundary - now_ts

            # Update countdown state
            log_countdown(seconds_until_next)

            # Refresh UI Header
            ui.update()

            # --- 1. SLOW/TRADING LOGIC (Every Candle Boundary) ---
            if floor_ts > last_processed_ts:
                # Only increment if it's not the very first immediate trigger
                if last_processed_ts != 0:
                    startup_candles_processed += 1
                last_processed_ts = floor_ts
                log_info(f"CANDLE CLOSED - Processing: {datetime.fromtimestamp(floor_ts-interval_sec).strftime('%H:%M')}")
                
                try:
                    closed_market = get_active_btc_market(offset_minutes=-INTERVAL)
                    if closed_market:
                        yes_token = closed_market['yes_token']
                        close_price = get_last_trade_price(yes_token)
                        
                        if close_price is not None:
                            market_dir = "UP" if close_price > 0.5 else "DOWN"
                            trade_res = None
                            
                            # Process Pending Bet
                            if pending_bet and pending_bet['timestamp'] == closed_market['timestamp']:
                                dir_bet = pending_bet['direction']
                                bet_amount = pending_bet.get('amount', mg.get_bet("BTC")) # Fallback
                                if (dir_bet == "YES" and close_price > 0.5) or (dir_bet == "NO" and close_price < 0.5):
                                    log_success(f"Trade WON! ({dir_bet}, Price: {close_price})")
                                    mg.win("BTC")
                                    
                                    shares = pending_bet.get('shares', bet_amount / 0.50)
                                    payout = shares * 1.0
                                    profit = payout - bet_amount
                                    update_virtual_balance(payout)
                                    
                                    # Record in DB
                                    save_trade(
                                        timestamp=int(time.time()),
                                        market_id=closed_market['market_id'],
                                        direction=dir_bet,
                                        amount=bet_amount,
                                        result="WIN",
                                        payout=payout,
                                        order_type=pending_bet.get('order_type', "AUTO")
                                    )
                                    
                                    send_telegram_notify(
                                        f"🏆 *SETTLEMENT: WIN*\n"
                                        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                                        f"💰 Payout:   *+${payout:.2f}*\n"
                                        f"💵 Profit:   *+${profit:.2f}*\n"
                                        f"---------------------------\n"
                                        f"📊 Position:  *{dir_bet}*\n"
                                        f"📉 Close:     *{close_price}* (WIN)\n"
                                        f"---------------------------\n"
                                        f"🔄 System: Martingale Reset (L1)\n"
                                        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                                    )
                                    trade_res = "WIN"
                                else:
                                    log_error(f"Trade LOST! ({dir_bet}, Price: {close_price})")
                                    mg.lose("BTC")
                                    new_step = mg.get_step("BTC")
                                    
                                    # Record in DB
                                    save_trade(
                                        timestamp=int(time.time()),
                                        market_id=closed_market['market_id'],
                                        direction=dir_bet,
                                        amount=bet_amount,
                                        result="LOSS",
                                        payout=0,
                                        order_type=pending_bet.get('order_type', "AUTO")
                                    )
                                    
                                    send_telegram_notify(
                                        f"❌ *SETTLEMENT: LOSS*\n"
                                        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                                        f"📉 Loss:     *- ${bet_amount:.2f}*\n"
                                        f"---------------------------\n"
                                        f"📊 Position:  *{dir_bet}*\n"
                                        f"📈 Close:     *{close_price}* (LOSS)\n"
                                        f"---------------------------\n"
                                        f"⬆️ System: Martingale L{new_step} -> L{new_step+1}\n"
                                        f"Risk: *${mg.get_bet('BTC')}*\n"
                                        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                                    )
                                    trade_res = "LOSS"
                                pending_bet = None
                            
                            # This now updates the UI header state
                            print_result_banner(trade_res, market_dir)
                            
                            save_candle(
                                market_id=closed_market['market_id'], 
                                token_id=yes_token, 
                                timestamp=closed_market['timestamp'], 
                                close_price=close_price
                            )
                            
                            # Signal Check
                            closes_candles = get_last_n_candles(3)
                            closes = [c['close_price'] for c in closes_candles]
                            trade_signal = check_signal(closes)
                            
                            if trade_signal:
                                amount = mg.get_bet("BTC")
                                if os.path.exists("pause.flag"):
                                    log_warning("Bot is PAUSED. Skipping trade.")
                                elif startup_candles_processed < 3:
                                    log_warning(f"Startup Phase: Waiting for new candles ({startup_candles_processed}/3)")
                                else:
                                    next_market = get_active_btc_market(offset_minutes=0)
                                    if next_market:
                                        target_token = next_market['yes_token'] if trade_signal == "YES" else next_market['no_token']
                                        # L1 = Market Order, L2-L7 = Limit Order
                                        current_step = mg.get_step("BTC")
                                        if current_step == 1:
                                            order_type = "FOK"
                                            limit_price = 0.99
                                            order_name = "Market Order"
                                        else:
                                            order_type = "GTC"
                                            limit_price = 0.50
                                            order_name = "Limit Order"

                                        if place_btc_bet(target_token, amount, price=limit_price, order_type=order_type):
                                            update_virtual_balance(-amount)
                                            
                                            actual_buy_price = get_last_trade_price(target_token)
                                            if not actual_buy_price or actual_buy_price <= 0:
                                                actual_buy_price = 0.50
                                            if order_type == "GTC":
                                                actual_buy_price = limit_price
                                                
                                            shares = amount / actual_buy_price
                                            
                                            pending_bet = {
                                                "direction": trade_signal, 
                                                "timestamp": next_market['timestamp'], 
                                                "amount": amount,
                                                "buy_price": actual_buy_price,
                                                "shares": shares,
                                                "order_type": order_type
                                            }
                                            log_trade(f"Placed ${amount} on {trade_signal} ({order_name} @ {actual_buy_price:.2f})")
                                            
                                            exec_time = datetime.now().strftime('%H:%M:%S')
                                            send_telegram_notify(
                                                f"🎯 *Auto Trade Executed*\n"
                                                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                                                f"⏰ Time: *{exec_time}*\n"
                                                f"---------------------------\n"
                                                f"💰 Amount: *${amount}*\n"
                                                f"📊 Side:   *{trade_signal}*\n"
                                                f"---------------------------\n"
                                                f"🪙 Shares: *{shares:.2f}* (@ {actual_buy_price:.2f})\n"
                                                f"⚙️ Type:   *{order_name}*\n"
                                                f"---------------------------\n"
                                                f"📌 Market: *{next_market['question']}*\n"
                                                f"---------------------------\n"
                                                f"{'🧪 SIMULATION ACTIVE' if DRY_RUN else '💸 LIVE EXECUTION'}\n"
                                            )

                                    else:
                                        log_error("Could not find next market for signal.")
                    else:
                        log_error("Failed to fetch closed market data at boundary.")
                except Exception as b_err:
                    log_network_error("processing boundary", b_err)

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
                except: pass

            # Sync Manual Bets
            if os.path.exists("data/manual_bet.json"):
                try:
                    with open("data/manual_bet.json", "r") as f:
                        manual_bet = json.load(f)
                    os.remove("data/manual_bet.json")
                    pending_bet = manual_bet
                    log_trade(f"Adopted Manual Bet for tracking: {pending_bet['direction']}")
                except: pass


            # Throttled Metadata (~30s)
            if loop_count % 30 == 0:
                try:
                    # Update Balance & Market Info
                    ui.status_data["balance"] = str(get_balance())
                    ui.status_data["virtual_balance"] = str(get_virtual_balance())
                    active_market = get_active_btc_market(offset_minutes=0)
                    if active_market:
                        ui.status_data["active_market"] = active_market['question'].replace("Bitcoin 5-minute Up/Down for ", "")
                        y_p = get_last_trade_price(active_market['yes_token'])
                        n_p = get_last_trade_price(active_market['no_token'])
                        ui.status_data["yes_price"] = f"{y_p:.4f}" if y_p is not None else "0.00"
                        ui.status_data["no_price"] = f"{n_p:.4f}" if n_p is not None else "0.00"
                    
                    ui.status_data["martingale_step"] = mg.get_step("BTC")
                    ui.status_data["bet_amount"] = mg.get_bet("BTC")
                    # No manual print_summary() here anymore, it's done at top of loop
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
