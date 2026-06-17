"""Database initialization — runs on import. Creates all tables if missing."""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "pricespy.db"

def init_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY, email TEXT UNIQUE, password_hash TEXT,
            google_id TEXT, display_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY, user_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS watchlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, query TEXT,
            condition_filter TEXT DEFAULT 'all', buy_price REAL DEFAULT 0,
            platform TEXT DEFAULT 'ebay', store_tier TEXT DEFAULT 'none', shipping_cost REAL DEFAULT 0,
            last_median REAL, last_low REAL, last_high REAL,
            last_score INTEGER, last_checked TIMESTAMP,
            price_change_pct REAL DEFAULT 0, alert_enabled INTEGER DEFAULT 1,
            alert_threshold REAL DEFAULT -15.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS deal_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT,
            item_name TEXT, detected_condition TEXT,
            your_price REAL, market_median REAL, net_profit REAL,
            flip_score INTEGER, verdict TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS price_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT,
            watchlist_id INTEGER, message TEXT,
            is_read INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT,
            item_name TEXT, condition TEXT, buy_price REAL,
            market_median REAL, platform TEXT,
            status TEXT DEFAULT 'bought', listed_price REAL,
            sold_price REAL, notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS search_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, query TEXT,
            category TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS ebay_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT UNIQUE,
            access_token_enc TEXT, refresh_token_enc TEXT,
            expires_at TIMESTAMP, scope TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    # Migration: add store_tier column if missing
    try:
        conn.execute("ALTER TABLE watchlist ADD COLUMN store_tier TEXT DEFAULT 'none'")
        conn.commit()
    except Exception:
        pass
    # Migration: add ebay_tokens table if missing
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ebay_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT UNIQUE,
                access_token_enc TEXT, refresh_token_enc TEXT,
                expires_at TIMESTAMP, scope TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
    except Exception:
        pass
    conn.close()

init_db()
print("Database tables initialized")
