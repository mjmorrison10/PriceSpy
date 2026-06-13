"""
Firebase service layer for PriceSpy.
Provides the same interface as SQLite but backed by Firestore.
Activated when FIREBASE_CREDENTIALS env var is set.
Otherwise falls back to SQLite.
"""
import os
import json
import uuid
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

DB_PATH = Path(__file__).parent / "pricespy.db"
FIREBASE_AVAILABLE = False

try:
    import firebase_admin
    from firebase_admin import credentials, firestore, auth
    FIREBASE_AVAILABLE = True
except ImportError:
    pass


class StorageProvider:
    """Abstract storage interface. Use get_provider() to get the active one."""

    def create_user(self, email: str, password_hash: str, display_name: str,
                    google_id: str = None) -> dict: ...

    def get_user_by_email(self, email: str) -> dict | None: ...

    def get_user_by_id(self, uid: str) -> dict | None: ...

    def create_session(self, user_id: str) -> str: ...

    def validate_session(self, token: str) -> str | None: ...

    def delete_session(self, token: str) -> None: ...

    def get_watchlist(self, user_id: str) -> list[dict]: ...

    def add_watchlist_item(self, user_id: str, data: dict) -> int: ...

    def delete_watchlist_item(self, item_id: str, user_id: str) -> None: ...

    def update_watchlist_prices(self, item_id: str, median: float, low: float,
                                 high: float, score: int, change_pct: float) -> None: ...

    def get_deal_history(self, user_id: str) -> list[dict]: ...

    def add_deal_history(self, user_id: str, data: dict) -> None: ...

    def get_alerts(self, user_id: str) -> dict: ...

    def mark_alerts_read(self, user_id: str) -> None: ...

    def add_alert(self, user_id: str, watchlist_id: str, message: str) -> None: ...

    def get_trending_searches(self, limit: int = 20) -> list[dict]: ...

    def record_search(self, query: str, category: str) -> None: ...
    def get_inventory(self, user_id: str) -> list[dict]: ...
    def add_inventory_item(self, user_id: str, data: dict) -> str: ...
    def update_inventory_item(self, item_id: str, user_id: str, data: dict) -> None: ...
    def delete_inventory_item(self, item_id: str, user_id: str) -> None: ...
    def get_inventory_stats(self, user_id: str) -> dict: ...


# ═══════════════════════════════════════════
#  SQLITE PROVIDER (local dev / fallback)
# ═══════════════════════════════════════════

