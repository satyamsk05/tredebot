import sqlite3
import os
import logging
import asyncio
import time

DB_PATH = "data/trading.db"

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Candles table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS candles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            market_id TEXT,
            token_id TEXT,
            timestamp INTEGER,
            close_price REAL,
            interval INTEGER DEFAULT 5
        )
    ''')
    
    # Trades table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp INTEGER,
            market_id TEXT,
            direction TEXT,
            amount REAL,
            result TEXT,
            payout REAL,
            order_type TEXT,
            interval INTEGER DEFAULT 5,
            claimed INTEGER DEFAULT 0,
            outcome_index INTEGER DEFAULT 0
        )
    ''')
    
    # Migration: Add interval column if missing
    try:
        cursor.execute("ALTER TABLE candles ADD COLUMN interval INTEGER DEFAULT 5")
    except: pass
    try:
        cursor.execute("ALTER TABLE trades ADD COLUMN interval INTEGER DEFAULT 5")
    except: pass
    try:
        cursor.execute("ALTER TABLE trades ADD COLUMN claimed INTEGER DEFAULT 0")
    except: pass
    try:
        cursor.execute("ALTER TABLE trades ADD COLUMN outcome_index INTEGER DEFAULT 0")
    except: pass
    
    conn.commit()
    conn.close()

def save_candle(market_id, token_id, timestamp, close_price, interval=5):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO candles (market_id, token_id, timestamp, close_price, interval)
        VALUES (?, ?, ?, ?, ?)
    ''', (market_id, token_id, timestamp, close_price, interval))
    conn.commit()
    conn.close()
    logging.info(f"Saved candle for {market_id} ({interval}m) at {timestamp}: Price {close_price}")

async def async_save_candle(market_id, token_id, timestamp, close_price, interval=5):
    return await asyncio.to_thread(save_candle, market_id, token_id, timestamp, close_price, interval)

def get_last_n_candles(limit=10, market_id=None, interval=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    if interval:
        cursor.execute('''
            SELECT timestamp, close_price, interval FROM candles
            WHERE interval = ?
            ORDER BY timestamp DESC
            LIMIT ?
        ''', (interval, limit))
    elif market_id:
        cursor.execute('''
            SELECT timestamp, close_price, interval FROM candles
            WHERE market_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
        ''', (market_id, limit))
    else:
        cursor.execute('''
            SELECT timestamp, close_price, interval FROM candles
            WHERE timestamp DESC
            LIMIT ?
        ''', (limit,))
    rows = cursor.fetchall()
    conn.close()
    
    latest = [{"timestamp": row['timestamp'], "close_price": row['close_price']} for row in rows]
    return latest[::-1]

async def async_get_last_n_candles(limit=10, market_id=None, interval=None):
    return await asyncio.to_thread(get_last_n_candles, limit, market_id, interval)

def save_trade(timestamp, market_id, direction, amount, result, payout, order_type="AUTO", interval=5, outcome_index=0):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO trades (timestamp, market_id, direction, amount, result, payout, order_type, interval, claimed, outcome_index)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
    ''', (timestamp, market_id, direction, amount, result, payout, order_type, interval, outcome_index))
    conn.commit()
    conn.close()
    logging.info(f"Recorded {order_type} trade ({interval}m): {result} (${payout-amount if result=='WIN' else -amount})")

async def async_save_trade(timestamp, market_id, direction, amount, result, payout, order_type="AUTO", interval=5, outcome_index=0):
    return await asyncio.to_thread(save_trade, timestamp, market_id, direction, amount, result, payout, order_type, interval, outcome_index)

def get_unclaimed_trades():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM trades WHERE result = 'WIN' AND claimed = 0")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

def mark_as_claimed(trade_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE trades SET claimed = 1 WHERE id = ?", (trade_id,))
    conn.commit()
    conn.close()

def get_24h_stats(interval=None):
    now = int(time.time())
    one_day_ago = now - (24 * 3600)
    conn = get_db_connection()
    cursor = conn.cursor()
    if interval:
        cursor.execute('''
            SELECT result, amount, payout FROM trades
            WHERE timestamp > ? AND interval = ?
        ''', (one_day_ago, interval))
    else:
        cursor.execute('''
            SELECT result, amount, payout FROM trades
            WHERE timestamp > ?
        ''', (one_day_ago,))
    rows = cursor.fetchall()
    conn.close()
    
    wins = sum(1 for r in rows if r['result'] == "WIN")
    losses = sum(1 for r in rows if r['result'] == "LOSS")
    total_profit = sum((r['payout'] - r['amount']) if r['result'] == "WIN" else -r['amount'] for r in rows)
    total_volume = sum(r['amount'] for r in rows)
    
    return {
        "wins": wins,
        "losses": losses,
        "total_profit": total_profit,
        "total_volume": total_volume
    }

async def async_get_24h_stats(interval=None):
    return await asyncio.to_thread(get_24h_stats, interval)

# Initialize on import
init_db()
