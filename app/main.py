import time
import sys
import os
import json
import logging
import asyncio
import subprocess
import signal as sys_signal
from datetime import datetime

from app.config import (
    INTERVAL, DRY_RUN, INITIAL_BET_AMOUNT, WALLET_ADDRESS, 
    FUNDER_ADDRESS, COINS, ENABLE_5M, ENABLE_15M
)
from app.logger import ui, log_info, log_success, log_warning, log_error, log_trade, log_countdown, log_telegram, log_status, print_summary, print_result_banner, log_network_error
from app.db import save_candle, get_last_n_candles, save_trade
from app.api.polymarket_api import get_active_market, get_last_trade_price, place_bet, fetch_redeemable_positions
from app.trading.strategy import check_signal
from app.trading.martingale import Martingale
from app.trading.trader import get_balance, get_virtual_balance, update_virtual_balance, redeem_winnings, get_matic_balance, gasless_redeem
from app.bot.telegram_bot import async_notify_fill

# Configure logging to file only (Console is managed by SimpleLogger)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - %(message)s',
    handlers=[
        logging.FileHandler("logs/trading_bot.log")
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
    
    # Define supported markets based on config.py (Kaam ki cheez)
    MARKETS = []
    if ENABLE_15M:
        for coin in COINS:
            MARKETS.append({"id": f"{coin.lower()}_15m", "coin": coin.upper(), "interval": 15, "label": f"{coin.upper()}_15m"})
    if ENABLE_5M:
        for coin in COINS:
            MARKETS.append({"id": f"{coin.lower()}_5m", "coin": coin.upper(), "interval": 5, "label": f"{coin.upper()}_5m"})
    
    # Primary market for UI updates
    PRIMARY_MARKET_ID = MARKETS[0]['id'] if MARKETS else "sol_15m"
    
    # Initialize Market States
    market_states = {}
    for m in MARKETS:
        market_states[m['id']] = {
            "last_ts": 0,
            "processed_ts": 0, # Tracking for Smart Resume (Kaam ki cheez)
            "pending_bet": None,
            "startup_candles": 0,
            "coin": m['coin'],
            "interval": m['interval'],
            "label": m['label']
        }
    
    # Initialize UI state (Default to first active market or SOL if possible)
    ui.status_data["balance"] = str(get_balance())
    first_m = MARKETS[0]['label'] if MARKETS else "SOL_15m"
    ui.status_data["active_market"] = first_m
    ui.status_data["martingale_step"] = mg.get_step(first_m)
    ui.status_data["bet_amount"] = mg.get_bet(first_m)
    
    ui.status_data["pending_trade"] = "None"

    loop_count = 0
    last_redemption_check = 0
    
    matic_bal = get_matic_balance()
    log_info(f"System Initialized. Signer MATIC Balance: {matic_bal} MATIC")

    log_info("Consolidating System - Launching Telegram Bot UI...")
    
    # Send startup notification to Telegram
    send_telegram_notify(
        "� *NODE INITIALIZED*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"📡 *Strat:* SOL Reversal Alpha\n"
        f"🛠 *Mode:* {'LIVE 💸' if not DRY_RUN else 'SIMULATION 🧪'}\n"
        f"⏱ *Window:* SOL 15m (Dedicated)\n"
        f"⛽ *Gas:* `{matic_bal}` MATIC\n"
        f"⏰ *Beat:* {datetime.now().strftime('%H:%M:%S')}\n"
        "━━━━━━━━━━━━━━━━━━"
    )
    
    # Kill any existing Telegram bot processes to prevent duplicates/old versions
    if sys.platform == "win32":
        try:
            subprocess.call(['taskkill', '/F', '/IM', 'python.exe', '/FI', 'MODULES eq app.bot.telegram_bot'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            # Alternatively, simpler approach for common setups:
            os.system('taskkill /F /FI "WINDOWTITLE eq Telegram Bot UI*" /T >nul 2>&1')
        except: pass

    # Start Telegram Bot as a separate process with error capture
    with open("logs/telegram_bot_stderr.log", "a") as err_log:
        tg_process = subprocess.Popen(
            [sys.executable, "-m", "app.bot.telegram_bot"],
            stdout=subprocess.DEVNULL,
            stderr=err_log,
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
    log_status(True, ["SOL"])
    ui.update()

    while True:
        try:
            now_ts = int(time.time())
            
            # Re-calculating MARKETS to respect live config strings (Kaam ki cheez)
            MARKETS = []
            if ENABLE_15M:
                for coin in COINS:
                    MARKETS.append({"id": f"{coin.lower()}_15m", "coin": coin.upper(), "interval": 15, "label": f"{coin.upper()}_15m"})
            if ENABLE_5M:
                for coin in COINS:
                    MARKETS.append({"id": f"{coin.lower()}_5m", "coin": coin.upper(), "interval": 5, "label": f"{coin.upper()}_5m"})
            
            if MARKETS:
                PRIMARY_MARKET_ID = MARKETS[0]['id']
                all_tfs = ", ".join([m['label'] for m in MARKETS])
                ui.status_data["active_market"] = all_tfs
            else:
                PRIMARY_MARKET_ID = "sol_15m"
                ui.status_data["active_market"] = "SOL_15m"

            for m in MARKETS:
                m_id = m['id']
                # Market is already filtered by the rebuild above, but state needs initialization if new
                if m_id not in market_states:
                    market_states[m_id] = {
                        "last_ts": 0,
                        "pending_bet": None,
                        "startup_candles": 0,
                        "coin": m['coin'],
                        "interval": m['interval'],
                        "label": m['label']
                    }
                
                state = market_states[m_id]
                m_coin = m['coin']
                m_interval = m['interval']
                interval_sec = m_interval * 60
                m_floor_ts = (now_ts // interval_sec) * interval_sec
                m_label = m['label']

                # Update countdown and UI if it's the primary UI market
                if m_id == PRIMARY_MARKET_ID:
                    next_boundary = m_floor_ts + interval_sec
                    log_countdown(next_boundary - now_ts)
                    
                    # Update Startup Status display
                    if state['startup_candles'] < 3:
                        ui.status_data["startup_status"] = f"{state['startup_candles']}/3"
                    else:
                        ui.status_data["startup_status"] = "Ready"
                        
                    ui.update()

                # Smart Resume Catch-up Boundary Logic
                # Trigger if:
                # 1. Real boundary crossed (m_floor_ts > last_ts)
                # 2. OR bot was paused and just unpaused within 5 mins of a boundary we haven't processed yet
                is_resume_catchup = not os.path.exists("pause.flag") and m_floor_ts > state.get('processed_ts', 0) and (now_ts - m_floor_ts) < 300
                
                if m_floor_ts > state['last_ts'] or is_resume_catchup:
                    # Update transition trackers
                    if m_floor_ts > state['last_ts']:
                        if state['last_ts'] != 0:
                            state['startup_candles'] += 1
                        state['last_ts'] = m_floor_ts
                    
                    state['processed_ts'] = m_floor_ts
                    log_info(f"[{m_label}] BOUNDARY TRIGGER {'(Catch-up)' if is_resume_catchup else ''} - Processing: {datetime.fromtimestamp(m_floor_ts-interval_sec).strftime('%H:%M')}")
                    
                    try:
                        # Fetch the market that just closed
                        closed_market = get_active_market(coin=m_coin, offset_minutes=-m_interval, interval=m_interval)
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
                                    limit_price = pending.get('buy_price', 0.50)
                                    
                                    # For limit orders: Did price cross the limit?
                                    # (In simulation we use close_price as a proxy for 'ever hit')
                                    is_fill = False
                                    if dir_bet == "YES":
                                        if close_price >= limit_price: is_fill = True
                                    else:
                                        if close_price <= (1.0 - limit_price): is_fill = True
                                    
                                    if is_fill:
                                        log_success(f"[{m_label}] Trade WON! ({dir_bet}, Price: {close_price})")
                                        mg.win(m_label)
                                        
                                        shares = pending.get('shares', bet_amount / limit_price)
                                        payout = shares * 1.0
                                        update_virtual_balance(payout)
                                        
                                        # New: Notify user on Fill
                                        if pending.get('order_type') == "Manual Limit":
                                            try:
                                                asyncio.run(
                                                    async_notify_fill(
                                                        coin=m_label.split('_')[0],
                                                        direction=dir_bet,
                                                        amount=bet_amount,
                                                        price=limit_price
                                                    )
                                                )
                                            except Exception as ne:
                                                log_error(f"Fill notification error: {ne}")
                                        
                                        # Outcome index for bitmask: YES = 1 (bit 0), NO = 2 (bit 1)
                                        outcome_idx = 1 if dir_bet == "YES" else 2

                                        save_trade(
                                            timestamp=int(time.time()),
                                            market_id=closed_market['market_id'],
                                            direction=dir_bet,
                                            amount=bet_amount,
                                            result="WIN",
                                            payout=payout,
                                            order_type=pending.get('order_type', "AUTO"),
                                            interval=m_interval,
                                            outcome_index=outcome_idx
                                        )
                                        
                                        send_telegram_notify(
                                            "🏆  *PROFIT SECURED!*  🏆\n"
                                            "━━━━━━━━━━━━━━━━━━━━\n"
                                            f"💰  *Payout:*  `+${payout:.2f}`\n"
                                            f"📊  *Market:*  `{m_label}`\n"
                                            f"📉  *Close:*   `{close_price}`\n"
                                            "━━━━━━━━━━━━━━━━━━━━\n"
                                            "🔄  *Resetting to Level 1...*"
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
                                            interval=m_interval
                                        )
                                        
                                        send_telegram_notify(
                                            "❌  *TRADE LOSS*  ❌\n"
                                            "━━━━━━━━━━━━━━━━━━━━\n"
                                            f"📉  *Loss:*    `-${bet_amount:.2f}`\n"
                                            f"📊  *Market:*  `{m_label}`\n"
                                            f"📉  *Close:*   `{close_price}`\n"
                                            "━━━━━━━━━━━━━━━━━━━━\n"
                                            f"🪜  *Next:* L{mg.get_step(m_label)+1} » `${mg.get_bet(m_label)}`"
                                        )
                                        trade_res = "LOSS"
                                    state['pending_bet'] = None
                                
                                # Update UI banner for primary market results
                                if m_id == PRIMARY_MARKET_ID:
                                    print_result_banner(trade_res, market_dir)
                                
                                # Record candle in history
                                save_candle(
                                    market_id=closed_market['market_id'], 
                                    token_id=yes_token, 
                                    timestamp=closed_market['timestamp'], 
                                    close_price=close_price,
                                    interval=m_interval
                                )
                                
                                # Signal Check (Standard 3-streak reversal strategy)
                                closes_candles = get_last_n_candles(4, interval=m_interval)
                                closes = [c['close_price'] for c in closes_candles]
                                trade_signal = check_signal(closes)
                                
                                if trade_signal:
                                    display_signal = trade_signal
                                    amount = mg.get_bet(m_label)
                                    if os.path.exists("pause.flag"):
                                        log_warning(f"[{m_label}] Bot is PAUSED. Logic skipped.")
                                        state['processed_ts'] = 0 # Ensure we retry once unpaused
                                    elif state['startup_candles'] < 3:
                                        log_warning(f"[{m_label}] Startup: Waiting for candles ({state['startup_candles']}/3)")
                                    else:
                                        # Set active signal for retry loop
                                        next_market = get_active_market(coin=m_coin, offset_minutes=0, interval=interval)
                                        if next_market:
                                            state['active_signal'] = {
                                                "direction": display_signal,
                                                "retry_until": now_ts + 30,
                                                "amount": amount,
                                                "timestamp": next_market['timestamp'],
                                                "question": next_market.get('question', ''),
                                                "notified_retry": False
                                            }
                                            log_info(f"[{m_label}] {display_signal} Signal! Entry window open for 30s.")
                                        else:
                                            log_error(f"[{m_label}] Failed to fetch market for next candle.")
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
                except Exception as e:
                    logging.error(f"Error handling Telegram activity: {e}")

            # Sync Manual Bets (Adopt to first enabled market)
            if os.path.exists("data/manual_bet.json"):
                try:
                    with open("data/manual_bet.json", "r") as f:
                        manual_bet = json.load(f)
                    os.remove("data/manual_bet.json")
                    
                    # Find first enabled market to adopt the bet
                    m_key = None
                    if MARKETS:
                        m_key = MARKETS[0]['id']
                    
                    if m_key:
                        market_states[m_key]['pending_bet'] = manual_bet
                        ui.status_data["pending_trade"] = f"{manual_bet['direction']} ${manual_bet['amount']} @ {manual_bet['buy_price']}"
                        log_trade(f"Adopted Manual Bet for {m_key}: {manual_bet['direction']} @ {manual_bet['buy_price']}")
                    else:
                        log_error("No active markets to adopt manual bet!")
                except Exception as me:
                    log_error(f"Manual bet adoption error: {me}")

            # Clear pending display if no bets active
            active_pending = any(s['pending_bet'] for s in market_states.values())
            if not active_pending:
                ui.status_data["pending_trade"] = "None"

            # RETRY EXECUTION LOOP (Automated trades)
            for m_id, state in market_states.items():
                if state.get('active_signal') and not state.get('pending_bet'):
                    signal = state['active_signal']
                    m_label = state['label']
                    
                    if now_ts <= signal['retry_until']:
                        # Attempt placement
                        # Re-fetch market to ensure we have the correct tokens
                        m_coin = state['coin']
                        interval = state['interval']
                        
                        m_next = get_active_market(coin=m_coin, offset_minutes=0, interval=interval)
                        if m_next and m_next['timestamp'] == signal['timestamp']:
                            target_token = m_next['yes_token'] if signal['direction'] == "YES" else m_next['no_token']
                            
                            # Determine order type and limit price based on martingale step
                            current_step = mg.get_step(m_label)
                            if current_step == 0:
                                order_type = "FOK"
                                limit_price = 0.99
                            elif current_step == 1:
                                order_type = "GTC"
                                limit_price = 0.49
                            else:
                                order_type = "GTC"
                                limit_price = 0.50

                            log_info(f"[{m_label}] Attempting {signal['direction']} ({order_type})...")
                            success = place_bet(target_token, signal['amount'], coin=m_coin, price=limit_price, order_type=order_type)
                            
                            if success:
                                update_virtual_balance(-signal['amount'])
                                actual_buy_price = get_last_trade_price(target_token) or 0.50
                                if order_type == "GTC": actual_buy_price = limit_price
                                
                                shares = signal['amount'] / actual_buy_price
                                state['pending_bet'] = {
                                    "direction": signal['direction'],
                                    "timestamp": signal['timestamp'],
                                    "amount": signal['amount'],
                                    "shares": shares,
                                    "order_type": order_type
                                }
                                # Clear signal
                                state['active_signal'] = None
                                log_trade(f"[{m_label}] SUCCESS! Placed ${signal['amount']} on {signal['direction']}")
                                
                                # Notify Telegram
                                exec_time = datetime.now().strftime('%H:%M:%S')
                                send_telegram_notify(
                                    "🎯  *TRADE EXECUTED*  🎯\n"
                                    "━━━━━━━━━━━━━━━━━━━━\n"
                                    f"↕️  *Side:*   {signal['direction']} {'▲' if signal['direction'] == 'YES' else '▼'}\n"
                                    f"💰  *Bet:*    `${signal['amount']}`\n"
                                    f"📊  *Market:*  `{m_label}`\n"
                                    f"⏰  *Time:*    `{exec_time}`\n"
                                    "━━━━━━━━━━━━━━━━━━━━"
                                )
                            else:
                                if not signal.get('notified_retry'):
                                    signal['notified_retry'] = True
                                    send_telegram_notify(
                                        f"⚠️ *{m_label} Entry Failed!*\n"
                                        "━━━━━━━━━━━━━━━━━━\n"
                                        "Liquidity issues or rejection.\n"
                                        "🔄 *Retrying for 30s...*"
                                    )
                    else:
                        log_warning(f"[{m_label}] Trade window EXPIRED (30s) for {signal['direction']}. No liquidity found.")
                        send_telegram_notify(
                            f"❌ *{m_label} AUTO MISSED!*\n"
                            "━━━━━━━━━━━━━━━━━━\n"
                            "Window expired after 30s retries.\n"
                            f"No entry found for {signal['direction']}."
                        )
                        state['active_signal'] = None

            # Update Metadata periodically
            if loop_count % 30 == 0:
                try:
                    ui.status_data["balance"] = str(get_balance())
                    ui.status_data["virtual_balance"] = str(get_virtual_balance())
                    ui.status_data["matic_balance"] = str(get_matic_balance())
                    
                    # Live Price Updates
                    if PRIMARY_MARKET_ID:
                        # Find the token for the primary market to get prices
                        m_coin = PRIMARY_MARKET_ID.split('_')[0]
                        m_interval = int(PRIMARY_MARKET_ID.split('_')[1].replace('m', ''))
                        curr_m = get_active_market(coin=m_coin, interval=m_interval)
                        if curr_m:
                            y_price = get_last_trade_price(curr_m['yes_token']) or 0.00
                            ui.status_data["yes_price"] = f"{y_price:.2f}"
                            ui.status_data["no_price"] = f"{(1.0 - y_price):.2f}"

                except Exception as p_err:
                    log_network_error("polling status", p_err)

            # --- 3. AUTO REDEMPTION (~5 Minutes) ---
            if now_ts - last_redemption_check >= 300:
                last_redemption_check = now_ts
                log_info("Running background Auto-Redemption check...")
                try:
                    # Scan both primary and funder wallet
                    wallets = list(set(filter(None, [WALLET_ADDRESS, FUNDER_ADDRESS])))
                    for wallet in wallets:
                        redeemables = fetch_redeemable_positions(wallet)
                        if redeemables:
                            log_success(f"Auto-Redeem: Found {len(redeemables)} winning positions for {wallet[:10]}...")
                            for pos in redeemables:
                                cond_id = pos['condition_id']
                                idx = pos['outcome_index']
                                payout = pos['payout']
                                
                                log_info(f"Initiating claim for {cond_id[:10]}... (${payout:.2f})")
                                
                                # 1. Try Gasless (Paid by Polymarket)
                                success = gasless_redeem(cond_id, idx, wallet)
                                
                                # 2. Fallback to On-Chain (Paid by your MATIC)
                                if not success:
                                    log_warning("Gasless claim failed or unavailable. Falling back to on-chain...")
                                    success = redeem_winnings(cond_id, idx, wallet)
                                
                                if success:
                                    log_success(f"Claim Successful: ${payout:.2f}")
                                    send_telegram_notify(
                                        "🎁  *AUTO-CLAIM COMPLETE*  🎁\n"
                                        "━━━━━━━━━━━━━━━━━━━━\n"
                                        f"💰  *Payout:*  `${payout:.2f}` USDC.e\n"
                                        f"👛  *Wallet:*  `{wallet[:6]}...{wallet[-4:]}`\n"
                                        "━━━━━━━━━━━━━━━━━━━━\n"
                                        "✨ *Funds added to balance.*"
                                    )
                                else:
                                    log_error(f"Auto-Claim failed for {cond_id[:10]}. Will retry in 5m.")
                        else:
                            # log_info(f"No winnings found for {wallet[:10]}...")
                            pass
                except Exception as r_err:
                    log_error(f"Auto-Redemption Task Error: {r_err}")

            loop_count += 1
            time.sleep(1)

        except KeyboardInterrupt:
            cleanup()
        except Exception as e:
            log_error(f"Error in main loop: {e}")
            time.sleep(5)

if __name__ == "__main__":
    bot_loop()
