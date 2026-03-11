import json,os,requests
from datetime import datetime, timedelta

FILE="data/history.json"
SESSION_FILE="data/candles.json"
SYNC_FILE="data/sync_state.json"

def load_json(path, default=[]):
    if not os.path.exists(path):
        return default
    with open(path,"r") as f:
        try:
            return json.load(f)
        except:
            return default

def save_json(path, data):
    with open(path,"w") as f:
        json.dump(data, f, indent=4)

def load_history(): return load_json(FILE, [])
def save_history(data): save_json(FILE, data)

def load_sync(): return load_json(SYNC_FILE, {})
def save_sync(data): save_json(SYNC_FILE, data)

def add_result(coin, result, timestamp):
    history = load_history()
    sync = load_sync()
    
    last_ts = sync.get(coin, 0)
    
    if timestamp > last_ts:
        # Format: [{"time": "HH:MM", "ETH": "UP", "SOL": "DOWN"}, ...]
        time_str = datetime.fromtimestamp(timestamp/1000).strftime('%H:%M')
        
        # Find if a record for this timestamp already exists
        # Since all coins sync at once, they usually share the same timestamp
        found = False
        for entry in history:
            if entry.get("_ts") == timestamp:
                entry[coin] = result
                found = True
                break
        
        if not found:
            new_entry = {"time": time_str, "_ts": timestamp, coin: result}
            history.append(new_entry)
        
        sync[coin] = timestamp
        # Keep only last 200 entries
        history = history[-200:]
        
        save_history(history)
        save_sync(sync)
        return True
    return False

def last_candles(coin, n=5):
    history = load_history()
    results = []
    for entry in history:
        if coin in entry:
            results.append(entry[coin])
    return results[-n:]

def get_poly_result(coin, timestamp_ms, interval=15):
    # Polymarket uses floor timestamp (start of interval) in seconds
    ts_sec = int(timestamp_ms / 1000)
    slug = f"{coin.lower()}-updown-{interval}m-{ts_sec}"
    url = f"https://gamma-api.polymarket.com/markets/slug/{slug}"
    
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 404:
            return None, None
        
        data = response.json()
        prices = data.get("outcomePrices") # e.g. '["1", "0"]' or '["0", "1"]'
        if isinstance(prices, str):
            try:
                prices = json.loads(prices)
            except:
                pass
        
        if prices == ["1", "0"]:
            return "UP", 1.0
        elif prices == ["0", "1"]:
            return "DOWN", 0.0
        else:
            # Market might not be resolved yet
            return None, None
    except Exception as e:
        import logging
        logging.error(f"Error fetching Polymarket slug {slug}: {e}")
        return None, None

def sync_history(coin, interval=15):
    # We want the market that just closed. 
    now = datetime.now()
    # Floor to nearest interval
    minutes = (now.minute // interval) * interval
    # The candle that JUST closed started 'interval' minutes ago
    close_time = now.replace(minute=minutes, second=0, microsecond=0)
    
    # Calculate start_time by subtracting interval minutes
    # This handles hour roll-over correctly via timedelta
    start_time = close_time - timedelta(minutes=interval)
        
    timestamp_ms = int(start_time.timestamp() * 1000)
    
    result, price = get_poly_result(coin, timestamp_ms, interval)
    
    if result:
        added = add_result(coin, result, timestamp_ms)
        return result, price, added
    return None, None, False

def recover_history(coin, interval=15):
    sync = load_sync()
    last_ts = sync.get(coin, 0)
    
    # If no history, start from 2 hours ago (24 slots for 5m, 8 slots for 15m)
    if last_ts == 0:
        last_ts = int((datetime.now().timestamp() - (8 * interval * 60)) * 1000) # Approx 2 hours
        # Round to nearest interval start
        last_ts = (last_ts // (interval * 60 * 1000)) * (interval * 60 * 1000)

    current_ts = int((datetime.now().timestamp() // (interval * 60)) * (interval * 60) * 1000)
    
    recovered_count = 0
    # Iterate every interval minutes from last_ts + interval to now
    check_ts = last_ts + (interval * 60 * 1000)
    while check_ts < current_ts:
        result, _ = get_poly_result(coin, check_ts, interval)
        if result:
            if add_result(coin, result, check_ts):
                recovered_count += 1
        check_ts += (interval * 60 * 1000)
        
    return recovered_count
