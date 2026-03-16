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
    FUNDER_ADDRESS, ENABLE_5M, ENABLE_15M, COINS
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
    
    # Define supported markets dynamically
    MARKETS = []
    
    # Initialize data/market_config.json if not exists
    MARKET_CONFIG_FILE = "data/market_config.json"
    config = {}
    if os.path.exists(MARKET_CONFIG_FILE):
        try:
            with open(MARKET_CONFIG_FILE, "r") as f:
                config = json.load(f)
        except: pass
    
    # Default: SOL 15m ON, others OFF
    default_config = {}
    for coin in COINS:
        default_config[f"{coin.lower()}_5m"] = False
        default_config[f"{coin.lower()}_15m"] = False
    
    # Explicit user request: Default SOL 15m ON
    if "sol_15m" in default_config:
        default_config["sol_15m"] = True
    
    # Merge existing config or use default
    if not config:
        config = default_config
        with open(MARKET_CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=4)
    
    # Build live markets list based on config file
    for key, enabled in config.items():
        if enabled:
            # key format: btc_5m
            parts = key.split("_")
            coin = parts[0].upper()
            interval = int(parts[1].replace("m", ""))
            MARKETS.append({"id": key, "coin": coin, "interval": interval, "label": f"{coin}_{interval}m"})
    
    # Primary market for UI updates (first enabled)
    PRIMARY_MARKET_ID = MARKETS[0]['id'] if MARKETS else None
    
    # Initialize Market States
    market_states = {}
    for m in MARKETS:
        market_states[m['id']] = {
            "last_ts": 0,
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
    
    # Load and show current martingale mode
    m_mode = "STD"
    if os.path.exists("data/ui_config.json"):
        try:
            with open("data/ui_config.json", "r") as f:
                cfg = json.load(f)
                if cfg.get("martingale_mode") == "test":
                    m_mode = "TEST"
        except: pass
    ui.status_data["martingale_mode"] = m_mode
    ui.status_data["pending_trade"] = "None"

    loop_count = 0
    last_redemption_check = 0
    
    matic_bal = get_matic_balance()
    log_info(f"System Initialized. Signer MATIC Balance: {matic_bal} MATIC")

    log_info("Consolidating System - Launching Telegram Bot UI...")
    
    # Send startup notification to Telegram
    send_telegram_notify(
        "╔══════════════════════════╗\n"
        "║   📈  NODE INITIALIZED  ║\n"
        "╚══════════════════════════╝\n\n"
        "Strat  »  BTC 3-Streak Reversal\n"
        f"Base   »  ${INITIAL_BET_AMOUNT}\n"
        "Window »  Multi-TF (5m/15m)\n"
        f"Mode   »  {'SIMULATION 🧪' if DRY_RUN else 'LIVE 💸'}\n"
        f"Gas    »  {matic_bal} MATIC\n"
        f"Beat   »  {datetime.now().strftime('%H:%M:%S')}\n\n"
        "———————————————————"
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
            
            # Hot-Reload active markets from config
            from dotenv import load_dotenv
            load_dotenv(override=True)
            e_5m = os.getenv("ENABLE_5M", "true").lower() == "true"
            e_15m = os.getenv("ENABLE_15M", "true").lower() == "true"

            MARKET_CONFIG_FILE = "data/market_config.json"
            if os.path.exists(MARKET_CONFIG_FILE):
                try:
                    with open(MARKET_CONFIG_FILE, "r") as f:
                        market_config = json.load(f)
                except: 
                    market_config = {}
            else:
                market_config = {}

            # Rebuild MARKETS list to respect hot-reloaded config
            MARKETS = []
            for key, enabled in market_config.items():
                if enabled:
                    parts = key.split("_")
                    coin = parts[0].upper()
                    if coin not in COINS: continue
                    
                    interval = int(parts[1].replace("m", ""))
                    if interval == 5 and not e_5m: continue
                    if interval == 15 and not e_15m: continue
                    
                    MARKETS.append({"id": key, "coin": coin, "interval": interval, "label": f"{coin}_{interval}m"})
            
            # Update PRIMARY_MARKET_ID and UI display
            if MARKETS:
                PRIMARY_MARKET_ID = MARKETS[0]['id']
                # Show all enabled TFs in the UI header
                all_tfs = ", ".join([m['label'] for m in MARKETS])
                ui.status_data["active_market"] = all_tfs
            else:
                PRIMARY_MARKET_ID = None
                ui.status_data["active_market"] = "None"

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

                if m_floor_ts > state['last_ts']:
                    # Only increment if it's not the very first immediate trigger
                    if state['last_ts'] != 0:
                        state['startup_candles'] += 1
                    state['last_ts'] = m_floor_ts
                    log_info(f"[{m_label}] CANDLE CLOSED - Processing: {datetime.fromtimestamp(m_floor_ts-interval_sec).strftime('%H:%M')}")
                    
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
                                            interval=interval,
                                            outcome_index=outcome_idx
                                        )
                                        
                                        send_telegram_notify(
                                            "╔══════════════════════════╗\n"
                                            f"║   🏆  WIN · {m_label:<10}    ║\n"
                                            "╚══════════════════════════╝\n\n"
                                            f"Payout »  +${payout:.2f}\n"
                                            f"Close  »  {close_price}\n"
                                            "Reset  »  L1\n\n"
                                            "————————————————"
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
                                            "╔══════════════════════════╗\n"
                                            f"║   ❌  LOSS · {m_label:<9}   ║\n"
                                            "╚══════════════════════════╝\n\n"
                                            f"Loss   »  -${bet_amount:.2f}\n"
                                            f"Close  »  {close_price}\n"
                                            f"Next   »  L{mg.get_step(m_label)+1} · ${mg.get_bet(m_label)}\n\n"
                                            "——————————————————"
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
                                        # Set active signal for retry loop
                                        next_market = get_active_market(coin=m_coin, offset_minutes=0, interval=interval)
                                        if next_market:
                                            state['active_signal'] = {
                                                "direction": trade_signal,
                                                "retry_until": now_ts + 30,
                                                "amount": amount,
                                                "timestamp": next_market['timestamp'],
                                                "question": next_market.get('question', ''),
                                                "notified_retry": False
                                            }
                                            log_info(f"[{m_label}] {trade_signal} Signal! Entry window open for 30s.")
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
                                    "╔══════════════════════════╗\n"
                                    f"║   🎯  AUTO · {m_label:<9}   ║\n"
                                    "╚══════════════════════════╝\n\n"
                                    f"Time   »  {exec_time}\n"
                                    f"Amt    »  ${signal['amount']}\n"
                                    f"Side   »  {signal['direction']} {'▲' if signal['direction'] == 'YES' else '▼'}\n\n"
                                    "——————————————————\n"
                                    f"Market »  {m_coin} Up or Down\n"
                                    f"{signal['question'].split('Up or Down ')[-1]}\n"
                                    "————————————————————"
                                )
                            else:
                                if not signal.get('notified_retry'):
                                    signal['notified_retry'] = True
                                    send_telegram_notify(
                                        f"⚠️  {m_label} Entry Failed!\n"
                                        f"Liquidity issues or rejection.\n"
                                        f"🔄 Retrying for 30s..."
                                    )
                    else:
                        log_warning(f"[{m_label}] Trade window EXPIRED (30s) for {signal['direction']}. No liquidity found.")
                        send_telegram_notify(
                            f"❌  {m_label} AUTO MISSED!\n"
                            f"Window expired after 30s retries.\n"
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

                    # Refresh mode too
                    m_mode = "STD"
                    if os.path.exists("data/ui_config.json"):
                        try:
                            with open("data/ui_config.json", "r") as f:
                                cfg = json.load(f)
                                if cfg.get("martingale_mode") == "test":
                                    m_mode = "TEST"
                        except: pass
                    ui.status_data["martingale_mode"] = m_mode
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
                                        "╔══════════════════════════╗\n"
                                        "║  💰  FINANCIAL OVERVIEW ║\n"
                                        "╚══════════════════════════╝\n\n"
                                        f"Payout »  ${payout:.2f} USDC.e\n"
                                        f"Wallet »  {wallet[:6]}...{wallet[-4:]}\n\n"
                                        "———————————————————\n"
                                        "~ Auto-claim processed ~\n"
                                        "———————————————————"
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
