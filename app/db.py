import sqlite3
import os
import logging

DB_PATH = "data/history.db"

def get_db_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS candles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            market_id TEXT NOT NULL,
            token_id TEXT NOT NULL,
            timestamp INTEGER NOT NULL,
            close_price REAL NOT NULL
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp INTEGER NOT NULL,
            market_id TEXT,
            direction TEXT,
            amount REAL,
            result TEXT, -- 'WIN', 'LOSS'
            payout REAL,
            order_type TEXT -- 'AUTO', 'MANUAL'
        )
    ''')
    conn.commit()
    conn.close()

def save_candle(market_id, token_id, timestamp, close_price):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO candles (market_id, token_id, timestamp, close_price)
        VALUES (?, ?, ?, ?)
    ''', (market_id, token_id, timestamp, close_price))
    conn.commit()
    conn.close()
    logging.info(f"Saved candle for {market_id} at {timestamp}: Price {close_price}")

def get_last_n_candles(limit=3):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT timestamp, close_price FROM candles
        ORDER BY timestamp DESC
        LIMIT ?
    ''', (limit,))
    rows = cursor.fetchall()
    conn.close()
    
    # Return full objects in chronological order
    latest = [{"timestamp": row['timestamp'], "close_price": row['close_price']} for row in rows]
    return latest[::-1]

def save_trade(timestamp, market_id, direction, amount, result, payout, order_type="AUTO"):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO trades (timestamp, market_id, direction, amount, result, payout, order_type)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (timestamp, market_id, direction, amount, result, payout, order_type))
    conn.commit()
    conn.close()
    logging.info(f"Recorded {order_type} trade: {result} (${payout-amount if result=='WIN' else -amount})")

def get_24h_stats():
    now = int(time.time())
    one_day_ago = now - (24 * 3600)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT result, amount, payout FROM trades
        WHERE timestamp > ?
    ''', (one_day_ago,))
    rows = cursor.fetchall()
    conn.close()
    
    stats = {
        "wins": 0,
        "losses": 0,
        "total_profit": 0,
        "total_volume": 0
    }
    
    for row in rows:
        stats["total_volume"] += row['amount']
        if row['result'] == 'WIN':
            stats["wins"] += 1
            stats["total_profit"] += (row['payout'] - row['amount'])
        else:
            stats["losses"] += 1
            stats["total_profit"] -= row['amount']
            
    return stats
    
import time

# Initialize on import
init_db()
