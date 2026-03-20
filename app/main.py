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
from app.api.polymarket_api import get_active_market, get_last_trade_price, place_bet, fetch_redeemable_positions, async_send_heartbeat
from app.trading.strategy import check_signal
from app.trading.martingale import Martingale
from app.trading.trader import get_balance, get_virtual_balance, update_virtual_balance, redeem_winnings, get_matic_balance, gasless_redeem
from app.bot.telegram_bot import async_notify_fill

# Ensure necessary directories exist
os.makedirs("logs", exist_ok=True)
os.makedirs("data", exist_ok=True)

# Track session start (Aligned to 15m block start, strictly session-only)
BOT_START_TIME = (int(time.time()) // 900) * 900

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

async def heartbeat_worker():
    """Background task to send heartbeats every 7 seconds."""
    while True:
        try:
            await async_send_heartbeat()
        except Exception as e:
            logging.error(f"[HEARTBEAT] Worker error: {e}")
        await asyncio.sleep(7)

async def redemption_worker():
    """Background task to check for winners every 5 minutes."""
    while True:
        try:
            # Wait 5 mins between checks
            await asyncio.sleep(300)
            log_info("Running background Auto-Redemption check...")
            wallets = list(set(filter(None, [WALLET_ADDRESS, FUNDER_ADDRESS])))
            for wallet in wallets:
                # fetch_redeemable_positions is currently sync, we offload to thread
                redeemables = await asyncio.to_thread(fetch_redeemable_positions, wallet)
                if redeemables:
                    log_success(f"Auto-Redeem: Found {len(redeemables)} winning positions for {wallet[:10]}...")
                    for pos in redeemables:
                        cond_id = pos['condition_id']
                        idx = pos['outcome_index']
                        payout = pos['payout']
                        log_info(f"Initiating claim for {cond_id[:10]}... (${payout:.2f})")
                        
                        # gasless_redeem and redeem_winnings are sync, offload to thread
                        success = await asyncio.to_thread(gasless_redeem, cond_id, idx, wallet)
                        if not success:
                            log_warning("Gasless claim failed. Falling back to on-chain...")
                            success = await asyncio.to_thread(redeem_winnings, cond_id, idx, wallet)
                        
                        if success:
                            log_success(f"Claim Successful: ${payout:.2f}")
                            send_telegram_notify(f"🎁 *AUTO-CLAIM COMPLETE*\n${payout:.2f} USDC.e claimed for {wallet[:6]}...")
        except Exception as e:
            log_error(f"Redemption Worker error: {e}")

async def bot_loop():
    mg = Martingale()
    mg.reset_all() # Reset all steps on startup as requested by user
    
    # Define supported markets based on config.py (Normalized to POLL_MARKETS)
    POLL_MARKETS = []
    if ENABLE_15M:
        for coin in COINS: POLL_MARKETS.append({"id": f"{coin.lower()}_15m", "coin": coin.upper(), "interval": 15, "label": f"{coin.upper()}_15m"})
    if ENABLE_5M:
        for coin in COINS: POLL_MARKETS.append({"id": f"{coin.lower()}_5m", "coin": coin.upper(), "interval": 5, "label": f"{coin.upper()}_5m"})
    
    # Initialize Market States efficiently
    market_states = {m['id']: {
        "last_ts": 0, "processed_ts": 0, "pending_bet": None, "startup_candles": 0,
        "coin": m['coin'], "interval": m['interval'], "label": m['label']
    } for m in POLL_MARKETS}
    
    # Initialize UI state
    loop_count = 0
    matic_bal = get_matic_balance()
    ui.status_data["balance"] = str(get_balance())
    ui.status_data["virtual_balance"] = str(get_virtual_balance())
    ui.status_data["matic_balance"] = str(matic_bal)
    
    # Initialize market table in UI
    for m in POLL_MARKETS:
        coin = m['coin']
        if coin not in ui.status_data["markets"]:
            ui.status_data["markets"][coin] = {"yes": "0.00", "no": "0.00", "status": "Ready"}

    async def dashboard_price_poller():
        """Background task to fetch prices for all coins periodically."""
        from app.api.polymarket_api import async_get_active_market, async_get_last_trade_price
        while True:
            try:
                for coin in COINS:
                    m_info = await async_get_active_market(coin=coin.upper(), interval=15)
                    if m_info:
                        y_p = await async_get_last_trade_price(m_info['yes_token'])
                        if y_p is not None:
                            ui.status_data["markets"][coin.upper()]["yes"] = f"{y_p:.2f}"
                            ui.status_data["markets"][coin.upper()]["no"] = f"{(1-y_p):.2f}"
                ui.update()
            except Exception: pass
            await asyncio.sleep(15) # Pulse every 15s to avoid rate limits

    asyncio.create_task(dashboard_price_poller())

    # Start Telegram Bot
    if sys.platform == "win32":
        try:
            os.system('taskkill /F /FI "WINDOWTITLE eq Telegram Bot UI*" /T >nul 2>&1')
        except: pass

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

    # Launch Background Workers
    asyncio.create_task(heartbeat_worker())
    asyncio.create_task(redemption_worker())

    # Helper coroutine for per-market logic
    async def process_market_step(m, now_ts, primary_id):
        m_id = m['id']
        state = market_states[m_id]
        m_coin = m['coin']
        m_interval = m['interval']
        interval_sec = m_interval * 60
        m_floor_ts = (now_ts // interval_sec) * interval_sec
        m_label = m['label']

        if m_id == primary_id:
            next_boundary = m_floor_ts + interval_sec
            log_countdown(next_boundary - now_ts)
            ui.status_data["startup_status"] = f"{state['startup_candles']}/3 h" if state['startup_candles'] < 3 else f"{int((time.time()-BOT_START_TIME)/3600)}h"
            ui.update()

        is_resume_catchup = not os.path.exists("pause.flag") and m_floor_ts > state.get('processed_ts', 0) and (now_ts - m_floor_ts) < 300
        
        if m_floor_ts > state['last_ts']:
            if state['last_ts'] != 0: state['startup_candles'] += 1
            state['last_ts'] = m_floor_ts
        state['processed_ts'] = m_floor_ts
        
        ui.status_data["markets"][m_coin]["status"] = "Scanning..."
        log_info(f"[{m_label}] BOUNDARY TRIGGER - Processing...")
            
        try:
            from app.api.polymarket_api import async_get_active_market, async_get_last_trade_price
            closed_market = await async_get_active_market(coin=m_coin, offset_minutes=-m_interval, interval=m_interval)
            if closed_market:
                yes_token = closed_market['yes_token']
                close_price = await async_get_last_trade_price(yes_token)
                
                if close_price is not None:
                    market_dir = "UP" if close_price > 0.5 else "DOWN"
                    trade_res = None
                    
                    pending = state['pending_bet']
                    if pending and pending['timestamp'] == closed_market['timestamp']:
                        dir_bet = pending['direction']
                        bet_amount = pending.get('amount', mg.get_bet(m_label))
                        entry_price = pending.get('buy_price', 0.50)
                        
                        # resolution_price is 1.0 if YES win, 0.0 if YES loss (NO win)
                        # Actual win condition for UpDown markets is simply resolving > 0.5 or < 0.5
                        market_won = (close_price > 0.5) if dir_bet == "YES" else (close_price < 0.5)
                        
                        # For Level 1 (FOK/Market), we assume success means it filled.
                        # For Level 2+ (Limit), we check if the market touched our price (using close as proxy)
                        order_filled = True if pending.get('order_type') == "FOK" else (
                            (close_price >= entry_price) if dir_bet == "YES" else (close_price <= (1.0 - entry_price))
                        )
                        
                        if market_won and order_filled:
                            log_success(f"[{m_label}] Trade WON! ({dir_bet}, Close: {close_price})")
                            mg.win(m_label)
                            # shares were calculated at entry time based on actual price
                            shares = pending.get('shares', bet_amount / entry_price)
                            payout = shares * 1.0 # Resolved value
                            profit = payout - bet_amount
                            update_virtual_balance(payout)
                            ui.status_data["markets"][m_coin]["status"] = "✅ WON"
                            trade_res = "WIN"
                            send_telegram_notify(f"✅ *TRADE WON*\n\n• Asset: `{m_label}`\n• PnL:  `+{profit:.2f} USDC` \n• Next: Back to Level 1")
                        elif not market_won and order_filled:
                            log_error(f"[{m_label}] Trade LOST! ({dir_bet}, Close: {close_price})")
                            mg.lose(m_label)
                            ui.status_data["markets"][m_coin]["status"] = "❌ LOST"
                            trade_res = "LOSS"
                            next_step = mg.get_step(m_label)
                            send_telegram_notify(f"❌ *TRADE LOST*\n\n• Asset: `{m_label}`\n• Step:  Martingale Level {next_step+1}\n• Info:  Locking Asset for Recovery")
                        else:
                            # Order never filled (Wait for next signal or keep pending?)
                            log_warning(f"[{m_label}] Order did not fill. Skipping resolution.")
                            ui.status_data["markets"][m_coin]["status"] = "Ready"
                        
                        if trade_res:
                            outcome_idx = 1 if dir_bet == "YES" else 2
                            await asyncio.to_thread(save_trade, timestamp=int(time.time()), market_id=closed_market['market_id'], direction=dir_bet, amount=bet_amount, result=trade_res, payout=payout if trade_res == "WIN" else 0, order_type=pending.get('order_type', "AUTO"), interval=m_interval, outcome_index=outcome_idx if trade_res == "WIN" else None)
                        state['pending_bet'] = None
                    
                    if m_id == primary_id: print_result_banner(trade_res, market_dir)
                    await asyncio.to_thread(save_candle, market_id=closed_market['market_id'], token_id=yes_token, timestamp=closed_market['timestamp'], close_price=close_price, interval=m_interval, coin=m_coin)
                    
                    closes_candles = await asyncio.to_thread(get_last_n_candles, 4, interval=m_interval, coin=m_coin, min_ts=BOT_START_TIME)
                    closes = [c['close_price'] for c in closes_candles]
                    trade_signal = check_signal(closes)
                    
                    if trade_signal:
                        if os.path.exists("pause.flag"): 
                            log_warning(f"[{m_label}] Bot is PAUSED. {trade_signal} Signal ignored.")
                        elif state['startup_candles'] < 2:
                            log_warning(f"[{m_label}] Startup: Waiting for session candles ({state['startup_candles']+1}/3)")
                        else:
                            next_market = await async_get_active_market(coin=m_coin, offset_minutes=0, interval=m_interval)
                            if next_market:
                                state['active_signal'] = {"direction": trade_signal, "retry_until": now_ts + 30, "amount": mg.get_bet(m_label), "timestamp": next_market['timestamp'], "notified_retry": False}
                                ui.status_data["markets"][m_coin]["status"] = f"🎯 {trade_signal} Signal"
                                log_info(f"[{m_label}] {trade_signal} Signal! Entry window open for 30s. Streak: {closes}")
                    else:
                        if ui.status_data["markets"][m_coin]["status"] not in ["✅ WON", "❌ LOST"]:
                            ui.status_data["markets"][m_coin]["status"] = "Scanning"
        except Exception as b_err:
            log_network_error(f"processing {m_label} boundary", b_err)

    log_status(True, ["SOL"])
    ui.update()

    # Static Configuration
    POLL_MARKETS = []
    if ENABLE_15M:
        for coin in COINS: POLL_MARKETS.append({"id": f"{coin.lower()}_15m", "coin": coin.upper(), "interval": 15, "label": f"{coin.upper()}_15m"})
    if ENABLE_5M:
        for coin in COINS: POLL_MARKETS.append({"id": f"{coin.lower()}_5m", "coin": coin.upper(), "interval": 5, "label": f"{coin.upper()}_5m"})
    
    PRIMARY_MARKET_ID = POLL_MARKETS[0]['id'] if POLL_MARKETS else "sol_15m"
    ui.status_data["active_market"] = ", ".join([m['label'] for m in POLL_MARKETS])

    while True:
        try:
            now_ts = int(time.time())
            await asyncio.gather(*[process_market_step(m, now_ts, PRIMARY_MARKET_ID) for m in POLL_MARKETS])

            if os.path.exists("logs/telegram_activity.log"):
                try:
                    with open("logs/telegram_activity.log", "r") as f:
                        lines = f.readlines()
                    if lines:
                        for line in lines:
                            if line.strip(): log_telegram(line.strip())
                        open("logs/telegram_activity.log", "w").close()
                except: pass

            if os.path.exists("data/manual_bet.json"):
                try:
                    with open("data/manual_bet.json", "r") as f: manual_bet = json.load(f)
                    os.remove("data/manual_bet.json")
                    m_coin = manual_bet.get('coin', 'SOL').upper()
                    m_key = f"{m_coin.lower()}_15m"
                    if m_key in market_states:
                        market_states[m_key]['pending_bet'] = manual_bet
                        log_info(f"[{m_key}] Injected manual bet from UI.")
                        ui.status_data["pending_trade"] = f"{manual_bet['direction']} ${manual_bet['amount']}"
                except: pass

            if not any(s['pending_bet'] for s in market_states.values()):
                ui.status_data["pending_trade"] = "None"

            # 3. EXECUTION LOGIC: Mutual Exclusion (One Trade at a Time)
            any_pending = any(s['pending_bet'] for s in market_states.values())
            
            if not any_pending:
                candidates = [m_id for m_id, s in market_states.items() if s.get('active_signal')]
                
                # RECOVERY LOCK: If ANY coin is in Martingale recovery (step > 0), lock the system to that coin!
                # This ensures we don't start new trades on ETH if BTC is currently trying to recover a loss.
                recovery_label = next((m['label'] for m in POLL_MARKETS if mg.get_step(m['label']) > 0), None)
                ui.status_data["recovery_lock"] = recovery_label if recovery_label else "NONE"
                
                if recovery_label:
                    # Filter candidates to ONLY show the recovery coin
                    candidates = [m for m in candidates if market_states[m]['label'] == recovery_label]
                    if not candidates:
                        # System is locked waiting for the recovery coin's signal
                        if loop_count % 60 == 0:
                            log_info(f"Recovery Lock: System is WAITING for {recovery_label} signal.")
                
                if candidates:
                    # Selection from filtered candidates
                    sol_candidates = [m for m in candidates if "sol_" in m]
                    if sol_candidates:
                        chosen_m_id = sol_candidates[0]
                    else:
                        import random
                        chosen_m_id = random.choice(candidates)
                        
                    state = market_states[chosen_m_id]
                    signal = state['active_signal']
                    
                    if now_ts <= signal['retry_until']:
                        from app.api.polymarket_api import async_get_active_market, async_place_bet, async_get_last_trade_price
                        m_next = await async_get_active_market(coin=state['coin'], interval=state['interval'])
                        if m_next and m_next['timestamp'] == signal['timestamp']:
                            target_token = m_next['yes_token'] if signal['direction'] == "YES" else m_next['no_token']
                            current_step = mg.get_step(state['label'])
                            
                            # For Level 1 (step 0), use Market-Fill (0.99 price) but calculate shares based on actual current price
                            if current_step == 0:
                                order_type = "FOK"
                                limit_price = 0.99
                                current_price = await async_get_last_trade_price(target_token)
                                # Default to 0.50 if price fetch fails for estimation
                                est_price = current_price if (current_price and current_price > 0) else 0.50
                            else:
                                order_type = "GTC"
                                limit_price = 0.49 if current_step == 1 else 0.50
                                est_price = limit_price
                            
                            success = await async_place_bet(target_token, signal['amount'], coin=state['coin'], price=limit_price, order_type=order_type)
                            if success:
                                update_virtual_balance(-signal['amount'])
                                # Use est_price for reporting, but limit_price is what goes to the exchange
                                state['pending_bet'] = {"direction": signal['direction'], "timestamp": signal['timestamp'], "amount": signal['amount'], "shares": signal['amount']/est_price, "order_type": order_type, "buy_price": est_price}
                                state['active_signal'] = None
                                log_trade(f"[{state['label']}] SUCCESS! Placed ${signal['amount']} on {signal['direction']} (Est. Price: {est_price})")
                                
                                # Enhanced execution notification
                                step = mg.get_step(state['label'])
                                msg = f"🎯 *TRADE EXECUTED*\n"
                                msg += f"• Asset: `{state['label']}`\n"
                                msg += f"• Side:  `{signal['direction']}`\n"
                                msg += f"• Bet:   `${signal['amount']}`\n"
                                msg += f"• Mode:  `{'Recovery' if step > 0 else 'Initial'}` (Lvl {step+1})"
                                send_telegram_notify(msg)
                    
                    # Expire all signals after selection
                    for mid in candidates:
                        market_states[mid]['active_signal'] = None
            else:
                # Expire any signals that appeared while a trade is already pending
                for mid, s in market_states.items():
                    if s.get('active_signal'): s['active_signal'] = None

            if loop_count % 30 == 0:
                try:
                    ui.status_data["balance"] = str(await asyncio.to_thread(get_balance))
                    ui.status_data["virtual_balance"] = str(await asyncio.to_thread(get_virtual_balance))
                    ui.status_data["matic_balance"] = str(await asyncio.to_thread(get_matic_balance))
                except: pass

            loop_count += 1
            await asyncio.sleep(1)

        except KeyboardInterrupt: cleanup()
        except Exception as e:
            log_error(f"Error in main loop: {e}")
            await asyncio.sleep(5)

if __name__ == "__main__":
    import asyncio
    asyncio.run(bot_loop())
