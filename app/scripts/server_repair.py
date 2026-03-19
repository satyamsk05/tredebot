import sqlite3
import os

DB_PATH = "data/trading.db"

def fix_server_db():
    print("🚀 Starting Server Database Repair...")
    # Check for relative/absolute DB path
    db_abs = os.path.abspath(DB_PATH)
    if not os.path.exists(db_abs):
        print(f"❌ Database file not found in {db_abs}")
        return

    conn = sqlite3.connect(db_abs)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 1. Ensure 'coin' column exists
    print("🛠 Step 1: Checking schema...")
    try:
        cursor.execute("ALTER TABLE candles ADD COLUMN coin TEXT")
        print("✅ Added 'coin' column to candles table.")
    except Exception as e:
        if "duplicate column name" in str(e).lower():
            print("ℹ️ 'coin' column already exists.")
        else:
            print(f"❌ Error adding column: {e}")

    # 2. Check data distribution
    print("\n📊 Step 2: Data Summary")
    cursor.execute("SELECT coin, COUNT(*) as cnt FROM candles GROUP BY coin")
    rows = cursor.fetchall()
    has_nulls = False
    for row in rows:
        coin = row['coin']
        count = row['cnt']
        c_name = coin if coin else "NULL (OLD DATA - NOT SHOWING)"
        if coin is None: has_nulls = True
        print(f"   - {c_name}: {count} records")

    # 3. Decision
    if has_nulls:
        print("\n⚠️ Found old data without 'coin' metadata.")
        print("   Polymarket uses unique market IDs every time a candle closes.")
        print("   The new Trends logic requires the 'coin' column to be populated (e.g., 'BTC', 'ETH').")
        print("   Wait for the bot to record its first 15M candle (it will have the coin name automatically).")
    
    conn.commit()
    conn.close()
    print("\n✨ Repair Complete! Restart the bot and trends will start populating with unique coin history.")

if __name__ == "__main__":
    fix_server_db()
