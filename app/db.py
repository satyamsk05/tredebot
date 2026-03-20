import sqlite3
import os
import logging
import asyncio
import time

DB_PATH = "data/trading.db"

def get_db_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
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
            interval INTEGER DEFAULT 5,
            coin TEXT
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
    
    # Indices for performance (Lightweight Optimization)
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_candles_ts ON candles (timestamp)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_trades_ts ON trades (timestamp)')
    
    try:
        cursor.execute("ALTER TABLE candles ADD COLUMN interval INTEGER DEFAULT 5")
    except: pass
    
    try:
        cursor.execute("ALTER TABLE candles ADD COLUMN coin TEXT")
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

def save_candle(market_id, token_id, timestamp, close_price, interval=5, coin=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    # Ensure uniqueness (simple check before insert)
    cursor.execute('SELECT 1 FROM candles WHERE coin = ? AND interval = ? AND timestamp = ?', (coin, interval, timestamp))
    if cursor.fetchone():
        conn.close()
        return

    cursor.execute('''
        INSERT INTO candles (market_id, token_id, timestamp, close_price, interval, coin)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (market_id, token_id, timestamp, close_price, interval, coin))
    conn.commit()
    conn.close()
    logging.info(f"Saved candle for {market_id} ({interval}m) at {timestamp}: Price {close_price}")

async def async_save_candle(market_id, token_id, timestamp, close_price, interval=5, coin=None):
    return await asyncio.to_thread(save_candle, market_id, token_id, timestamp, close_price, interval, coin)

def get_last_n_candles(limit=10, market_id=None, interval=None, coin=None, min_ts=0):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Base query logic with min_ts support
    if coin and interval:
        cursor.execute('''
            SELECT timestamp, close_price FROM candles
            WHERE coin = ? AND interval = ? AND timestamp >= ?
            GROUP BY timestamp
            ORDER BY timestamp DESC
            LIMIT ?
        ''', (coin, interval, min_ts, limit))
    elif interval:
        cursor.execute('''
            SELECT timestamp, close_price FROM candles
            WHERE interval = ? AND timestamp >= ?
            GROUP BY timestamp
            ORDER BY timestamp DESC
            LIMIT ?
        ''', (interval, min_ts, limit))
    elif market_id:
        cursor.execute('''
            SELECT timestamp, close_price FROM candles
            WHERE market_id = ? AND timestamp >= ?
            ORDER BY timestamp DESC
            LIMIT ?
        ''', (market_id, min_ts, limit))
    else:
        cursor.execute('''
            SELECT timestamp, close_price FROM candles
            WHERE timestamp >= ?
            ORDER BY timestamp DESC
            LIMIT ?
        ''', (min_ts, limit))
    rows = cursor.fetchall()
    conn.close()
    
    latest = [{"timestamp": row['timestamp'], "close_price": row['close_price']} for row in rows]
    return latest[::-1]

async def async_get_last_n_candles(limit=10, market_id=None, interval=None, coin=None, min_ts=0):
    return await asyncio.to_thread(get_last_n_candles, limit, market_id, interval, coin, min_ts)

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

def get_recent_trades(limit=10):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, timestamp, market_id, direction, amount, result, payout, interval 
        FROM trades 
        ORDER BY timestamp DESC 
        LIMIT ?
    ''', (limit,))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

async def async_get_recent_trades(limit=10):
    return await asyncio.to_thread(get_recent_trades, limit)

def get_stats_period(days=1, interval=None):
    now = int(time.time())
    since = now - (days * 24 * 3600)
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = "SELECT result, amount, payout FROM trades WHERE timestamp > ?"
    params = [since]
    
    if interval:
        query += " AND interval = ?"
        params.append(interval)
        
    cursor.execute(query, params)
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
        "total_volume": total_volume,
        "days": days
    }

async def async_get_stats_period(days=1, interval=None):
    return await asyncio.to_thread(get_stats_period, days, interval)

def get_24h_stats(interval=None):
    return get_stats_period(days=1, interval=interval)

async def async_get_24h_stats(interval=None):
    return await asyncio.to_thread(get_24h_stats, interval)

def export_candles_to_file(coin, days=7, interval=15):
    """Generates a CSV file for the last N days of data for a specific coin."""
    now = int(time.time())
    since = now - (days * 24 * 3600)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT datetime(timestamp, 'unixepoch') as UTC_Time, timestamp, close_price 
        FROM candles 
        WHERE coin = ? AND interval = ? AND timestamp >= ?
        ORDER BY timestamp ASC
    ''', (coin.upper(), interval, since))
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        return None
        
    os.makedirs("data/exports", exist_ok=True)
    file_path = f"data/exports/{coin.lower()}_{days}d_history_{int(time.time())}.csv"
    
    import csv
    with open(file_path, "w", newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["UTC_Time", "Timestamp", "Close_Price"])
        for row in rows:
            writer.writerow([row['UTC_Time'], row['timestamp'], row['close_price']])
            
    return file_path

# Initialize on import
init_db()