class SQLiteProvider(StorageProvider):
    def __init__(self):
        self.db_path = str(DB_PATH)

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def create_user(self, email, password_hash, display_name, google_id=None):
        conn = self._connect()
        uid = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO users (id, email, password_hash, display_name, google_id) VALUES (?,?,?,?,?)",
            (uid, email, password_hash, display_name, google_id))
        conn.commit()
        conn.close()
        return {"id": uid, "email": email, "display_name": display_name}

    def get_user_by_email(self, email):
        conn = self._connect()
        row = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def get_user_by_id(self, uid):
        conn = self._connect()
        row = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def create_session(self, user_id):
        import secrets
        token = secrets.token_hex(32)
        conn = self._connect()
        conn.execute(
            "INSERT INTO sessions (token, user_id, expires_at) VALUES (?,?,datetime('now','+30 days'))",
            (token, user_id))
        conn.commit()
        conn.close()
        return token

    def validate_session(self, token):
        conn = self._connect()
        row = conn.execute(
            "SELECT user_id FROM sessions WHERE token=? AND expires_at > datetime('now')",
            (token,)).fetchone()
        conn.close()
        return row["user_id"] if row else None

    def delete_session(self, token):
        conn = self._connect()
        conn.execute("DELETE FROM sessions WHERE token=?", (token,))
        conn.commit()
        conn.close()

    def get_watchlist(self, user_id):
        conn = self._connect()
        rows = conn.execute(
            "SELECT * FROM watchlist WHERE user_id=? ORDER BY created_at DESC",
            (user_id,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def add_watchlist_item(self, user_id, data):
        conn = self._connect()
        conn.execute(
            "INSERT INTO watchlist (user_id,query,condition_filter,buy_price,platform,shipping_cost,last_median,last_low,last_high,last_score,last_checked) VALUES (?,?,?,?,?,?,?,?,?,?,datetime('now'))",
            (user_id, data["query"], data.get("condition", "all"),
             data.get("buy_price", 0), data.get("platform", "ebay"),
             data.get("shipping_cost", 0), data.get("median", 0),
             data.get("low", 0), data.get("high", 0), data.get("score", 0)))
        conn.commit()
        rid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()
        return rid

    def delete_watchlist_item(self, item_id, user_id):
        conn = self._connect()
        conn.execute("DELETE FROM watchlist WHERE id=? AND user_id=?", (item_id, user_id))
        conn.commit()
        conn.close()

    def update_watchlist_prices(self, item_id, median, low, high, score, change_pct):
        conn = self._connect()
        conn.execute(
            "UPDATE watchlist SET last_median=?, last_low=?, last_high=?, last_score=?, last_checked=datetime('now'), price_change_pct=? WHERE id=?",
            (median, low, high, score, change_pct, item_id))
        conn.commit()
        conn.close()

    def get_deal_history(self, user_id):
        conn = self._connect()
        rows = conn.execute(
            "SELECT * FROM deal_history WHERE user_id=? ORDER BY created_at DESC LIMIT 100",
            (user_id,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def add_deal_history(self, user_id, data):
        conn = self._connect()
        conn.execute(
            "INSERT INTO deal_history (user_id,item_name,detected_condition,your_price,market_median,net_profit,flip_score,verdict) VALUES (?,?,?,?,?,?,?,?)",
            (user_id, data.get("item_name"), data.get("detected_condition"),
             data.get("your_price"), data.get("market_median"),
             data.get("net_profit"), data.get("flip_score"), data.get("verdict")))
        conn.commit()
        conn.close()

    def get_alerts(self, user_id):
        conn = self._connect()
        rows = conn.execute(
            "SELECT * FROM price_alerts WHERE user_id=? ORDER BY created_at DESC LIMIT 50",
            (user_id,)).fetchall()
        conn.close()
        rlist = [dict(r) for r in rows]
        return {"alerts": rlist, "unread": sum(1 for r in rlist if not r["is_read"])}

    def mark_alerts_read(self, user_id):
        conn = self._connect()
        conn.execute("UPDATE price_alerts SET is_read=1 WHERE user_id=?", (user_id,))
        conn.commit()
        conn.close()

    def add_alert(self, user_id, watchlist_id, message):
        conn = self._connect()
        conn.execute(
            "INSERT INTO price_alerts (user_id, watchlist_id, message) VALUES (?,?,?)",
            (user_id, watchlist_id, message))
        conn.commit()
        conn.close()

    def get_trending_searches(self, limit=20):
        # SQLite version returns sample data
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT query, COUNT(*) as cnt FROM watchlist GROUP BY query ORDER BY cnt DESC LIMIT ?",
                (limit,)).fetchall()
            conn.close()
            return [{"query": r["query"], "count": r["cnt"]} for r in rows]
        except Exception:
            conn.close()
            return []

    def record_search(self, query, category):
        conn = self._connect()
        conn.execute(
            "CREATE TABLE IF NOT EXISTS search_log (id INTEGER PRIMARY KEY AUTOINCREMENT, query TEXT, category TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("INSERT INTO search_log (query, category) VALUES (?,?)", (query, category))
        conn.commit()
        conn.close()

    def get_inventory(self, user_id):
        conn = self._connect()
        conn.execute("CREATE TABLE IF NOT EXISTS inventory (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, item_name TEXT, condition TEXT, buy_price REAL, market_median REAL, platform TEXT, status TEXT DEFAULT 'bought', listed_price REAL, sold_price REAL, notes TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        rows = conn.execute("SELECT * FROM inventory WHERE user_id=? ORDER BY updated_at DESC", (user_id,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def add_inventory_item(self, user_id, data):
        conn = self._connect()
        conn.execute("CREATE TABLE IF NOT EXISTS inventory (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, item_name TEXT, condition TEXT, buy_price REAL, market_median REAL, platform TEXT, status TEXT DEFAULT 'bought', listed_price REAL, sold_price REAL, notes TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("INSERT INTO inventory (user_id, item_name, condition, buy_price, market_median, platform, status, notes) VALUES (?,?,?,?,?,?,?,?)",
                     (user_id, data.get("item_name"), data.get("condition"), data.get("buy_price"), data.get("market_median"), data.get("platform", "ebay"), data.get("status", "bought"), data.get("notes", "")))
        conn.commit()
        rid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()
        return str(rid)

    def update_inventory_item(self, item_id, user_id, data):
        conn = self._connect()
        updates = []
        params = []
        for field in ["status", "listed_price", "sold_price", "notes", "item_name", "condition", "buy_price", "market_median", "platform"]:
            if field in data:
                updates.append(f"{field}=?")
                params.append(data[field])
        if updates:
            updates.append("updated_at=datetime('now')")
            params.extend([item_id, user_id])
            conn.execute(f"UPDATE inventory SET {', '.join(updates)} WHERE id=? AND user_id=?", params)
        conn.commit()
        conn.close()

    def delete_inventory_item(self, item_id, user_id):
        conn = self._connect()
        conn.execute("DELETE FROM inventory WHERE id=? AND user_id=?", (item_id, user_id))
        conn.commit()
        conn.close()

    def get_inventory_stats(self, user_id):
        conn = self._connect()
        conn.execute("CREATE TABLE IF NOT EXISTS inventory (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, item_name TEXT, condition TEXT, buy_price REAL, market_median REAL, platform TEXT, status TEXT DEFAULT 'bought', listed_price REAL, sold_price REAL, notes TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        total = conn.execute("SELECT COUNT(*) as c, COALESCE(SUM(buy_price),0) as cost FROM inventory WHERE user_id=?", (user_id,)).fetchone()
        bought = conn.execute("SELECT COUNT(*) FROM inventory WHERE user_id=? AND status='bought'", (user_id,)).fetchone()[0]
        listed = conn.execute("SELECT COUNT(*) FROM inventory WHERE user_id=? AND status='listed'", (user_id,)).fetchone()[0]
        sold = conn.execute("SELECT COUNT(*) FROM inventory WHERE user_id=? AND status='sold'", (user_id,)).fetchone()[0]
        sold_data = conn.execute("SELECT COALESCE(SUM(sold_price),0) as revenue, COALESCE(SUM(buy_price),0) as cost FROM inventory WHERE user_id=? AND status='sold'", (user_id,)).fetchone()
        conn.close()
        return {
            "total_items": total["c"],
            "total_cost": round(total["cost"] or 0, 2),
            "bought": bought, "listed": listed, "sold": sold,
            "sold_revenue": round(sold_data["revenue"] or 0, 2),
            "sold_cost": round(sold_data["cost"] or 0, 2),
            "sold_profit": round((sold_data["revenue"] or 0) - (sold_data["cost"] or 0), 2),
        }


# ═══════════════════════════════════════════
#  FIREBASE FIRESTORE PROVIDER
# ═══════════════════════════════════════════

class FirebaseProvider(StorageProvider):
    def __init__(self):
        cred_path = os.environ.get("FIREBASE_CREDENTIALS", "")
        if not cred_path or not os.path.exists(cred_path):
            raise RuntimeError(
                "FIREBASE_CREDENTIALS must point to a valid service account JSON file")

        cred = credentials.Certificate(cred_path)
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred)
        self.db = firestore.client()

    def create_user(self, email, password_hash, display_name, google_id=None):
        uid = str(uuid.uuid4())
        self.db.collection("users").document(uid).set({
            "email": email,
            "password_hash": password_hash,
            "display_name": display_name,
            "google_id": google_id,
            "created_at": firestore.SERVER_TIMESTAMP,
        })
        return {"id": uid, "email": email, "display_name": display_name}

    def get_user_by_email(self, email):
        docs = self.db.collection("users").where("email", "==", email).limit(1).stream()
        for doc in docs:
            data = doc.to_dict()
            data["id"] = doc.id
            return data
        return None

    def get_user_by_id(self, uid):
        doc = self.db.collection("users").document(uid).get()
        if doc.exists:
            data = doc.to_dict()
            data["id"] = doc.id
            return data
        return None

    def create_session(self, user_id):
        import secrets
        token = secrets.token_hex(32)
        self.db.collection("sessions").document(token).set({
            "user_id": user_id,
            "created_at": firestore.SERVER_TIMESTAMP,
            "expires_at": datetime.now(timezone.utc).timestamp() + 30 * 86400,
        })
        return token

    def validate_session(self, token):
        doc = self.db.collection("sessions").document(token).get()
        if not doc.exists:
            return None
        data = doc.to_dict()
        if data.get("expires_at", 0) < datetime.now(timezone.utc).timestamp():
            doc.reference.delete()
            return None
        return data.get("user_id")

    def delete_session(self, token):
        self.db.collection("sessions").document(token).delete()

    def get_watchlist(self, user_id):
        docs = self.db.collection("watchlist").where("user_id", "==", user_id).order_by(
            "created_at", direction=firestore.Query.DESCENDING).stream()
        return [{**d.to_dict(), "id": d.id} for d in docs]

    def add_watchlist_item(self, user_id, data):
        ref = self.db.collection("watchlist").document()
        ref.set({
            "user_id": user_id,
            "query": data["query"],
            "condition_filter": data.get("condition", "all"),
            "buy_price": data.get("buy_price", 0),
            "platform": data.get("platform", "ebay"),
            "shipping_cost": data.get("shipping_cost", 0),
            "last_median": data.get("median", 0),
            "last_low": data.get("low", 0),
            "last_high": data.get("high", 0),
            "last_score": data.get("score", 0),
            "price_change_pct": 0,
            "last_checked": firestore.SERVER_TIMESTAMP,
            "created_at": firestore.SERVER_TIMESTAMP,
        })
        return ref.id

    def delete_watchlist_item(self, item_id, user_id):
        doc = self.db.collection("watchlist").document(item_id).get()
        if doc.exists and doc.to_dict().get("user_id") == user_id:
            doc.reference.delete()

    def update_watchlist_prices(self, item_id, median, low, high, score, change_pct):
        self.db.collection("watchlist").document(item_id).update({
            "last_median": median,
            "last_low": low,
            "last_high": high,
            "last_score": score,
            "price_change_pct": change_pct,
            "last_checked": firestore.SERVER_TIMESTAMP,
        })

    def get_deal_history(self, user_id):
        docs = self.db.collection("deal_history").where("user_id", "==", user_id).order_by(
            "created_at", direction=firestore.Query.DESCENDING).limit(100).stream()
        return [{**d.to_dict(), "id": d.id} for d in docs]

    def add_deal_history(self, user_id, data):
        self.db.collection("deal_history").add({
            "user_id": user_id,
            "item_name": data.get("item_name"),
            "detected_condition": data.get("detected_condition"),
            "your_price": data.get("your_price"),
            "market_median": data.get("market_median"),
            "net_profit": data.get("net_profit"),
            "flip_score": data.get("flip_score"),
            "verdict": data.get("verdict"),
            "created_at": firestore.SERVER_TIMESTAMP,
        })

    def get_alerts(self, user_id):
        docs = self.db.collection("price_alerts").where("user_id", "==", user_id).order_by(
            "created_at", direction=firestore.Query.DESCENDING).limit(50).stream()
        rlist = [{**d.to_dict(), "id": d.id} for d in docs]
        return {"alerts": rlist, "unread": sum(1 for r in rlist if not r.get("is_read"))}

    def mark_alerts_read(self, user_id):
        docs = self.db.collection("price_alerts").where(
            "user_id", "==", user_id).where("is_read", "==", False).stream()
        batch = self.db.batch()
        for doc in docs:
            batch.update(doc.reference, {"is_read": True})
        batch.commit()

    def add_alert(self, user_id, watchlist_id, message):
        self.db.collection("price_alerts").add({
            "user_id": user_id,
            "watchlist_id": watchlist_id,
            "message": message,
            "is_read": False,
            "created_at": firestore.SERVER_TIMESTAMP,
        })

    def get_trending_searches(self, limit=20):
        # Aggregate search_log by query
        docs = self.db.collection("search_log").stream()
        counts = {}
        for doc in docs:
            q = doc.to_dict().get("query", "")
            if q:
                counts[q] = counts.get(q, 0) + 1
        sorted_queries = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:limit]
        return [{"query": q, "count": c} for q, c in sorted_queries]

    def record_search(self, query, category):
        self.db.collection("search_log").add({
            "query": query, "category": category,
            "created_at": firestore.SERVER_TIMESTAMP,
        })

    def get_inventory(self, user_id):
        docs = self.db.collection("inventory").where("user_id", "==", user_id).order_by("updated_at", direction=firestore.Query.DESCENDING).stream()
        return [{**d.to_dict(), "id": d.id} for d in docs]

    def add_inventory_item(self, user_id, data):
        ref = self.db.collection("inventory").document()
        ref.set({"user_id": user_id, "item_name": data.get("item_name"), "condition": data.get("condition", ""), "buy_price": data.get("buy_price", 0), "market_median": data.get("market_median", 0), "platform": data.get("platform", "ebay"), "status": data.get("status", "bought"), "listed_price": data.get("listed_price", 0), "sold_price": data.get("sold_price", 0), "notes": data.get("notes", ""), "created_at": firestore.SERVER_TIMESTAMP, "updated_at": firestore.SERVER_TIMESTAMP})
        return ref.id

    def update_inventory_item(self, item_id, user_id, data):
        data["updated_at"] = firestore.SERVER_TIMESTAMP
        self.db.collection("inventory").document(item_id).update(data)

    def delete_inventory_item(self, item_id, user_id):
        self.db.collection("inventory").document(item_id).delete()

    def get_inventory_stats(self, user_id):
        docs = self.db.collection("inventory").where("user_id", "==", user_id).stream()
        items = [d.to_dict() for d in docs]
        total = len(items)
        total_cost = sum(it.get("buy_price", 0) or 0 for it in items)
        bought = sum(1 for it in items if it.get("status") == "bought")
        listed = sum(1 for it in items if it.get("status") == "listed")
        sold_items = [it for it in items if it.get("status") == "sold"]
        sold_count = len(sold_items)
        sold_revenue = sum(it.get("sold_price", 0) or 0 for it in sold_items)
        sold_cost = sum(it.get("buy_price", 0) or 0 for it in sold_items)
        return {"total_items": total, "total_cost": round(total_cost, 2), "bought": bought, "listed": listed, "sold": sold_count, "sold_revenue": round(sold_revenue, 2), "sold_cost": round(sold_cost, 2), "sold_profit": round(sold_revenue - sold_cost, 2)}


# ═══════════════════════════════════════════
#  PROVIDER FACTORY
# ═══════════════════════════════════════════

_provider = None


def get_provider() -> StorageProvider:
    global _provider
    if _provider is None:
        creds = os.environ.get("FIREBASE_CREDENTIALS", "")
        if creds and os.path.exists(creds) and FIREBASE_AVAILABLE:
            try:
                _provider = FirebaseProvider()
                print("🔥 Using Firebase Firestore")
            except Exception as e:
                print(f"⚠️ Firebase init failed ({e}), using SQLite")
                _provider = SQLiteProvider()
        else:
            _provider = SQLiteProvider()
            print("💾 Using SQLite (local)")
    return _provider


def reset_provider():
    global _provider
    _provider = None


# ═══════════════════════════════════════════
#  FIREBASE ADMIN — verify ID tokens
# ═══════════════════════════════════════════

def verify_firebase_id_token(id_token: str) -> dict | None:
    """Verify a Firebase Auth ID token (from client-side Firebase Auth).
    Returns user dict or None."""
    if not FIREBASE_AVAILABLE:
        print("⚠️ Firebase not available")
        return None
    
    # Ensure Firebase Admin is initialized
    creds = os.environ.get("FIREBASE_CREDENTIALS", "")
    if creds and os.path.exists(creds):
        try:
            if not firebase_admin._apps:
                firebase_admin.initialize_app(credentials.Certificate(creds))
                print("✅ Firebase Admin initialized for token verification")
        except Exception as e:
            print(f"⚠️ Firebase Admin init failed: {e}")
            return None
    else:
        print("⚠️ FIREBASE_CREDENTIALS not set")
        return None
    
    try:
        decoded = firebase_admin.auth.verify_id_token(id_token)
        return {
            "uid": decoded.get("uid"),
            "email": decoded.get("email", ""),
            "name": decoded.get("name", ""),
            "picture": decoded.get("picture", ""),
            "firebase_sign_in_provider": decoded.get("firebase", {}).get("sign_in_provider", ""),
        }
    except Exception as e:
        print(f"⚠️ Firebase token verification failed: {e}")
        return None
