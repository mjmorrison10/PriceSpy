#!/usr/bin/env python3
"""
PriceSpy — eBay-only flip analyzer.
Real eBay sold/active data only. No synthetic listings.
Optional PriceCharting fallback for games/collectibles.
"""
import json
import os
import re
import urllib.parse
import traceback
import base64
import random
import hashlib
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("PriceSpy")

# Token / auth helpers
from pathlib import Path
import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, render_template, request, send_file, make_response
import sys as _sys, os as _os
_this_dir = _os.path.dirname(_os.path.abspath(__file__))
if _this_dir not in _sys.path:
    _sys.path.insert(0, _this_dir)
from auth_routes import register_routes
from db_init import init_db
from firebase_service import get_provider, verify_firebase_id_token

try:
    from cryptography.fernet import Fernet
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False

# Token / auth helpers
def _get_user_id_from_request() -> str | None:
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not token:
        token = request.args.get("token", "")
    if not token:
        return None
    fb_user = verify_firebase_id_token(token)
    if fb_user:
        return fb_user["uid"]
    return get_provider().validate_session(token)

# Token encryption helper
def _get_fernet() -> Fernet | None:
    if not CRYPTO_AVAILABLE:
        return None
    key = _os.environ.get("SECRET_KEY", "pricespy-default-secret-key-change-in-production")
    key_bytes = base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest())
    return Fernet(key_bytes)

def _encrypt_token(token: str) -> str:
    f = _get_fernet()
    if f:
        return f.encrypt(token.encode()).decode()
    return token

def _decrypt_token(encrypted: str) -> str:
    f = _get_fernet()
    if f:
        return f.decrypt(encrypted.encode()).decode()
    return encrypted

# ── Configuration ────────────────────────────────────────────────────────
EBAY_CLIENT_ID = os.environ.get("EBAY_CLIENT_ID", "").strip()
EBAY_CLIENT_SECRET = os.environ.get("EBAY_CLIENT_SECRET", "").strip()
EBAY_OAUTH_URL = "https://api.ebay.com/identity/v1/oauth2/token"
EBAY_API_BASE = "https://api.ebay.com"
EBAY_FINDING_API = "https://svcs.ebay.com/services/search/FindingService/v1"

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
ENABLE_PRICECHARTING = os.environ.get("ENABLE_PRICECHARTING", "true").lower() == "true"

EBAY_VERIFICATION_TOKEN = os.environ.get("EBAY_VERIFICATION_TOKEN", "pricespy-ebay-notification-token-2024")

PRICE_CACHE: dict[str, dict] = {}
SOLD_SOURCE_DEBUG: dict[str, dict] = {}
SESSION = requests.Session()
_adapter = requests.adapters.HTTPAdapter(pool_connections=20, pool_maxsize=20)
SESSION.mount("http://", _adapter)
SESSION.mount("https://", _adapter)
SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
})

PERIOD_DAYS = {
    "1w": 7, "1m": 30, "3m": 90, "6m": 180,
    "1y": 365, "2y": 730, "3y": 1095,
    "5y": 1825, "10y": 3650,
}

# ── eBay Conditions ──────────────────────────────────────────────────────
# Canonical keys used across the app. Map to eBay condition IDs.
EBAY_COND = {
    "new":              {"id": "1000", "label": "🆕 New", "ebay": "New"},
    "new_other":        {"id": "1500", "label": "📦 New Other", "ebay": "New other (see details)"},
    "new_defects":      {"id": "1750", "label": "⚠️ New w/ Defects", "ebay": "New with defects"},
    "manufacturer_refurbished": {"id": "2000", "label": "🔧 Mfr Refurbished", "ebay": "Manufacturer refurbished"},
    "seller_refurbished": {"id": "2500", "label": "🔧 Seller Refurbished", "ebay": "Seller refurbished"},
    "used":             {"id": "3000", "label": "👌 Used", "ebay": "Used"},
    "very_good":        {"id": "4000", "label": "👍 Very Good", "ebay": "Very Good"},
    "good":             {"id": "5000", "label": "✅ Good", "ebay": "Good"},
    "acceptable":       {"id": "6000", "label": "⚠️ Acceptable", "ebay": "Acceptable"},
    "for_parts":        {"id": "7000", "label": "🔧 For Parts", "ebay": "For parts or not working"},
}

# Map loose text to canonical condition
CONDITION_ALIASES = {
    "new": "new", "brand new": "new", "factory sealed": "new", "sealed": "new", "deadstock": "new", "mint": "new", "never opened": "new", "unopened": "new",
    "new other": "new_other", "new with box": "new_other", "open box": "new_other", "like new": "new_other", "near mint": "new_other", "excellent": "new_other",
    "new with defects": "new_defects", "new defects": "new_defects",
    "manufacturer refurbished": "manufacturer_refurbished", "mfr refurbished": "manufacturer_refurbished", "refurbished": "manufacturer_refurbished",
    "seller refurbished": "seller_refurbished",
    "used": "used", "pre-owned": "used", "preowned": "used", "pre owned": "used",
    "very good": "very_good", "vg": "very_good", "great": "very_good", "lightly used": "very_good",
    "good": "good", "used good": "good",
    "acceptable": "acceptable", "fair": "acceptable", "worn": "acceptable", "heavy wear": "acceptable", "beater": "acceptable",
    "for parts": "for_parts", "parts": "for_parts", "not working": "for_parts", "broken": "for_parts", "damaged": "for_parts", "repair": "for_parts", "as is": "for_parts", "as-is": "for_parts", "defective": "for_parts",
}

# ── eBay Fee Engine ──────────────────────────────────────────────────────
EBAY_CATEGORY_FVF = {
    "default": 13.25,
    "sneakers": 8.0,
    "watches": 15.0,
    "books": 14.6,
    "musical_instruments": 6.0,
    "video_games": 13.25,
    "electronics": 13.25,
    "trading_cards": 13.25,
    "fashion": 13.25,
    "toys": 13.25,
    "vehicles": 13.25,
    "home": 13.25,
    "health": 13.25,
    "sporting": 13.25,
}

EBAY_STORE_TIERS = {
    "none":        {"subscription": 0,    "discount": 0},
    "basic":       {"subscription": 21.95, "discount": 1.25},
    "premium":     {"subscription": 59.95, "discount": 1.75},
    "anchor":      {"subscription": 299.95,"discount": 3.25},
    "enterprise":  {"subscription": 2999.95,"discount": 3.25},
}

def _ebay_fvf_pct(category: str, store_tier: str = "none") -> float:
    base = EBAY_CATEGORY_FVF.get(category, EBAY_CATEGORY_FVF["default"])
    discount = EBAY_STORE_TIERS.get(store_tier, EBAY_STORE_TIERS["none"])["discount"]
    return max(0, base - discount)



def _calculate_ebay_fees(sell_price: float, shipping_cost: float = 0.0,
                         category: str = "default", store_tier: str = "none",
                         promoted_rate: float = 0.0) -> dict:
    """Return a complete eBay fee breakdown."""
    fvf_pct = _ebay_fvf_pct(category, store_tier)
    fvf = sell_price * (fvf_pct / 100)
    per_order = 0.30 if sell_price > 10 else 0.0  # eBay insertion/order fee approximation
    promoted = sell_price * (promoted_rate / 100)
    # Managed payments is now included in eBay's FVF for most sellers; no separate 2.9%.
    total_fees = fvf + per_order + promoted
    net = sell_price - total_fees - shipping_cost
    return {
        "platform": "eBay",
        "sell_price": round(sell_price, 2),
        "shipping_cost": round(shipping_cost, 2),
        "category": category,
        "store_tier": store_tier,
        "fvf_pct": round(fvf_pct, 2),
        "fvf": round(fvf, 2),
        "per_order_fee": round(per_order, 2),
        "promoted_fee": round(promoted, 2),
        "total_fees": round(total_fees, 2),
        "net_proceeds": round(sell_price - total_fees, 2),
    }

def _calculate_net_profit(sell_price: float, buy_price: float, shipping_cost: float = 0.0,
                          category: str = "default", store_tier: str = "none",
                          promoted_rate: float = 0.0) -> dict:
    fees = _calculate_ebay_fees(sell_price, shipping_cost, category, store_tier, promoted_rate)
    net_profit = sell_price - buy_price - fees["total_fees"] - shipping_cost
    margin_pct = (net_profit / buy_price * 100) if buy_price > 0 else 0
    return {
        **fees,
        "shipping_cost": round(shipping_cost, 2),
        "buy_price": round(buy_price, 2),
        "net_profit": round(net_profit, 2),
        "net_margin_pct": round(margin_pct, 1),
    }

# ── Flask App ────────────────────────────────────────────────────────────
app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024
UPLOAD_FOLDER = Path(__file__).parent / "uploads"
UPLOAD_FOLDER.mkdir(exist_ok=True)

@app.route("/health")
def health():
    return jsonify({"status": "ok"}), 200

@app.route("/policy")
def policy():
    return render_template("policy.html")

@app.route("/account-deletion")
def account_deletion_page():
    return render_template("policy.html", section="account-deletion")

@app.route("/")
def index():
    path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "templates", "index.html")
    resp = make_response(send_file(path, mimetype="text/html"))
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

# ── eBay OAuth ───────────────────────────────────────────────────────────
EBAY_TOKEN_CACHE = {"token": None, "expires_at": 0}

def _get_ebay_token() -> str | None:
    if not EBAY_CLIENT_ID or not EBAY_CLIENT_SECRET:
        return None
    
    # Check cache
    now = datetime.now(timezone.utc).timestamp()
    if EBAY_TOKEN_CACHE["token"] and EBAY_TOKEN_CACHE["expires_at"] > now + 60:
        return EBAY_TOKEN_CACHE["token"]

    creds = base64.b64encode(f"{EBAY_CLIENT_ID}:{EBAY_CLIENT_SECRET}".encode()).decode()
    try:
        r = SESSION.post(
            EBAY_OAUTH_URL,
            headers={"Authorization": f"Basic {creds}", "Content-Type": "application/x-www-form-urlencoded"},
            data="grant_type=client_credentials&scope=https://api.ebay.com/oauth/api_scope",
            timeout=15,
        )
        if r.status_code == 200:
            data = r.json()
            token = data.get("access_token")
            expires_in = data.get("expires_in", 7200)
            EBAY_TOKEN_CACHE["token"] = token
            EBAY_TOKEN_CACHE["expires_at"] = now + expires_in
            return token
        print(f"eBay OAuth failed: {r.status_code} {r.text[:200]}")
    except Exception as e:
        print(f"eBay OAuth error: {e}")
    return None

# ── eBay Taxonomy API: category suggestions ───────────────────────────────
def _ebay_category_suggestions(query: str) -> list[dict]:
    token = _get_ebay_token()
    if not token:
        return []
    try:
        r = SESSION.get(
            f"{EBAY_API_BASE}/commerce/taxonomy/v1/category_tree/0/get_category_suggestions",
            params={"q": query},
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        if r.status_code != 200:
            return []
        data = r.json()
        return data.get("categorySuggestions", [])[:8]
    except Exception as e:
        print(f"eBay taxonomy error: {e}")
    return []

def _detect_ebay_category(query: str, category_id: str = "") -> str:
    if category_id:
        # Try to map eBay category ID to our internal category
        fvf = _ebay_category_fvf(category_id)
        for k, v in EBAY_CATEGORY_FVF.items():
            if v == fvf:
                return k
    q = query.lower()
    if any(k in q for k in ["jordan", "dunk", "air force", "sneaker", "yeezy", "trainer", "shoe"]):
        return "sneakers"
    if any(k in q for k in ["watch", "rolex", "apple watch", "omega", "cartier"]):
        return "watches"
    if any(k in q for k in ["book", "textbook", "comic", "manga"]):
        return "books"
    if any(k in q for k in ["guitar", "fender", "gibson", "drum", "keyboard", "piano", "amplifier", "amp"]):
        return "musical_instruments"
    if any(k in q for k in ["pokemon", "trading card", "mtg", "magic the gathering", "yugioh", "sports card"]):
        return "trading_cards"
    if any(k in q for k in ["nintendo", "playstation", "xbox", "game", "console", "gameboy", "gamecube"]):
        return "video_games"
    if any(k in q for k in ["iphone", "samsung", "pixel", "macbook", "laptop", "camera", "headphone", "tablet", "phone"]):
        return "electronics"
    if any(k in q for k in ["car", "truck", "motorcycle", "suv", "vehicle", "toyota", "ford", "honda", "harley"]):
        return "vehicles"
    if any(k in q for k in ["lego", "toy", "action figure", "doll", "plush"]):
        return "toys"
    if any(k in q for k in ["shirt", "jacket", "pants", "dress", "bag", "wallet", "purse", "clothing"]):
        return "fashion"
    return "default"

def _ebay_category_fvf(category_id: str) -> float:
    """Map eBay category ID to our FVF category."""
    token = _get_ebay_token()
    if not token or not category_id:
        return EBAY_CATEGORY_FVF["default"]
    try:
        r = SESSION.get(
            f"{EBAY_API_BASE}/commerce/taxonomy/v1/category_tree/0/category_{category_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        if r.status_code != 200:
            return EBAY_CATEGORY_FVF["default"]
        cat = r.json()
        path = cat.get("categoryPath", "")
        name = (cat.get("categoryName", "") + " " + path).lower()
        if any(k in name for k in ["sneaker", "athletic shoe"]):
            return EBAY_CATEGORY_FVF["sneakers"]
        if any(k in name for k in ["watch", "wristwatch"]):
            return EBAY_CATEGORY_FVF["watches"]
        if any(k in name for k in ["book", "textbook", "comic", "manga"]):
            return EBAY_CATEGORY_FVF["books"]
        if any(k in name for k in ["guitar", "instrument", "fender", "gibson", "drum", "keyboard", "piano", "amplifier"]):
            return EBAY_CATEGORY_FVF["musical_instruments"]
        if any(k in name for k in ["game", "console", "nintendo", "playstation", "xbox"]):
            return EBAY_CATEGORY_FVF["video_games"]
        if any(k in name for k in ["trading card", "pokemon", "sports card", "mtg"]):
            return EBAY_CATEGORY_FVF["trading_cards"]
        if any(k in name for k in ["phone", "laptop", "camera", "electronic", "tablet", "computer", "headphone"]):
            return EBAY_CATEGORY_FVF["electronics"]
    except Exception as e:
        print(f"eBay category FVF error: {e}")
    return EBAY_CATEGORY_FVF["default"]

# ── eBay Browse API: active listings ─────────────────────────────────────
def _ebay_active_listings(query: str, condition: str = "all", limit: int = 50) -> list[dict]:
    token = _get_ebay_token()
    if not token:
        return []
    filters = ["buyingOptions:{FIXED_PRICE|AUCTION}", "soldItemOnly:false"]
    if condition != "all" and condition in EBAY_COND:
        filters.append(f"conditionIds:{{{EBAY_COND[condition]['id']}}}")
    url = f"{EBAY_API_BASE}/buy/browse/v1/item_summary/search"
    params = {
        "q": query,
        "filter": ",".join(filters),
        "limit": str(min(limit, 50)),
        "sort": "price asc",
    }
    try:
        r = SESSION.get(url, params=params, headers={"Authorization": f"Bearer {token}"}, timeout=20)
        if r.status_code != 200:
            print(f"eBay active API error: {r.status_code} {r.text[:200]}")
            return []
        items = r.json().get("itemSummaries", [])
        results = []
        for it in items:
            price = float(it.get("price", {}).get("value", 0))
            if price <= 0:
                continue
            cond = _ebay_condition_to_canonical(it.get("condition", ""))
            shipping = 0.0
            ship_opts = it.get("shippingOptions", [])
            if ship_opts and ship_opts[0].get("shippingCost", {}).get("value"):
                shipping = float(ship_opts[0]["shippingCost"]["value"])
            results.append({
                "title": it.get("title", ""),
                "price": price,
                "shipping": shipping,
                "condition": cond,
                "url": it.get("itemWebUrl", ""),
                "is_auction": "AUCTION" in it.get("buyingOptions", []),
            })
        return results
    except Exception as e:
        print(f"eBay active listings error: {e}")
    return []

def _ebay_condition_to_canonical(raw: str) -> str:
    raw = (raw or "").lower()
    for k, v in EBAY_COND.items():
        if raw in (v["ebay"].lower(), v["label"].lower(), k):
            return k
    for alias, canonical in CONDITION_ALIASES.items():
        if alias in raw:
            return canonical
    return "used"


def _extract_item_id_from_url(url: str) -> str | None:
    if not url:
        return None
    m = re.search(r'/itm/(?:[^/]+/)?(\d+)', url)
    if m:
        return m.group(1)
    m = re.search(r'item=(\d+)', url)
    if m:
        return m.group(1)
    return None


def _safe_ymd(raw: str) -> str | None:
    raw = (raw or '').strip()
    if not raw:
        return None
    if re.match(r'^\d{4}-\d{2}-\d{2}$', raw):
        return raw
    if len(raw) >= 10 and re.match(r'^\d{4}-\d{2}-\d{2}', raw[:10]):
        return raw[:10]
    return None


def _build_sold_verification_url(query: str, title: str = '', item_id: str | None = None) -> str:
    search_term = item_id or title or query or ''
    return (
        'https://www.ebay.com/sch/i.html?_nkw=' + urllib.parse.quote_plus(search_term) +
        '&LH_Sold=1&LH_Complete=1'
    )


def _sold_debug_key(query: str, condition: str) -> str:
    return f"{(query or '').strip().lower()}|{(condition or 'all').strip().lower()}"


def _derive_sold_source_status(debug: dict, raw_items: list[dict], relevant_items: list[dict], valid_items: list[dict]) -> str:
    if valid_items:
        return 'available'
    if not debug:
        return 'unknown'
    if debug.get('http_status') and debug.get('http_status') != 200:
        return 'http_error'
    if debug.get('blocked_signals'):
        return 'blocked_or_error_page'
    if debug.get('has_no_results_text'):
        return 'no_results'
    if raw_items and not relevant_items:
        return 'filtered_out'
    if relevant_items and not valid_items:
        return 'excluded'
    if debug.get('item_node_count', 0) == 0:
        return 'selector_mismatch_or_empty_markup'
    if debug.get('extracted_items', 0) == 0:
        return 'parsed_zero_items'
    return 'unavailable'


def _sold_source_status_note(status: str, debug: dict) -> str:
    if status == 'blocked_or_error_page':
        return 'Verified sold listings are unavailable because eBay returned an error or anti-bot style page to the server.'
    if status == 'http_error':
        return f"Verified sold listings are unavailable because eBay returned HTTP {debug.get('http_status')}."
    if status == 'selector_mismatch_or_empty_markup':
        return 'Verified sold listings are unavailable because the sold-search page did not contain parseable listing markup.'
    if status == 'parsed_zero_items':
        return 'Verified sold listings are unavailable because the sold-search page loaded but no sold cards could be extracted.'
    if status == 'filtered_out':
        return 'eBay sold-search results were found, but none matched this product cleanly after relevance filtering.'
    if status == 'excluded':
        return 'Sold-search results were found from eBay, but all were excluded from pricing due to missing/future dates, active overlap, or product mismatch.'
    if status == 'no_results':
        return 'Verified sold listings are unavailable because eBay sold search returned no results.'
    return 'Verified sold listings are unavailable right now. Use the eBay sold search link below to verify manually.'


def _sold_source_merge_priority(item: dict) -> tuple:
    source = item.get('source', '')
    source_rank = {
        'eBay Sold Search': 4,
        'eBay Finding API': 3,
        'eBay Browse API': 2,
        'PriceCharting': 1,
    }.get(source, 0)
    has_date = 1 if _safe_ymd(item.get('sold_date', '')) else 0
    return (has_date, source_rank)


def _sold_identity_key(item: dict) -> str:
    item_id = item.get('item_id') or _extract_item_id_from_url(item.get('url', ''))
    if item_id:
        return f"item:{item_id}"
    url = (item.get('url') or '').split('#')[0]
    if url:
        return f"url:{url}"
    return f"title:{(item.get('title') or '').strip().lower()}|price:{item.get('price')}|date:{_safe_ymd(item.get('sold_date', '')) or ''}"


def _merge_sold_candidates(items: list[dict]) -> list[dict]:
    best_by_key = {}
    for item in items or []:
        key = _sold_identity_key(item)
        existing = best_by_key.get(key)
        if existing is None or _sold_source_merge_priority(item) > _sold_source_merge_priority(existing):
            best_by_key[key] = item
    merged = list(best_by_key.values())
    merged.sort(key=lambda it: ((it.get('sold_date') or ''), _sold_source_merge_priority(it)), reverse=True)
    return merged


def _sold_source_breakdown(items: list[dict]) -> dict:
    counts = defaultdict(int)
    for it in items or []:
        counts[it.get('source', 'unknown')] += 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def _summarize_excluded_reasons(items: list[dict]) -> dict:
    counts = defaultdict(int)
    for it in items or []:
        for reason in it.get('reject_reasons', []) or []:
            counts[reason] += 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def _validate_sold_item_basic(item: dict, query: str, active_ids: set[str], today_ymd: str) -> dict:
    comp = dict(item or {})
    sold_date = _safe_ymd(comp.get('sold_date', ''))
    item_id = comp.get('item_id') or _extract_item_id_from_url(comp.get('url', ''))
    source = comp.get('source', '')
    source_conf = 'low'
    if source == 'eBay Sold Search':
        source_conf = 'high'
    elif source == 'eBay Finding API':
        source_conf = 'medium'
    elif source == 'PriceCharting':
        source_conf = 'low'

    reject_reasons = []
    warning_reasons = []
    active_overlap = bool(item_id and item_id in active_ids)

    if not sold_date:
        reject_reasons.append('missing_sold_date')
    elif sold_date > today_ymd:
        reject_reasons.append('future_sold_date')

    if active_overlap:
        reject_reasons.append('active_overlap')

    reject_reasons.extend(_category_specific_mismatch_reasons(query, comp.get('title', '')))

    if source == 'eBay Sold Search':
        source_conf = 'high'
    elif source == 'eBay Finding API':
        source_conf = 'medium'
        warning_reasons.append('finding_view_item_url')
    elif source == 'eBay Browse API':
        source_conf = 'low'
        warning_reasons.append('browse_view_item_url')
    elif source == 'PriceCharting':
        source_conf = 'low'
        warning_reasons.append('non_ebay_source')

    if comp.get('is_multi_variation'):
        warning_reasons.append('multi_variation_listing')

    comp['item_id'] = item_id
    comp['sold_date'] = sold_date or ''
    comp['sold_date_raw'] = comp.get('sold_date_raw') or item.get('sold_date') or ''
    comp['sold_date_valid'] = bool(sold_date and sold_date <= today_ymd)
    comp['active_overlap'] = active_overlap
    comp['source_confidence'] = source_conf
    comp['verification_url'] = _build_sold_verification_url(query, comp.get('title', ''), item_id)
    comp['url_type'] = 'view_item' if comp.get('url') else 'none'
    comp['reject_reasons'] = reject_reasons
    comp['warning_reasons'] = warning_reasons
    comp['comp_valid'] = len(reject_reasons) == 0
    return comp

# ── eBay Sold Data (Finding API) ───────────────────────────────────────
def _fetch_ebay_sold_browse(query: str, condition: str = "all", limit: int = 100) -> list[dict]:
    token = _get_ebay_token()
    if not token:
        return []
    try:
        filters = ["soldItemOnly:true"]
        if condition != "all" and condition in EBAY_COND:
            filters.append(f"conditionIds:{{{EBAY_COND[condition]['id']}}}")
        url = f"{EBAY_API_BASE}/buy/browse/v1/item_summary/search"
        params = {
            "q": query,
            "filter": ",".join(filters),
            "limit": str(min(limit, 50)),
            "sort": "newlyListed",
        }
        r = SESSION.get(url, params=params, headers={"Authorization": f"Bearer {token}"}, timeout=20)
        if r.status_code != 200:
            return []
        items = r.json().get("itemSummaries", [])
        res = []
        for it in items:
            try:
                price = float(it.get("price", {}).get("value", 0))
                if price <= 0:
                    continue
                url = it.get("itemWebUrl", "")
                res.append({
                    "title": it.get("title", ""),
                    "price": price,
                    "sold_date": _safe_ymd(it.get("itemEndDate", "")) or "",
                    "condition": _ebay_condition_to_canonical(it.get("condition", "")),
                    "url": url,
                    "item_id": _extract_item_id_from_url(url),
                    "source": "eBay Browse API",
                })
            except Exception:
                continue
        return res
    except Exception:
        return []


def _fetch_ebay_sold_finding(query: str, condition: str = "all", limit: int = 100) -> list[dict]:
    if not EBAY_CLIENT_ID:
        return []
    try:
        params = {
            "OPERATION-NAME": "findCompletedItems",
            "SERVICE-VERSION": "1.13.0",
            "SECURITY-APPNAME": EBAY_CLIENT_ID,
            "RESPONSE-DATA-FORMAT": "JSON",
            "REST-PAYLOAD": "true",
            "GLOBAL-ID": "EBAY-US",
            "keywords": query,
            "paginationInput.entriesPerPage": str(min(limit, 100)),
            "sortOrder": "EndTimeSoonest",
            "itemFilter(0).name": "SoldItemsOnly",
            "itemFilter(0).value": "true",
        }
        if condition != "all" and condition in EBAY_COND:
            params["itemFilter(1).name"] = "Condition"
            params["itemFilter(1).value"] = EBAY_COND[condition]["id"]
        r = SESSION.get(EBAY_FINDING_API, params=params, timeout=20)
        if r.status_code != 200:
            return []
        data = r.json()
        response = data.get("findCompletedItemsResponse", [{}])[0]
        if response.get("ack", [""])[0] != "Success":
            return []
        search_res = response.get("searchResult", [{}])
        items = search_res[0].get("item", []) if search_res and search_res[0] else []
        res = []
        for it in items:
            try:
                price = float(it.get("sellingStatus", [{}])[0].get("currentPrice", [{}])[0].get("__value__", 0))
                if price <= 0:
                    continue
                url = it.get("viewItemURL", [""])[0]
                res.append({
                    "title": it.get("title", [""])[0],
                    "price": price,
                    "sold_date": _safe_ymd(it.get("listingInfo", [{}])[0].get("endTime", "")) or "",
                    "condition": _ebay_condition_to_canonical(it.get("condition", [{}])[0].get("conditionDisplayName", "") if it.get("condition") else ""),
                    "url": url,
                    "item_id": _extract_item_id_from_url(url),
                    "listing_type": it.get("listingInfo", [{}])[0].get("listingType", "") if it.get("listingInfo") else "",
                    "selling_state": it.get("sellingStatus", [{}])[0].get("sellingState", "") if it.get("sellingStatus") else "",
                    "is_multi_variation": bool(it.get("isMultiVariationListing", [False])[0]) if isinstance(it.get("isMultiVariationListing"), list) else bool(it.get("isMultiVariationListing", False)),
                    "source": "eBay Finding API",
                })
            except Exception:
                continue
        return res
    except Exception:
        return []


def _ebay_sold_listings(query: str, condition: str = "all", limit: int = 100) -> list[dict]:
    """Return only verified eBay sold-search results for user-facing sold comps.

    We intentionally do NOT use Browse soldItemOnly or Finding completed results as
    user-facing sold truth because those sources can still point at buyer-facing
    View Item pages, multi-quantity/multi-variation listings, or records with weak
    end-date semantics. For correctness, the app now treats the eBay sold/completed
    search surface as the verified sold-listing source.
    """
    return _scrape_ebay_sold_fallback(query, condition, min(limit, 60))


def _scrape_ebay_sold_fallback(query: str, condition: str = "all", limit: int = 60) -> list[dict]:
    """Scrape the eBay sold/completed search page as the verified sold-listing source."""
    u = f"https://www.ebay.com/sch/i.html?_nkw={urllib.parse.quote_plus(query)}&LH_Sold=1&LH_Complete=1&_ipg=60"
    if condition and condition != "all" and condition in EBAY_COND:
        u += f"&LH_ItemCondition={EBAY_COND[condition]['id']}"

    debug = {
        "query": query,
        "condition": condition,
        "request_url": u,
        "final_url": u,
        "http_status": None,
        "page_title": "",
        "response_length": 0,
        "item_node_count": 0,
        "pl_bottom_node_count": 0,
        "title_node_count": 0,
        "price_node_count": 0,
        "link_node_count": 0,
        "extracted_items": 0,
        "skipped_missing_core": 0,
        "skipped_duplicates": 0,
        "skipped_shop_or_sponsored": 0,
        "skipped_bad_price": 0,
        "has_no_results_text": False,
        "blocked_signals": [],
        "parse_notes": [],
    }

    try:
        r = SESSION.get(u, timeout=15)
        debug["http_status"] = r.status_code
        debug["final_url"] = r.url
        debug["response_length"] = len(r.text or "")
        if r.status_code != 200:
            debug["blocked_signals"].append("non_200_status")
            SOLD_SOURCE_DEBUG[_sold_debug_key(query, condition)] = debug
            print(f"eBay sold search scrape error: {r.status_code}")
            return []
    except Exception as e:
        debug["blocked_signals"].append("request_exception")
        debug["parse_notes"].append(str(e)[:200])
        SOLD_SOURCE_DEBUG[_sold_debug_key(query, condition)] = debug
        print(f"eBay sold search scrape request failed: {e}")
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    title_tag = soup.select_one('title')
    debug["page_title"] = title_tag.get_text(" ", strip=True)[:200] if title_tag else ""
    debug["item_node_count"] = len(soup.select("li.s-item"))
    debug["pl_bottom_node_count"] = len(soup.select("li.s-item.s-item__pl-on-bottom"))
    debug["title_node_count"] = len(soup.select(".s-item__title"))
    debug["price_node_count"] = len(soup.select(".s-item__price"))
    debug["link_node_count"] = len(soup.select("a.s-item__link"))

    text_blob_all = soup.get_text(" ", strip=True)[:5000]
    lower_blob = text_blob_all.lower()
    if "something went wrong on our end" in lower_blob or debug["page_title"].lower().startswith("error page"):
        debug["blocked_signals"].append("ebay_error_page")
    if "captcha" in lower_blob or "robot" in lower_blob or "verify yourself" in lower_blob or "security measure" in lower_blob:
        debug["blocked_signals"].append("anti_bot_or_captcha")
    if "no exact matches found" in lower_blob or "0 results for" in lower_blob:
        debug["has_no_results_text"] = True

    items = []
    seen = set()
    for li in soup.select("li.s-item"):
        try:
            title_el = li.select_one(".s-item__title")
            price_el = li.select_one(".s-item__price")
            link_el = li.select_one("a.s-item__link")
            title = title_el.get_text(" ", strip=True) if title_el else ""
            price_text = price_el.get_text(" ", strip=True) if price_el else ""
            url = link_el.get("href", "") if link_el else ""
            item_id = _extract_item_id_from_url(url)
            key = item_id or (title + '|' + price_text)
            if not title or not price_text:
                debug["skipped_missing_core"] += 1
                continue
            if key in seen:
                debug["skipped_duplicates"] += 1
                continue
            if "shop on ebay" in title.lower() or "sponsored" in title.lower():
                debug["skipped_shop_or_sponsored"] += 1
                continue
            price = _clean_price(price_text)
            if not price or price <= 0.01:
                debug["skipped_bad_price"] += 1
                continue

            sold_date = None
            text_blob = li.get_text(" ", strip=True)
            m = re.search(r'(?:Sold|Ended)\s+(\w{3}\s+\d{1,2},\s+\d{4})', text_blob, re.IGNORECASE)
            if not m:
                m = re.search(r'(\w{3}\s+\d{1,2},\s+\d{4})', text_blob)
            if m:
                try:
                    sold_date = datetime.strptime(m.group(1), "%b %d, %Y").strftime("%Y-%m-%d")
                except ValueError:
                    sold_date = None

            cond = _ebay_condition_to_canonical(title)
            items.append({
                "title": title,
                "price": price,
                "sold_date": sold_date or "",
                "condition": cond,
                "url": url,
                "item_id": item_id,
                "source": "eBay Sold Search",
            })
            seen.add(key)
            if len(items) >= limit:
                break
        except Exception:
            continue

    debug["extracted_items"] = len(items)
    if debug["item_node_count"] == 0 and not debug["has_no_results_text"] and not debug["blocked_signals"]:
        debug["parse_notes"].append("selector_mismatch_or_empty_markup")
    if debug["item_node_count"] > 0 and len(items) == 0 and not debug["blocked_signals"]:
        debug["parse_notes"].append("selector_matched_nodes_but_no_items_extracted")
    SOLD_SOURCE_DEBUG[_sold_debug_key(query, condition)] = debug
    print(f"eBay sold search scrape returned {len(items)} items for '{query}'")
    return items

# ── PriceCharting (games only, optional) ─────────────────────────────────
GAMING_KEYWORDS = [
    "nintendo", "switch", "playstation", "ps5", "ps4", "ps3", "xbox", "pokemon",
    "mario", "zelda", "gameboy", "wii", "sega", "atari", "gamecube", "ds", "3ds",
    "amiibo", "skylanders", "nes", "snes", "n64", "dreamcast", "genesis", "turbografx",
]

def _is_gaming_query(query: str) -> bool:
    q = query.lower()
    return any(kw in q for kw in GAMING_KEYWORDS)

def _search_pricecharting(query: str) -> list[dict]:
    if not ENABLE_PRICECHARTING:
        return []
    try:
        r = SESSION.get(
            f"https://www.pricecharting.com/search-products?q={urllib.parse.quote_plus(query)}",
            timeout=15,
        )
        if r.status_code != 200:
            return []
    except Exception:
        return []
    soup = BeautifulSoup(r.text, "html.parser")
    products = []
    for offer in soup.select(".offer"):
        name_el = offer.select_one(".product_name")
        if not name_el:
            continue
        name = name_el.get_text(strip=True)
        offers_url = ""
        for a in offer.select("a[href]"):
            href = a.get("href", "")
            if "/offers?product=" in href:
                offers_url = "https://www.pricecharting.com" + href
                break
        if offers_url:
            products.append({"title": name, "url": offers_url, "relevance": _relevance_score(query, name)})
    products.sort(key=lambda p: p["relevance"], reverse=True)
    return products[:5]

def _scrape_pricecharting_detail(offers_url: str) -> dict | None:
    if not ENABLE_PRICECHARTING:
        return None
    try:
        r = SESSION.get(offers_url, timeout=15)
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, "html.parser")
        historic_url = ""
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            if ("/game/" in href or "/product/" in href) and "offers" not in href:
                historic_url = "https://www.pricecharting.com" + href
                break
        if not historic_url:
            return None
        r2 = SESSION.get(historic_url, timeout=15)
        if r2.status_code != 200:
            return None
        soup2 = BeautifulSoup(r2.text, "html.parser")
        sold_listings = []
        for table in soup2.select("table"):
            headers = [th.get_text(strip=True).lower() for th in table.select("th")]
            has_date = any("sale date" in h or "date" in h for h in headers)
            has_price = any("price" in h for h in headers)
            if not (has_date and has_price):
                continue
            prev = table.find_previous(["h2", "h3", "div"])
            current_condition = "good"
            if prev:
                norm = _normalize_condition_text(prev.get_text(strip=True))
                if norm:
                    current_condition = norm
            price_idx = None
            date_idx = None
            for i, h in enumerate(headers):
                if "price" in h and i >= 2:
                    price_idx = i
                elif "sale date" in h or ("date" in h and i == 0):
                    date_idx = i
            if price_idx is None:
                continue
            for tr in table.select("tr"):
                cells = tr.select("td")
                if len(cells) <= price_idx:
                    continue
                date_cell = cells[date_idx].get_text(strip=True) if date_idx is not None and date_idx < len(cells) else ""
                if not re.match(r"\d{4}-\d{2}-\d{2}", date_cell):
                    continue
                price = _clean_price(cells[price_idx].get_text(strip=True))
                if not price:
                    continue
                title = cells[1].get_text(strip=True)[:200] if len(cells) > 1 else ""
                title = re.sub(r"Time Warp.*?OK\s*", "", title).strip()
                item_cond = _normalize_condition_text(title) or current_condition
                sold_listings.append({
                    "title": title, "price": price,
                    "sold_date": date_cell, "url": "",
                    "condition": item_cond,
                })
        return {"sold_listings": sold_listings, "source": "PriceCharting", "source_url": historic_url}
    except Exception:
        return None

def _normalize_condition_text(raw: str) -> str:
    if not raw:
        return ""
    rl = raw.strip().lower()
    for alias, canonical in CONDITION_ALIASES.items():
        if alias in rl:
            return canonical
    return ""

def _tokenize(s: str) -> set[str]:
    noise = {"the", "a", "an", "of", "in", "on", "at", "to", "for", "with",
             "and", "or", "is", "are", "was", "were", "be", "been", "being",
             "it", "its", "this", "that", "these", "those", "edition", "version"}
    tokens = re.findall(r'[a-z0-9]+', s.lower())
    return {_singularize(t) for t in tokens if t not in noise and len(t) > 1}

def _singularize(token: str) -> str:
    """Tiny normalizer so bottle/bottles and box/boxes compare the same."""
    token = (token or "").lower()
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 4 and token.endswith(("ches", "shes", "xes", "sses", "zes")):
        return token[:-2]
    if len(token) > 3 and token.endswith("s"):
        return token[:-1]
    return token

def _compact(s: str) -> str:
    return re.sub(r'[^a-z0-9]+', '', (s or '').lower())

def _query_tokens_for_relevance(query: str) -> list[str]:
    """Tokens that should be present in matching eBay titles.

    eBay keyword search is intentionally broad; it may return adjacent products
    that match only one word in the query.  We keep meaningful user terms and
    drop listing filler words so stats are built from the product actually
    searched for.
    """
    weak = {
        "new", "used", "open", "box", "lot", "bundle", "set", "pack", "pair",
        "sale", "sold", "listing", "item", "free", "shipping", "authentic",
        "genuine", "original", "official", "read", "please", "condition",
    }
    raw = re.findall(r'[a-z0-9]+', (query or '').lower())
    return [_singularize(t) for t in raw if len(t) > 1 and t not in weak]

def _title_contains_token(title_tokens: set[str], compact_title: str, token: str) -> bool:
    # Exact token match catches normal titles; compact substring catches brands
    # written together, e.g. "BlenderBottle" for query "Blender Bottle".
    return token in title_tokens or token in compact_title

def _relevance_score(query: str, product_title: str) -> float:
    q_tokens = _query_tokens_for_relevance(query)
    p_tokens = _tokenize(product_title)
    if not q_tokens:
        return 1.0

    compact_query = _compact(query)
    compact_title = _compact(product_title)
    matched = [t for t in q_tokens if _title_contains_token(p_tokens, compact_title, t)]
    recall = len(matched) / len(q_tokens)

    # Strong bonus for exact phrase or joined brand spelling.
    phrase_bonus = 0.0
    if compact_query and compact_query in compact_title:
        phrase_bonus = 0.35

    # Mild penalty for very noisy titles, but don't over-penalize legitimate
    # detailed listings.
    length_penalty = min(1.0, 12 / max(len(p_tokens), 1))
    score = recall * 0.75 + length_penalty * 0.10 + phrase_bonus
    return max(0.0, min(1.0, score))

KNOWN_STRICT_PHRASE_PRODUCTS = {
    # Brand/product phrases where the individual words are too generic on eBay.
    # "Blender Bottle" is a shaker bottle brand/product; generic USB blenders
    # and unrelated water bottles should not count as comparable listings.
    "blenderbottle",
}

def _strict_phrase_match(query: str, title: str) -> bool:
    """True when the searched words appear as one product/brand phrase.

    This catches both "Blender Bottle" and "BlenderBottle" while rejecting
    titles where the words are separated as unrelated descriptors, e.g.
    "USB Juicer Blender ... Mixer Bottle".
    """
    q_tokens = _query_tokens_for_relevance(query)
    if len(q_tokens) < 2:
        return False
    compact_query = "".join(q_tokens)
    return bool(compact_query and compact_query in _compact(title))

def _requires_strict_phrase(query: str) -> bool:
    q_tokens = _query_tokens_for_relevance(query)
    return "".join(q_tokens) in KNOWN_STRICT_PHRASE_PRODUCTS

def _query_is_for_accessory(query: str) -> bool:
    q = (query or "").lower()
    accessory_words = {
        "replacement", "replace", "gasket", "seal", "o-ring", "oring",
        "lid", "cap", "straw", "part", "parts", "accessory", "accessories",
        "blade", "blades", "charger", "cable", "case", "cover", "strap",
    }
    return any(w in q for w in accessory_words)

def _is_accessory_or_part_listing(title: str, query: str) -> bool:
    """Exclude replacement parts/accessories unless the user searched for one."""
    if _query_is_for_accessory(query):
        return False

    tl = (title or "").lower()
    tokens = _tokenize(tl)

    # Strong accessory/parts indicators.
    if any(term in tl for term in [
        "replacement", "replace ", "for parts", "parts only", "not working",
        "gasket", "o-ring", "oring", "rubber seal", "sealing ring",
        "accessory", "accessories",
    ]):
        return True

    # Lid/cap/straw/blade listings are usually accessories when paired with
    # words like only/pack/pcs, but a full product title may legitimately say
    # "with lid", so keep this conservative.
    accessory_tokens = {"lid", "cap", "straw", "seal", "washer", "gasket"}
    quantity_or_only_tokens = {"only", "pack", "pc", "pcs", "piece", "pieces", "set", "kit"}
    if tokens & accessory_tokens and tokens & quantity_or_only_tokens:
        return True

    return False


def _extract_requested_storage_gb(query: str) -> str:
    m = re.search(r'(16|32|64|128|256|512|1024)\s*gb', (query or '').lower())
    return m.group(1) if m else ''


def _iphone_variant_key(text: str) -> str:
    t = (text or '').lower()
    if 'pro max' in t:
        return 'pro max'
    if re.search(r'pro', t):
        return 'pro'
    if re.search(r'plus', t):
        return 'plus'
    if re.search(r'mini', t):
        return 'mini'
    return 'base'


def _category_specific_mismatch_reasons(query: str, title: str) -> list[str]:
    ql = (query or '').lower()
    tl = (title or '').lower()
    reasons = []
    category = _detect_ebay_category(query)

    if category == 'electronics' and 'iphone' in ql and 'iphone' in tl:
        q_model = re.search(r'iphone\s+(\d{1,2})', ql)
        t_model = re.search(r'iphone\s+(\d{1,2})', tl)
        if q_model and t_model and q_model.group(1) != t_model.group(1):
            reasons.append('wrong_phone_generation')
        if _iphone_variant_key(ql) != _iphone_variant_key(tl):
            reasons.append('wrong_phone_variant')
        q_storage = _extract_requested_storage_gb(ql)
        title_storages = set(re.findall(r'(16|32|64|128|256|512|1024)\s*gb', tl))
        if q_storage and title_storages and q_storage not in title_storages:
            reasons.append('wrong_storage')
        if 'unlocked' in ql and 'locked' in tl and 'unlocked' not in tl:
            reasons.append('locked_phone')

    if category == 'video_games':
        accessory_terms = [
            'dock', 'docking station', 'joy-con', 'joycon', 'controller', 'charger dock',
            'travel case', 'carrying case', 'case', 'shell', 'housing', 'thumb grip',
            'thumb grips', 'sticker', 'button caps', 'buttons', 'strap', 'nitro deck',
            'organizer', 'stand', 'wall mount'
        ]
        if any(term in tl for term in accessory_terms):
            reasons.append('console_accessory')
        if any(term in tl for term in ['bundle', 'lot', 'and extras', 'with extras', '4 games', 'games included']):
            if 'bundle' not in ql and 'lot' not in ql:
                reasons.append('console_bundle')
        if any(term in tl for term in ['console only', 'tablet only']):
            if 'console only' not in ql and 'tablet only' not in ql:
                reasons.append('console_only_variant')

    if category == 'tools':
        if any(term in tl for term in ['chuck', 'switch label', 'tool case', 'case only', 'housing', 'gear shifter', 'gear selector']):
            reasons.append('tool_part_or_case')

    if category == 'trading_cards':
        if any(term in tl for term in ['psa', 'bgs', 'cgc', 'sgc', 'graded', 'ace graded']):
            if not any(term in ql for term in ['psa', 'bgs', 'cgc', 'sgc', 'graded']):
                reasons.append('graded_card')
        if 'base set' in ql and 'base set 2' in tl:
            reasons.append('wrong_card_set')
        if 'japanese' in tl and 'japanese' not in ql:
            reasons.append('wrong_card_language')
        if any(term in tl for term in ['celebrations', 'expedition', 'legendary collection']):
            reasons.append('wrong_card_series')
        if any(term in tl for term in ['lot', 'binder', 'collection', 'trio', 'complete set']):
            if not any(term in ql for term in ['lot', 'binder', 'collection', 'set']):
                reasons.append('card_lot_or_collection')

    if category == 'books':
        if any(term in ql for term in ['hardcover', 'hardback']) and 'paperback' in tl:
            reasons.append('wrong_book_format')
        if any(term in tl for term in ['casebook', 'study guide', 'student', 'cooking', 'entertaining guide', 'understanding the ']):
            reasons.append('book_companion_or_guide')
        if any(term in tl for term in ['set of', 'book set']) and 'set' not in ql:
            reasons.append('book_set')

    if category == 'sneakers':
        if re.search(r'(gs|grade school|youth|toddler|preschool|infant|baby)', tl):
            if not re.search(r'(gs|grade school|youth|toddler|preschool|infant|baby)', ql):
                reasons.append('youth_shoe_variant')

    # de-duplicate while preserving order
    seen = set()
    deduped = []
    for reason in reasons:
        if reason not in seen:
            deduped.append(reason)
            seen.add(reason)
    return deduped


def _is_relevant_listing(query: str, title: str) -> bool:
    """Return True only when a listing title appears to match the searched item.

    For multi-word searches we require every important query term to appear,
    allowing joined brand spellings ("blenderbottle" contains both "blender"
    and "bottle"). Accessory/replacement-part listings are excluded unless the
    search itself asks for an accessory.
    """
    if _is_accessory_or_part_listing(title, query):
        return False
    if _category_specific_mismatch_reasons(query, title):
        return False
    if _requires_strict_phrase(query) and not _strict_phrase_match(query, title):
        return False

    q_tokens = _query_tokens_for_relevance(query)
    if not q_tokens:
        return True

    title_tokens = _tokenize(title)
    compact_title = _compact(title)
    matches = sum(1 for t in q_tokens if _title_contains_token(title_tokens, compact_title, t))

    if len(q_tokens) <= 2:
        return matches == len(q_tokens)

    # Longer searches can include descriptors/model words not present in every
    # title, but the majority should still match.
    return matches >= max(2, int(len(q_tokens) * 0.75 + 0.999))

def _is_barcode_query(query: str) -> bool:
    clean = query.strip().replace("-", "").replace(" ", "")
    return clean.isdigit() and len(clean) >= 8

def _extract_product_name_from_titles(items: list[dict], query: str) -> str:
    if not items:
        return query
    titles = [it.get("title", "") for it in items if it.get("title")]
    if not titles:
        return query
    clean_titles = sorted(titles, key=len)
    best = clean_titles[0]
    for junk in ["BRAND NEW", "NEW", "Free Shipping", "Used", "Boxed", "Complete", "Mint", "TESTED", "In Hand", "Sealed"]:
        best = re.sub(f"(?i)\\b{junk}\\b", "", best).strip()
    return best.strip(" -,/|") or titles[0]

def _filter_by_relevance(items: list[dict], query: str) -> list[dict]:
    """Filter eBay/market listings down to titles relevant to the query."""
    if _is_barcode_query(query):
        filtered = []
        for it in items or []:
            title = it.get("title", "")
            if not _is_accessory_or_part_listing(title, "barcode"):
                it["relevance"] = 1.0
                filtered.append(it)
        return filtered

    filtered = []
    for it in items or []:
        title = it.get("title", "")
        if _is_relevant_listing(query, title):
            it["relevance"] = round(_relevance_score(query, title), 3)
            filtered.append(it)

    q_tokens = _query_tokens_for_relevance(query)
    if len(q_tokens) >= 2:
        phrase_matches = [it for it in filtered if _strict_phrase_match(query, it.get("title", ""))]
        if len(phrase_matches) >= 3 or (filtered and len(phrase_matches) / len(filtered) >= 0.35):
            filtered = phrase_matches

    return filtered

# ── Utilities ────────────────────────────────────────────────────────────
def _clean_price(txt):
    if not txt:
        return None
    t = str(txt).replace("$", "").replace(",", "").strip()
    if not t:
        return None
    try:
        val = float(t)
    except (ValueError, TypeError):
        return None
    if val <= 0.01 or val >= 500000:
        return None
    return val

def _compute_stats(items: list[dict]) -> dict:
    prices = [it["price"] for it in items if it.get("price") and it["price"] > 0.01]
    if not prices:
        return {"low": 0, "p10": 0, "median": 0, "p90": 0, "high": 0, "mean": 0, "count": 0}
    prices.sort()
    n = len(prices)
    median = prices[n // 2] if n % 2 else (prices[n // 2 - 1] + prices[n // 2]) / 2
    p10_idx = max(0, int(n * 0.10) - 1)
    p90_idx = min(n - 1, int(n * 0.90))
    return {
        "low": round(min(prices), 2),
        "p10": round(prices[p10_idx], 2),
        "median": round(median, 2),
        "p90": round(prices[p90_idx], 2),
        "high": round(max(prices), 2),
        "mean": round(sum(prices) / n, 2),
        "count": n,
    }

def _stats_by_condition(items: list[dict]) -> dict:
    groups = defaultdict(list)
    for it in items:
        cond = it.get("condition", "used") or "used"
        if cond not in EBAY_COND:
            cond = "used"
        groups[cond].append(it["price"])
    result = {}
    for cond in EBAY_COND:
        prices = groups.get(cond, [])
        if not prices:
            continue
        prices.sort()
        n = len(prices)
        median = prices[n // 2] if n % 2 else (prices[n // 2 - 1] + prices[n // 2]) / 2
        result[cond] = {
            "low": round(min(prices), 2),
            "median": round(median, 2),
            "high": round(max(prices), 2),
            "mean": round(sum(prices) / n, 2),
            "count": n,
        }
    return result

def _filter_by_condition(items: list[dict], target_cond: str) -> list[dict]:
    if not target_cond or target_cond == "all":
        return items
    return [it for it in items if it.get("condition") == target_cond]

def _generate_trend(base_price: float, sold_items: list, period_days: int = 180) -> list[dict]:
    """Build a real trend from sold dates, or return empty if not enough data."""
    dated = [it for it in sold_items
             if it.get("sold_date") and re.match(r"\d{4}-\d{2}-\d{2}", str(it["sold_date"]))]
    if len(dated) < 3:
        return []
    buckets = defaultdict(list)
    for it in dated:
        try:
            d = datetime.strptime(it["sold_date"], "%Y-%m-%d")
            week = (d - timedelta(days=d.weekday())).strftime("%Y-%m-%d")
            buckets[week].append(it["price"])
        except Exception:
            continue
    cutoff = datetime.now() - timedelta(days=period_days)
    trend = []
    for week in sorted(buckets.keys()):
        try:
            wd = datetime.strptime(week, "%Y-%m-%d")
        except ValueError:
            continue
        if wd < cutoff:
            continue
        prices = [p for p in buckets[week] if p > 0.01]
        if not prices:
            continue
        prices.sort()
        n = len(prices)
        trend.append({
            "date": week,
            "low": round(min(prices), 2),
            "median": round(prices[n // 2], 2),
            "high": round(max(prices), 2),
            "mean": round(sum(prices) / n, 2),
            "count": n,
        })
    if len(trend) > 60:
        step = len(trend) // 60
        trend = trend[::step]
        if trend[-1] != trend[-1]:
            trend.append(trend[-1])
    return trend

# ── Flip Analysis ────────────────────────────────────────────────────────
def _analyze_flip(sold_stats, active_stats, sold_items, active_items, trend,
                  condition_stats, buy_price=0.0, category="default",
                  store_tier="none", shipping_cost=0.0, promoted_rate=0.0):
    sm = sold_stats.get("median", 0) or 0
    am = active_stats.get("median", 0) or 0
    sc = sold_stats.get("count", 0) or 0
    ac = active_stats.get("count", 0) or 0
    sold_low = sold_stats.get("low", 0) or 0

    if sc == 0:
        return {
            "score": 0, "verdict": "❓ No Sold Data", "verdict_detail": "No eBay sold listings found. Can't estimate flip value.",
            "sell_through_rate": 0, "liquidity": {"label": "Unknown", "description": "No sales data."},
            "potential_buy_price": round(buy_price or 0, 2), "potential_sell_price": 0,
            "potential_profit": 0, "potential_profit_pct": 0,
            "velocity_per_day": 0, "velocity_label": "Unknown",
            "market_explanation": "No real eBay sold data. Use the verification links to research manually.",
            "user_buy_price_used": buy_price > 0,
            "fee_calculation": _calculate_net_profit(0, buy_price or 0, shipping_cost, category, store_tier, promoted_rate),
            "saturation": {"tier": "unknown", "label": "Unknown", "description": "No sold data.", "active_sold_ratio": 0, "active_count": ac, "sold_count": 0},
            "opportunity": {"score": 0, "verdict": "No Sold Data", "description": "No eBay sold listings found.", "saturation": {}, "alerts": []},
        }

    total_listings = sc + ac
    str_rate = (sc / total_listings * 100) if total_listings > 0 else 0

    potential_buy = buy_price if buy_price > 0 else (sold_low if sold_low > 0 else sm * 0.7)
    potential_sell = sm
    margin_dollar = potential_sell - potential_buy
    margin_pct = (margin_dollar / potential_buy * 100) if potential_buy > 0 else 0

    # Velocity from real sold dates
    velocity = 0
    if sold_items:
        dated = [it for it in sold_items if re.match(r"\d{4}-\d{2}-\d{2}", str(it.get("sold_date", "")))]
        if len(dated) >= 2:
            dates = sorted([datetime.strptime(it["sold_date"], "%Y-%m-%d") for it in dated])
            span = max((dates[-1] - dates[0]).days, 1)
            velocity = len(dates) / span
        else:
            velocity = sc / 180.0
    else:
        velocity = 0

    avg_days_to_sell = (1 / velocity) if velocity > 0 else None
    if str_rate > 30:
        liquidity_label, liquidity_desc = "🟢 Liquid", "Sells fast — buy confidently"
    elif str_rate > 10:
        liquidity_label, liquidity_desc = "🟡 Moderate", "Will sell with patience"
    else:
        liquidity_label, liquidity_desc = "🔴 Illiquid", "You'll sit on this for a while"

    velocity_label = "🔥 Very Fast" if velocity > 2 else "✅ Fast" if velocity > 0.5 else "📊 Moderate" if velocity > 0.1 else "🐢 Slow"

    active_sold_ratio = (ac / sc) if sc > 0 else 999
    if active_sold_ratio < 1:
        saturation_label = "🟢 Underserved"
        saturation_desc = f"Only {ac} listed vs {sc} sold. Strong opportunity."
    elif active_sold_ratio < 3:
        saturation_label = "🟡 Balanced"
        saturation_desc = "Healthy market. Price competitively."
    elif active_sold_ratio < 8:
        saturation_label = "🟠 Competitive"
        saturation_desc = f"{ac} sellers for {sc} sold. Need best price or condition."
    else:
        saturation_label = "🔴 Oversaturated"
        saturation_desc = f"{ac} listed, only {sc} sold. Skip unless patient."

    alerts = []
    if str_rate > 50 and active_sold_ratio < 2:
        alerts.append({"type": "hot", "icon": "🔥", "label": "HOT ITEM",
                       "desc": "High sell-through, low competition. Buy immediately."})
    if active_sold_ratio > 5 and sc > 0:
        alerts.append({"type": "saturated", "icon": "⚠️", "label": "SATURATED",
                       "desc": f"Supply is {active_sold_ratio:.0f}x demand."})
    if ac < 5 and velocity > 0.5:
        alerts.append({"type": "gem", "icon": "💎", "label": "HIDDEN GEM",
                       "desc": f"Only {ac} active listings with {velocity:.1f} sales/day."})

    opp_score = 50
    if active_sold_ratio < 1: opp_score += 25
    elif active_sold_ratio < 3: opp_score += 10
    elif active_sold_ratio < 8: opp_score -= 10
    else: opp_score -= 25
    if velocity > 1: opp_score += 15
    elif velocity > 0.5: opp_score += 10
    elif velocity < 0.05: opp_score -= 10
    opp_score += min(10, len(alerts) * 5)
    opp_score = max(0, min(100, round(opp_score)))

    if opp_score >= 70:
        opp_verdict, opp_desc = "🌟 Prime Opportunity", "Market conditions are ideal."
    elif opp_score >= 50:
        opp_verdict, opp_desc = "👍 Good Opportunity", "Worth pursuing with the right price."
    elif opp_score >= 30:
        opp_verdict, opp_desc = "🤔 Mixed Signals", "Be selective."
    else:
        opp_verdict, opp_desc = "👎 Poor Timing", "Too many sellers, not enough buyers."

    saturation = {
        "tier": "underserved" if active_sold_ratio < 1 else "balanced" if active_sold_ratio < 3 else "competitive" if active_sold_ratio < 8 else "oversaturated",
        "label": saturation_label, "description": saturation_desc,
        "active_sold_ratio": round(active_sold_ratio, 1),
        "active_count": ac, "sold_count": sc,
    }
    opportunity = {
        "score": opp_score, "verdict": opp_verdict, "description": opp_desc,
        "saturation": saturation, "alerts": alerts,
    }

    # Fee calculation (eBay only)
    fee_calc = _calculate_net_profit(potential_sell, potential_buy, shipping_cost,
                                     category, store_tier, promoted_rate)

    # Flip score
    score = 50
    if str_rate > 30: score += 15
    elif str_rate > 15: score += 8
    elif str_rate < 5: score -= 10
    if margin_pct > 50: score += 20
    elif margin_pct > 25: score += 12
    elif margin_pct > 10: score += 5
    elif margin_pct < 0: score -= 15
    else: score -= 8
    if velocity > 1: score += 10
    elif velocity > 0.3: score += 3
    elif velocity < 0.05: score -= 10
    if fee_calc["net_profit"] > 0 and fee_calc["net_margin_pct"] > 30: score += 5
    elif fee_calc["net_profit"] < 0: score -= 10
    score = max(0, min(100, round(score)))

    if score >= 70:
        verdict, detail = "🔥 Great Flip", "Strong demand, good margins after fees."
    elif score >= 50:
        verdict, detail = "✅ Decent Flip", "Reasonable margins after fees. Watch your buy price."
    elif score >= 30:
        verdict, detail = "⚠️ Risky Flip", "Tight margins or high competition."
    else:
        verdict, detail = "🚫 Avoid", "After fees, this is a losing proposition."

    return {
        "score": score, "verdict": verdict, "verdict_detail": detail,
        "sell_through_rate": round(str_rate, 1),
        "liquidity": {
            "label": liquidity_label, "description": liquidity_desc,
            "avg_days_to_sell": round(avg_days_to_sell, 1) if avg_days_to_sell else None,
            "velocity_per_day": round(velocity, 2), "velocity_label": velocity_label,
        },
        "potential_buy_price": round(potential_buy, 2),
        "potential_sell_price": round(potential_sell, 2),
        "potential_profit": fee_calc["net_profit"],
        "potential_profit_pct": fee_calc["net_margin_pct"],
        "gross_profit": round(margin_dollar, 2),
        "gross_profit_pct": round(margin_pct, 1),
        "velocity_per_day": round(velocity, 2), "velocity_label": velocity_label,
        "market_explanation": _build_market_explanation(trend, sm, am, ac, sc, velocity, str_rate,
                                                          buy_price, margin_dollar, category, store_tier, shipping_cost),
        "user_buy_price_used": buy_price > 0,
        "fee_calculation": fee_calc,
        "saturation": saturation,
        "opportunity": opportunity,
    }

def _build_market_explanation(trend, sold_median, active_median, active_count, sold_count,
                               velocity, str_rate, buy_price=0, margin_dollar=0,
                               category="default", store_tier="none", shipping_cost=0.0):
    parts = []
    if trend and len(trend) >= 2:
        first = trend[0]["median"]
        last = trend[-1]["median"]
        change_pct = ((last - first) / first * 100) if first > 0 else 0
        if change_pct > 10: parts.append(f"Prices rising sharply (+{change_pct:.0f}%). Strong demand.")
        elif change_pct > 3: parts.append(f"Prices trending up (+{change_pct:.0f}%).")
        elif change_pct > -3: parts.append(f"Prices stable ({change_pct:+.0f}%).")
        elif change_pct > -10: parts.append(f"Prices declining ({change_pct:+.0f}%).")
        else: parts.append(f"Prices falling ({change_pct:+.0f}%).")

    if sold_count > 0 and active_count > 0:
        r = active_count / sold_count
        if r > 5: parts.append(f"High supply ({active_count} active vs {sold_count} sold). Price competitively.")
        elif r > 2: parts.append(f"Moderate competition ({active_count} active vs {sold_count} sold).")
        else: parts.append(f"Low competition ({active_count} active for {sold_count} sold).")

    if velocity > 1: parts.append(f"Fast seller ({velocity:.1f}/day).")
    elif velocity > 0.1: parts.append(f"Moderate velocity ({velocity:.1f}/day).")
    else: parts.append(f"Slow mover ({velocity:.2f}/day).")

    if str_rate > 30: parts.append(f"Great sell-through ({str_rate:.0f}%).")
    elif str_rate > 10: parts.append(f"Decent sell-through ({str_rate:.0f}%).")

    if buy_price and buy_price > 0 and sold_median > 0:
        fc = _calculate_net_profit(sold_median, buy_price, shipping_cost, category, store_tier)
        net = fc["net_profit"]
        if net > 0:
            parts.append(f"At ${buy_price:.2f}, net ~${net:.2f} after eBay fees & shipping (gross ${margin_dollar:.2f}).")
        else:
            parts.append(f"At ${buy_price:.2f}, you'd lose ${abs(net):.2f} after eBay fees & shipping.")
    return " ".join(parts) if parts else "Not enough data to analyze."

# ── Main Search ──────────────────────────────────────────────────────────
import concurrent.futures

def _do_search(q: str, period_days: int, period: str, filter_condition: str,
               buy_price: float = 0.0, store_tier: str = "none",
               shipping_cost: float = 0.0, promoted_rate: float = 0.0,
               ebay_category_id: str = "") -> dict:
    now = datetime.now(timezone.utc)
    today_ymd = now.strftime("%Y-%m-%d")
    category = _detect_ebay_category(q, ebay_category_id)

    # Use ThreadPoolExecutor for parallel API calls
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        future_sold = executor.submit(_ebay_sold_listings, q, filter_condition, limit=100)
        future_active = executor.submit(_ebay_active_listings, q, filter_condition, limit=50)
        
        # Parallel fetch
        sold_items_raw = future_sold.result()
        active_items_raw = future_active.result()

    sold_candidates = _filter_by_relevance(sold_items_raw, q)
    sold_source_debug = SOLD_SOURCE_DEBUG.get(_sold_debug_key(q, filter_condition), {})
    source_label = "eBay Sold Search"
    if sold_items_raw and sold_items_raw[0].get("source"):
        source_label = sold_items_raw[0]["source"]

    # 2. Real eBay active listings (already fetched in parallel)
    active_items = _filter_by_relevance(active_items_raw, q)
    active_ids = {_extract_item_id_from_url(it.get("url", "")) for it in active_items if _extract_item_id_from_url(it.get("url", ""))}

    sold_candidates = [_validate_sold_item_basic(it, q, active_ids, today_ymd) for it in sold_candidates]
    sold_items = [it for it in sold_candidates if it.get("comp_valid")]
    excluded_sold = [it for it in sold_candidates if not it.get("comp_valid")]
    sold_source_breakdown = _sold_source_breakdown(sold_candidates)

    primary_source = next(iter(sold_source_breakdown.keys()), source_label)
    data_source = f"Verified sold listings ({len(sold_items)} validated of {len(sold_candidates)} relevant items via {primary_source or source_label})"
    confidence = "high" if len(sold_items) >= 5 else "medium" if len(sold_items) > 0 else "low"
    sold_source_status = _derive_sold_source_status(sold_source_debug, sold_items_raw, sold_candidates, sold_items)
    if sold_items:
        market_note = (
            f"Verified sold listings are sourced only from eBay's sold/completed search surface. "
            f"{len(excluded_sold)} sold-search results were excluded for missing/future dates, active overlap, or product mismatch."
            if excluded_sold else
            "Verified sold listings are sourced only from eBay's sold/completed search surface."
        )
    else:
        market_note = _sold_source_status_note(sold_source_status, sold_source_debug)

    # Filter
    sold_filtered = _filter_by_condition(sold_items, filter_condition)
    active_filtered = _filter_by_condition(active_items, filter_condition)

    # Stats
    sold_stats = _compute_stats(sold_filtered)
    active_stats = _compute_stats(active_filtered)
    condition_sold = _stats_by_condition(sold_items)
    condition_active = _stats_by_condition(active_items)

    median_price = sold_stats.get("median") or active_stats.get("median") or 0
    trend = _generate_trend(median_price, sold_filtered, period_days)
    trend_status = {
        "available": len(trend) >= 2,
        "reason": "" if len(trend) >= 2 else "not_enough_valid_dated_sales",
    }

    if len(trend) >= 2:
        first, last = trend[0]["median"], trend[-1]["median"]
        direction = "rising" if last > first * 1.03 else "falling" if last < first * 0.97 else "stable"
    else:
        direction = "stable"

    recent_sold = sorted(sold_filtered, key=lambda x: x.get("sold_date") or "", reverse=True)
    flip = _analyze_flip(sold_stats, active_stats, sold_filtered, active_filtered,
                         trend, condition_sold, buy_price, category, store_tier,
                         shipping_cost, promoted_rate)

    available_conditions = [c for c in EBAY_COND if c in condition_sold or c in condition_active]
    if not available_conditions:
        available_conditions = list(EBAY_COND.keys())

    # Promoted listings impact at different ad rates
    promoted_impact = []
    if sold_stats.get("median", 0) > 0 and buy_price > 0:
        for rate in [0, 2, 5, 10]:
            fc = _calculate_net_profit(sold_stats["median"], buy_price, shipping_cost, category, store_tier, rate)
            promoted_impact.append({
                "rate": rate,
                "net_profit": fc["net_profit"],
                "net_margin": fc["net_margin_pct"],
                "promoted_fee": fc["promoted_fee"],
            })

    available_conditions = [c for c in EBAY_COND if c in condition_sold or c in condition_active]
    if not available_conditions:
        available_conditions = list(EBAY_COND.keys())

    result = {
        "item_name": _extract_product_name_from_titles(sold_items_raw or active_items_raw, q) if _is_barcode_query(q) else q,
        "query": q,
        "period": period,
        "active_filter_condition": filter_condition or "all",
        "available_conditions": available_conditions,
        "condition_labels": {k: v["label"] for k, v in EBAY_COND.items()},
        "category": category,
        "ebay_category_id": ebay_category_id,
        "sold_summary": sold_stats,
        "active_summary": active_stats,
        "condition_sold": condition_sold,
        "condition_active": condition_active,
        "trend": trend,
        "trend_status": trend_status,
        "direction": direction,
        "recent_sold": recent_sold,
        "excluded_sold": excluded_sold,
        "active_listings": active_filtered,
        "data_source": data_source,
        "sold_source_status": sold_source_status,
        "sold_source_debug": sold_source_debug,
        "confidence": confidence,
        "confidence_label": {
            "high": "✅ High confidence — real eBay sales",
            "medium": "⚠️ Medium — limited real sales",
            "low": "❌ Low — no eBay sold data, use links",
        }.get(confidence, ""),
        "market_note": market_note,
        "flip_analysis": flip,
        "opportunity": flip.get("opportunity", {}),
        "promoted_impact": promoted_impact,
        "ebay_url": f"https://www.ebay.com/sch/i.html?_nkw={urllib.parse.quote_plus(q)}&LH_Sold=1&LH_Complete=1",
        "total_sold_scraped": len(sold_filtered),
        "total_active_scraped": len(active_filtered),
        "total_sold_before_relevance_filter": len(sold_items_raw),
        "total_active_before_relevance_filter": len(active_items_raw),
        "total_sold_before_validation": len(sold_candidates),
        "total_sold_excluded": len(excluded_sold),
        "sold_validation_summary": {
            "valid_count": len(sold_items),
            "excluded_count": len(excluded_sold),
            "excluded_reasons": _summarize_excluded_reasons(excluded_sold),
            "source_breakdown": sold_source_breakdown,
        },
        "buy_price": buy_price if buy_price > 0 else 0,
        "store_tier": store_tier,
        "shipping_cost": shipping_cost if shipping_cost > 0 else 0,
        "promoted_rate": promoted_rate,
        "api_missing": not (EBAY_CLIENT_ID and EBAY_CLIENT_SECRET),
        "setup_instructions": "To get real eBay prices: https://developer.ebay.com/signin → Create App → Set EBAY_CLIENT_ID and EBAY_CLIENT_SECRET env vars",
    }

    # Record search (fire-and-forget)
    try:
        import threading
        def _record():
            try:
                from firebase_service import get_provider
                get_provider().record_search(q, category)
            except Exception:
                pass
        threading.Thread(target=_record, daemon=True).start()
    except Exception:
        pass

    return result

# ── API Routes ───────────────────────────────────────────────────────────
@app.route("/api/search")
def api_search():
    q = request.args.get("q", "").strip()
    period = request.args.get("period", "6m")
    if period not in PERIOD_DAYS:
        period = "6m"
    period_days = PERIOD_DAYS[period]
    filter_condition = request.args.get("condition", "all").strip().lower()
    if filter_condition not in EBAY_COND and filter_condition != "all":
        filter_condition = "all"
    buy_price = float(request.args.get("buy_price", "0") or 0)
    store_tier = request.args.get("store_tier", "none").strip().lower()
    if store_tier not in EBAY_STORE_TIERS:
        store_tier = "none"
    shipping_cost = float(request.args.get("shipping", "0") or 0)
    promoted_rate = float(request.args.get("promoted_rate", "0") or 0)
    ebay_category_id = request.args.get("ebay_category_id", "").strip()

    if not q:
        return jsonify({"error": "Missing query"}), 400

    import copy
    base_cache_key = f"{q.lower()}|{period}|{filter_condition}|{ebay_category_id}"
    if base_cache_key in PRICE_CACHE:
        cached = copy.deepcopy(PRICE_CACHE[base_cache_key])
        age = (datetime.now(timezone.utc) - cached.get("_cached_at", datetime.now(timezone.utc))).total_seconds()
        if age < 300:
            cached["active_filter_condition"] = filter_condition
            cached["buy_price"] = buy_price if buy_price > 0 else 0
            cached["store_tier"] = store_tier
            cached["shipping_cost"] = shipping_cost if shipping_cost > 0 else 0
            cached["promoted_rate"] = promoted_rate
            cached["flip_analysis"] = _analyze_flip(
                cached.get("sold_summary", {}), cached.get("active_summary", {}),
                cached.get("recent_sold", []), cached.get("active_listings", []),
                cached.get("trend", []), cached.get("condition_sold", {}),
                buy_price, cached.get("category", "default"), store_tier,
                shipping_cost, promoted_rate
            )
            cached["opportunity"] = cached["flip_analysis"].get("opportunity", {})
            sold_median = cached.get("sold_summary", {}).get("median", 0)
            promoted_impact = []
            if sold_median > 0 and buy_price > 0:
                for rate in [0, 2, 5, 10]:
                    fc = _calculate_net_profit(sold_median, buy_price, shipping_cost, cached.get("category", "default"), store_tier, rate)
                    promoted_impact.append({
                        "rate": rate,
                        "net_profit": fc["net_profit"],
                        "net_margin": fc["net_margin_pct"],
                        "promoted_fee": fc["promoted_fee"],
                    })
            cached["promoted_impact"] = promoted_impact
            return jsonify(cached)

    try:
        result = _do_search(q, period_days, period, filter_condition, buy_price,
                            store_tier, shipping_cost, promoted_rate, ebay_category_id)
        result["_cached_at"] = datetime.now(timezone.utc)
        PRICE_CACHE[base_cache_key] = copy.deepcopy(result)
        return jsonify(result)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e), "query": q}), 500

@app.route("/api/recalculate", methods=["POST"])
def api_recalculate():
    """Recalculate market stats from the currently-visible listing arrays.

    Used by the UI when a user manually removes bad sold/active comps. This
    avoids another eBay API call and makes the medians/flip analysis update
    immediately from the human-curated comp set.
    """
    payload = request.get_json(silent=True) or {}
    d = payload.get("data") or payload

    def _as_float(v, default=0.0):
        try:
            return float(v or default)
        except (TypeError, ValueError):
            return default

    def _clean_items(items):
        cleaned = []
        for it in items or []:
            if not isinstance(it, dict):
                continue
            price = _as_float(it.get("price"), 0)
            if price <= 0:
                continue
            cleaned.append({
                "title": str(it.get("title") or ""),
                "price": price,
                "shipping": _as_float(it.get("shipping"), 0),
                "sold_date": it.get("sold_date"),
                "sold_date_raw": it.get("sold_date_raw"),
                "condition": it.get("condition") if it.get("condition") in EBAY_COND else "used",
                "url": str(it.get("url") or ""),
                "verification_url": str(it.get("verification_url") or ""),
                "url_type": str(it.get("url_type") or ""),
                "item_id": str(it.get("item_id") or ""),
                "source": it.get("source"),
                "source_confidence": it.get("source_confidence"),
                "active_overlap": bool(it.get("active_overlap")),
                "comp_valid": bool(it.get("comp_valid", True)),
                "reject_reasons": list(it.get("reject_reasons") or []),
                "warning_reasons": list(it.get("warning_reasons") or []),
                "is_auction": bool(it.get("is_auction")),
                "relevance": it.get("relevance"),
            })
        return cleaned

    q = str(d.get("query") or "").strip()
    if not q:
        return jsonify({"error": "Missing query"}), 400

    period = str(d.get("period") or "6m")
    if period not in PERIOD_DAYS:
        period = "6m"
    period_days = PERIOD_DAYS[period]

    filter_condition = str(d.get("active_filter_condition") or "all").strip().lower()
    if filter_condition not in EBAY_COND and filter_condition != "all":
        filter_condition = "all"

    buy_price = _as_float(d.get("buy_price"), 0)
    store_tier = str(d.get("store_tier") or "none").strip().lower()
    if store_tier not in EBAY_STORE_TIERS:
        store_tier = "none"
    shipping_cost = _as_float(d.get("shipping_cost"), 0)
    promoted_rate = _as_float(d.get("promoted_rate"), 0)
    ebay_category_id = str(d.get("ebay_category_id") or "")
    category = str(d.get("category") or "") or _detect_ebay_category(q, ebay_category_id)

    sold_items = _clean_items(d.get("recent_sold"))
    active_items = _clean_items(d.get("active_listings"))

    sold_filtered = _filter_by_condition(sold_items, filter_condition)
    active_filtered = _filter_by_condition(active_items, filter_condition)

    sold_stats = _compute_stats(sold_filtered)
    active_stats = _compute_stats(active_filtered)
    condition_sold = _stats_by_condition(sold_items)
    condition_active = _stats_by_condition(active_items)

    median_price = sold_stats.get("median") or active_stats.get("median") or 0
    trend = _generate_trend(median_price, sold_filtered, period_days)
    if len(trend) >= 2:
        first, last = trend[0]["median"], trend[-1]["median"]
        direction = "rising" if last > first * 1.03 else "falling" if last < first * 0.97 else "stable"
    else:
        direction = "stable"

    flip = _analyze_flip(sold_stats, active_stats, sold_filtered, active_filtered,
                         trend, condition_sold, buy_price, category, store_tier,
                         shipping_cost, promoted_rate)

    promoted_impact = []
    if sold_stats.get("median", 0) > 0 and buy_price > 0:
        for rate in [0, 2, 5, 10]:
            fc = _calculate_net_profit(sold_stats["median"], buy_price, shipping_cost, category, store_tier, rate)
            promoted_impact.append({
                "rate": rate,
                "net_profit": fc["net_profit"],
                "net_margin": fc["net_margin_pct"],
                "promoted_fee": fc["promoted_fee"],
            })

    available_conditions = [c for c in EBAY_COND if c in condition_sold or c in condition_active]
    if not available_conditions:
        available_conditions = d.get("available_conditions") or list(EBAY_COND.keys())

    result = dict(d)
    result.update({
        "query": q,
        "period": period,
        "active_filter_condition": filter_condition,
        "available_conditions": available_conditions,
        "condition_labels": {k: v["label"] for k, v in EBAY_COND.items()},
        "category": category,
        "ebay_category_id": ebay_category_id,
        "sold_summary": sold_stats,
        "active_summary": active_stats,
        "condition_sold": condition_sold,
        "condition_active": condition_active,
        "trend": trend,
        "trend_status": {"available": len(trend) >= 2, "reason": "" if len(trend) >= 2 else "not_enough_valid_dated_sales"},
        "direction": direction,
        "recent_sold": sorted(sold_filtered, key=lambda x: x.get("sold_date") or "", reverse=True),
        "active_listings": active_filtered,
        "flip_analysis": flip,
        "opportunity": flip.get("opportunity", {}),
        "promoted_impact": promoted_impact,
        "total_sold_scraped": len(sold_filtered),
        "total_active_scraped": len(active_filtered),
        "sold_validation_summary": {
            "valid_count": len(d.get("recent_sold") or sold_filtered),
            "excluded_count": len(d.get("excluded_sold") or []),
            "excluded_reasons": _summarize_excluded_reasons(d.get("excluded_sold") or []),
        },
        "market_note": "Manual comp edits applied. Medians and analysis updated from your curated listings.",
        "buy_price": buy_price if buy_price > 0 else 0,
        "store_tier": store_tier,
        "shipping_cost": shipping_cost if shipping_cost > 0 else 0,
        "promoted_rate": promoted_rate,
    })
    result.pop("_cached_at", None)
    return jsonify(result)


@app.route("/api/lot-calculate", methods=["POST"])
def api_lot_calculate():
    data = request.get_json() or {}
    items = data.get("items", [])
    if not items:
        return jsonify({"error": "No items provided"}), 400

    store_tier = data.get("store_tier", "none").strip().lower()
    if store_tier not in EBAY_STORE_TIERS:
        store_tier = "none"
    shipping_per_item = float(data.get("shipping_per_item", 0) or 0)
    total_custom_cost = float(data.get("total_lot_cost", 0) or 0)

    total_market = 0.0
    total_cost = 0.0
    total_fees = 0.0
    breakdown = []

    for it in items:
        name = it.get("name", "").strip()
        price = float(it.get("price", 0) or 0)
        if not name:
            continue

        res = None
        for k, v in PRICE_CACHE.items():
            if k.startswith(f"{name.lower()}|") and v.get("sold_summary"):
                res = v
                break

        if not res:
            try:
                res = _do_search(name, 180, "6m", "all")
            except Exception:
                res = {}

        sold_summary = res.get("sold_summary", {})
        market_val = float(sold_summary.get("median", 0) or 0)

        if market_val <= 0:
            market_val = price if price > 0 else 0.0

        total_market += market_val
        total_cost += price
        
        fee_rate = 0.1325
        item_fee = (market_val + shipping_per_item) * fee_rate + 0.30 if market_val > 0 else 0
        total_fees += item_fee

        item_name_disp = res.get("item_name", name) or name
        breakdown.append({
            "name": item_name_disp,
            "market_value": market_val,
            "cost": price,
            "fee": round(item_fee, 2),
            "net": round(market_val - price - item_fee - shipping_per_item, 2),
            "sold_count": sold_summary.get("count", 0),
        })

    if total_custom_cost > 0:
        total_cost = total_custom_cost

    total_shipping = shipping_per_item * len(items)
    total_cost_with_ship = total_cost + total_shipping
    total_profit = total_market - total_cost_with_ship - total_fees

    if total_profit > total_cost_with_ship * 0.4 and total_profit > 25:
        verdict = "🔥 STRONG LOT BUY"
        color = "green"
    elif total_profit > 0:
        verdict = "👍 GOOD BUNDLE"
        color = "green"
    elif total_profit > -15:
        verdict = "⚠️ BORDERLINE LOT"
        color = "amber"
    else:
        verdict = "🚫 PASS ON THIS LOT"
        color = "red"

    return jsonify({
        "verdict": verdict,
        "verdict_color": color,
        "total_cost": round(total_cost_with_ship, 2),
        "total_market_value": round(total_market, 2),
        "total_fees": round(total_fees, 2),
        "total_profit": round(total_profit, 2),
        "item_breakdown": breakdown,
    })


@app.route("/api/status")
def api_status():
    return jsonify({
        "ebay_configured": bool(EBAY_CLIENT_ID and EBAY_CLIENT_SECRET),
        "gemini_configured": bool(GEMINI_API_KEY),
        "pricecharting_enabled": ENABLE_PRICECHARTING,
    })

@app.route("/api/categories")
def api_categories():
    q = request.args.get("q", "").strip()
    if not q: return jsonify({"error": "Missing query"}), 400
    suggestions = _ebay_category_suggestions(q)
    return jsonify({"query": q, "suggestions": suggestions})

@app.route("/api/promoted-impact")
def api_promoted_impact():
    q = request.args.get("q", "").strip()
    buy_price = float(request.args.get("buy_price", "0") or 0)
    store_tier = request.args.get("store_tier", "none").strip().lower()
    shipping_cost = float(request.args.get("shipping", "0") or 0)
    category_id = request.args.get("ebay_category_id", "").strip()
    if not q or buy_price <= 0: return jsonify({"error": "Query and buy price required"}), 400
    try:
        r = _do_search(q, 180, "6m", "all", buy_price, store_tier, shipping_cost, 0, category_id)
        return jsonify({"query": q, "promoted_impact": r.get("promoted_impact", []), "category": r.get("category")})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

PROMOTED_VELOCITY_MULTIPLIERS = {
    0: 1.0, 2: 1.15, 5: 1.35, 10: 1.60, 15: 1.80,
}

@app.route("/api/promoted-optimize")
def api_promoted_optimize():
    """Recommend the optimal Promoted Listings ad rate based on expected daily profit."""
    q = request.args.get("q", "").strip()
    buy_price = float(request.args.get("buy_price", "0") or 0)
    store_tier = request.args.get("store_tier", "none").strip().lower()
    if store_tier not in EBAY_STORE_TIERS:
        store_tier = "none"
    shipping_cost = float(request.args.get("shipping", "0") or 0)
    category_id = request.args.get("ebay_category_id", "").strip()
    if not q or buy_price <= 0:
        return jsonify({"error": "Query and buy price required"}), 400
    try:
        r = _do_search(q, 180, "6m", "all", buy_price, store_tier, shipping_cost, 0, category_id)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    sold_median = r["sold_summary"].get("median", 0)
    if sold_median <= 0:
        return jsonify({"error": "No sold data to estimate market price"}), 400
    category = r.get("category", "default")
    base_velocity = r["flip_analysis"].get("velocity_per_day", 0) or 0.01
    results = []
    best = None
    for rate, mult in PROMOTED_VELOCITY_MULTIPLIERS.items():
        fc = _calculate_net_profit(sold_median, buy_price, shipping_cost, category, store_tier, rate)
        expected_daily = fc["net_profit"] * base_velocity * mult
        velocity = max(base_velocity * mult, 0.001)
        entry = {
            "rate": rate,
            "net_profit": round(fc["net_profit"], 2),
            "net_margin": round(fc["net_margin_pct"], 1),
            "promoted_fee": round(fc["promoted_fee"], 2),
            "velocity_multiplier": mult,
            "expected_daily_profit": round(expected_daily, 2),
            "days_to_sell_estimate": round(1 / velocity, 1),
        }
        results.append(entry)
        if best is None or expected_daily > best["expected_daily_profit"]:
            best = entry
    reason = "Maximizes expected daily profit by balancing ad cost with faster sell-through."
    if best and best["rate"] == 0:
        reason = "No ad spend is optimal because the margin is too thin for promoted listings to pay off."
    return jsonify({
        "query": q,
        "market_median": round(sold_median, 2),
        "buy_price": round(buy_price, 2),
        "category": category,
        "base_velocity_per_day": round(base_velocity, 2),
        "recommendation": {**best, "reason": reason} if best else None,
        "scenarios": results,
    })

# ── Title Optimizer ────────────────────────────────────────────────────
TITLE_STOP_WORDS = {
    "the", "a", "an", "and", "or", "but", "for", "with", "without", "from", "to", "of", "in", "on", "at", "by",
    "is", "are", "was", "were", "be", "been", "being", "it", "its", "this", "that", "these", "those", "have", "has", "had",
    "do", "does", "did", "will", "would", "could", "should", "may", "might", "must", "can", "shall", "about", "up", "out", "so", "if",
    "new", "used", "good", "very", "excellent", "condition", "working", "tested", "untested", "parts", "only", "free", "shipping",
    "fast", "quick", "sale", "sold", "listing", "item", "lot", "bundle", "includes", "include", "comes", "come", "please", "read",
    "description", "details", "more", "info", "information", "see", "photos", "pictures", "pic", "image", "images", "view", "look",
    "buy", "now", "today", "usd", "us", "ship", "ships", "shipped", "worldwide", "usa", "authentic", "genuine", "original", "official",
    "box", "case", "manual", "cable", "charger", "adapter", "cord", "remote", "controller", "battery", "batteries", "strap", "cover",
}

def _extract_title_keywords(titles: list[str]) -> dict:
    """Extract keyword frequency from eBay listing titles."""
    counts = defaultdict(int)
    bigrams = defaultdict(int)
    for title in titles:
        words = re.findall(r'[a-zA-Z0-9]+', title.lower())
        # Filter
        filtered = [w for w in words if len(w) > 1 and w not in TITLE_STOP_WORDS]
        for w in filtered:
            counts[w] += 1
        for i in range(len(filtered) - 1):
            bigram = filtered[i] + " " + filtered[i + 1]
            bigrams[bigram] += 1
    # Merge bigrams into counts if they appear frequently
    for bg, c in bigrams.items():
        if c >= 2:
            counts[bg] = c
    return dict(sorted(counts.items(), key=lambda x: x[1], reverse=True))

def _score_title(title: str, keywords: dict) -> int:
    """Score a title based on how many high-frequency keywords it contains."""
    if not title or not keywords:
        return 0
    tl = title.lower()
    score = 0
    max_freq = max(keywords.values()) if keywords else 1
    for kw, freq in keywords.items():
        if kw in tl:
            score += int((freq / max_freq) * 100)
    return min(100, score)

def _build_optimized_title(query: str, current_title: str, keywords: dict) -> str:
    """Build a title using the most valuable keywords, keeping it under 80 chars."""
    # Start with the item name / query
    base = query.strip()
    used = set(base.lower().split())
    parts = [base]
    remaining = 80 - len(base) - 1
    # Add top keywords that are not already in base
    for kw, freq in keywords.items():
        if remaining <= 0:
            break
        kw_clean = kw.strip()
        # Skip if already covered by base words
        if all(w in used for w in kw_clean.split()):
            continue
        if len(kw_clean) + 1 <= remaining:
            parts.append(kw_clean)
            used.update(kw_clean.split())
            remaining -= (len(kw_clean) + 1)
    title = " ".join(parts)
    return title[:80]

def _analyze_titles_for_insights(titles: list[str], prices: list[float]) -> list[dict]:
    """Find keyword patterns that correlate with higher prices."""
    if not titles or not prices or len(titles) != len(prices):
        return []
    keyword_prices = defaultdict(list)
    for title, price in zip(titles, prices):
        words = re.findall(r'[a-zA-Z0-9]+', title.lower())
        seen = set()
        for w in words:
            if len(w) > 2 and w not in TITLE_STOP_WORDS and w not in seen:
                keyword_prices[w].append(price)
                seen.add(w)
    insights = []
    for kw, prices_list in keyword_prices.items():
        if len(prices_list) < 3:
            continue
        avg = sum(prices_list) / len(prices_list)
        insights.append({"keyword": kw, "avg_price": round(avg, 2), "count": len(prices_list)})
    insights.sort(key=lambda x: x["avg_price"], reverse=True)
    return insights[:10]

@app.route("/api/title-optimize")
def api_title_optimize():
    """Suggest an optimized eBay title based on top-selling listings."""
    q = request.args.get("q", "").strip()
    current_title = request.args.get("current_title", "").strip()
    condition = request.args.get("condition", "all").strip().lower()
    if condition not in EBAY_COND and condition != "all":
        condition = "all"
    if not q:
        return jsonify({"error": "Query required"}), 400
    sold_items = _ebay_sold_listings(q, condition, limit=100)
    if not sold_items:
        return jsonify({"error": "No eBay sold listings found to analyze"}), 400
    titles = [it.get("title", "") for it in sold_items]
    prices = [it.get("price", 0) for it in sold_items]
    keywords = _extract_title_keywords(titles)
    top_keywords = dict(list(keywords.items())[:30])
    suggested_title = _build_optimized_title(q, current_title, top_keywords)
    current_score = _score_title(current_title, top_keywords) if current_title else 0
    suggested_score = _score_title(suggested_title, top_keywords)
    insights = _analyze_titles_for_insights(titles, prices)
    top_titles = sorted(sold_items, key=lambda x: x.get("price", 0), reverse=True)[:5]
    return jsonify({
        "query": q,
        "condition": condition,
        "current_title": current_title or None,
        "current_score": current_score,
        "suggested_title": suggested_title,
        "suggested_score": suggested_score,
        "top_keywords": top_keywords,
        "price_insights": insights,
        "top_selling_titles": [{"title": it.get("title"), "price": it.get("price"), "url": it.get("url")} for it in top_titles],
        "ebay_url": f"https://www.ebay.com/sch/i.html?_nkw={urllib.parse.quote_plus(q)}&LH_Sold=1&LH_Complete=1",
    })

# ── Sales Analytics ──────────────────────────────────────────────────────
def _title_similarity(a: str, b: str) -> float:
    """Simple token-overlap similarity between two titles."""
    if not a or not b:
        return 0.0
    a_tokens = set(re.findall(r'[a-z0-9]+', a.lower()))
    b_tokens = set(re.findall(r'[a-z0-9]+', b.lower()))
    if not a_tokens or not b_tokens:
        return 0.0
    overlap = a_tokens & b_tokens
    return len(overlap) / max(len(a_tokens), len(b_tokens))

def _match_inventory_to_title(inventory: list[dict], title: str) -> tuple[dict | None, float]:
    """Find the best matching inventory item for an eBay order line item."""
    best_match = None
    best_score = 0.0
    for item in inventory:
        score = _title_similarity(title, item.get("item_name", ""))
        if score > best_score and score > 0.5:
            best_score = score
            best_match = item
    return best_match, best_score

def _analyze_sales(user_id: str, store_tier: str = "none", start_date: str = "", end_date: str = "") -> dict | None:
    """Pull eBay sold orders and match them to PriceSpy inventory for profit analysis."""
    orders = _ebay_seller_api_get(user_id, "/sell/fulfillment/v1/order", params={"limit": 200})
    if orders is None:
        return None
    inventory = get_provider().get_inventory(user_id)
    matched = []
    unmatched = []
    total_revenue = 0.0
    total_cost = 0.0
    total_fees = 0.0
    total_profit = 0.0
    sales_by_month = defaultdict(float)

    for order in orders.get("orders", []):
        order_date = str(order.get("creationDate", ""))[:10]
        if start_date and order_date < start_date:
            continue
        if end_date and order_date > end_date:
            continue
        for line_item in order.get("lineItems", []):
            title = line_item.get("title", "")
            price_info = line_item.get("lineItemCost", {})
            price = float(price_info.get("value", 0)) if isinstance(price_info, dict) else 0.0
            if price <= 0:
                continue
            total_revenue += price

            inv_item, score = _match_inventory_to_title(inventory, title)
            if inv_item:
                buy_price = inv_item.get("buy_price", 0) or 0.0
                category = _detect_ebay_category(title)
                fees = _calculate_ebay_fees(price, 0.0, category, store_tier)
                profit = price - buy_price - fees["total_fees"]
                total_cost += buy_price
                total_fees += fees["total_fees"]
                total_profit += profit
                matched.append({
                    "title": title,
                    "sold_price": round(price, 2),
                    "buy_price": round(buy_price, 2),
                    "fees": round(fees["total_fees"], 2),
                    "profit": round(profit, 2),
                    "sold_date": order_date,
                    "inventory_id": inv_item.get("id"),
                    "match_score": round(score, 2),
                })
                month = order_date[:7] if len(order_date) >= 7 else "unknown"
                sales_by_month[month] += profit
            else:
                unmatched.append({
                    "title": title,
                    "sold_price": round(price, 2),
                    "sold_date": order_date,
                })
                month = order_date[:7] if len(order_date) >= 7 else "unknown"
                sales_by_month[month] += price

    return {
        "summary": {
            "total_revenue": round(total_revenue, 2),
            "total_cost": round(total_cost, 2),
            "total_fees": round(total_fees, 2),
            "total_profit": round(total_profit, 2),
            "margin_pct": round((total_profit / total_revenue * 100), 1) if total_revenue > 0 else 0.0,
            "items_sold": len(matched) + len(unmatched),
            "matched_items": len(matched),
            "unmatched_items": len(unmatched),
        },
        "matched": sorted(matched, key=lambda x: x["profit"], reverse=True),
        "unmatched": unmatched,
        "sales_by_month": [{"month": m, "profit": round(p, 2)} for m, p in sorted(sales_by_month.items())],
    }

@app.route("/api/analytics/sales")
def api_analytics_sales():
    """Return sales analytics for the connected eBay seller account."""
    user_id = _get_user_id_from_request()
    if not user_id:
        return jsonify({"error": "Login required"}), 401
    store_tier = request.args.get("store_tier", "none").strip().lower()
    if store_tier not in EBAY_STORE_TIERS:
        store_tier = "none"
    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()
    if start_date and not re.match(r"\d{4}-\d{2}-\d{2}", start_date):
        start_date = ""
    if end_date and not re.match(r"\d{4}-\d{2}-\d{2}", end_date):
        end_date = ""
    result = _analyze_sales(user_id, store_tier, start_date, end_date)
    if result is None:
        return jsonify({"error": "Could not fetch eBay sales. Ensure seller account is connected and has fulfillment scope."}), 400
    return jsonify(result)

@app.route("/api/analytics/inventory-profit")
def api_analytics_inventory_profit():
    """Estimate profit for current inventory if sold at market median."""
    user_id = _get_user_id_from_request()
    if not user_id:
        return jsonify({"error": "Login required"}), 401
    store_tier = request.args.get("store_tier", "none").strip().lower()
    if store_tier not in EBAY_STORE_TIERS:
        store_tier = "none"
    shipping = float(request.args.get("shipping", "0") or 0)
    inventory = get_provider().get_inventory(user_id)
    results = []
    for item in inventory:
        if item.get("status") == "sold":
            continue
        name = item.get("item_name", "").strip()
        buy_price = item.get("buy_price", 0) or 0.0
        if not name or buy_price <= 0:
            continue
        try:
            r = _do_search(name, 180, "6m", "all", buy_price, store_tier, shipping)
            fc = r.get("flip_analysis", {}).get("fee_calculation", {})
            results.append({
                "item_name": name,
                "buy_price": round(buy_price, 2),
                "market_median": round(r["sold_summary"].get("median", 0), 2),
                "net_profit": round(fc.get("net_profit", 0), 2),
                "flip_score": r.get("flip_analysis", {}).get("score", 0),
            })
        except Exception:
            continue
    results.sort(key=lambda x: x["net_profit"], reverse=True)
    return jsonify({"items": results[:50], "count": len(results)})

@app.route("/api/quick-deal")
def api_quick_deal():
    raw = request.args.get("input", "").strip()
    if not raw:
        return jsonify({"error": "Enter item and price. e.g. 'Nikon D850, good, $400'"}), 400
    store_tier = request.args.get("store_tier", "none").strip().lower()
    if store_tier not in EBAY_STORE_TIERS:
        store_tier = "none"
    shipping_cost = float(request.args.get("shipping", "0") or 0)
    ebay_category_id = request.args.get("ebay_category_id", "").strip()

    # Parse price
    price_match = re.search(r'\$?\s*(\d+(?:\.\d{1,2})?)\s*$', raw)
    buy_price = 0.0
    item_part = raw
    if price_match:
        buy_price = float(price_match.group(1))
        item_part = raw[:price_match.start()].strip().rstrip(",")
        item_part = re.sub(r'\s+(for|at)\s*$', '', item_part, flags=re.IGNORECASE)

    # Detect condition
    detected_condition = "used"
    best_score = 0
    item_lower = item_part.lower()
    for alias, canonical in sorted(CONDITION_ALIASES.items(), key=lambda x: -len(x[0])):
        if alias in item_lower:
            detected_condition = canonical
            best_score = len(alias)
            break

    # Clean item name
    if best_score > 0:
        cleaned = item_lower
        for alias in [detected_condition] + [k for k, v in CONDITION_ALIASES.items() if v == detected_condition]:
            cleaned = cleaned.replace(alias, "")
        cleaned = re.sub(r'\s+,', ',', cleaned).strip().strip(",")
        if len(cleaned) > 3:
            item_part = cleaned

    item_name = item_part.strip().strip(",").strip()
    if not item_name or len(item_name) < 3:
        return jsonify({"error": "Could not identify the item. Try: 'Nikon D850, good, $400'"}), 400

    try:
        result = _do_search(item_name, 180, "6m", detected_condition, buy_price,
                            store_tier, shipping_cost, 0, ebay_category_id)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"Search failed: {str(e)}"}), 500

    flip = result.get("flip_analysis", {})
    fc = flip.get("fee_calculation", {})
    net_profit = fc.get("net_profit", 0)
    score = flip.get("score", 0)
    market_median = result["sold_summary"].get("median", 0)
    market_low = result["sold_summary"].get("low", 0)
    market_high = result["sold_summary"].get("high", 0)
    liq = flip.get("liquidity", {})
    sat = flip.get("saturation", {})

    if net_profit > 0 and score >= 50:
        verdict, label, color, reason = "BUY", "🔥 BUY IT", "green", f"This is a ${abs(net_profit):.0f} profit after eBay fees. Buy immediately."
    elif net_profit > 0 and score >= 30:
        verdict, label, color, reason = "MAYBE", "🤔 MAYBE", "amber", "Small profit but market is competitive. Negotiate down."
    else:
        verdict, label, color, reason = "LEAVE", "🚫 LEAVE IT", "red", "After eBay fees, you'll lose money. Walk away."

    return jsonify({
        "verdict": verdict, "verdict_label": label, "verdict_color": color,
        "verdict_reason": reason,
        "item_name": item_name,
        "detected_condition": detected_condition,
        "detected_condition_label": EBAY_COND.get(detected_condition, {}).get("label", detected_condition),
        "your_price": buy_price if buy_price > 0 else None,
        "market_value_range": f"${market_low:.0f} – ${market_high:.0f}",
        "market_median": round(market_median, 2),
        "flip_score": score,
        "net_profit": round(net_profit, 2),
        "net_profit_display": f"{'+' if net_profit >= 0 else ''}${net_profit:.2f}",
        "net_margin": round(fc.get("net_margin_pct", 0), 1),
        "days_to_sell": round(liq.get("avg_days_to_sell", 30), 1) if liq.get("avg_days_to_sell") else 30,
        "velocity_label": liq.get("velocity_label", "Unknown"),
        "competition_ratio": round(sat.get("active_sold_ratio", 1), 1) if isinstance(sat, dict) else 1,
        "competition_label": (
            "Low" if (isinstance(sat, dict) and sat.get("active_sold_ratio", 1) < 1) else
            "Moderate" if (isinstance(sat, dict) and sat.get("active_sold_ratio", 1) < 3) else
            "High" if (isinstance(sat, dict) and sat.get("active_sold_ratio", 1) < 8) else "Very High"
        ),
        "full_result": result,
    })

# ── Photo Identification (Gemini only, no price estimation) ──────────────
GEMINI_PROMPT = """Identify this product precisely — brand, model name/number, colorway/variant, and any distinguishing features visible.

Return ONLY the specific product identifier that an eBay seller would use to find comparable sold listings, in this format:
  Brand + Model/Product Name + Key Variant

Rules:
- Do NOT include words like "condition", "price", "New", "Used", "Boxed", or extra conversational filler.
- If the image clearly shows a UPC barcode or serial number, you can include that or return the exact model number.
- Examples of perfect outputs:
  - "Nintendo Switch OLED Console White"
  - "Nike Dunk Low Retro Black White"
  - "DeWalt DCD791 Brushless Drill"
  - "Sony WH-1000XM5 Headphones"
If you truly cannot identify anything searchable, say "Unknown item"."""

def _build_gemini_identify_prompt(user_context: str = "") -> str:
    user_context = (user_context or "").strip()[:500]
    if not user_context:
        return GEMINI_PROMPT
    return GEMINI_PROMPT + f"""

User-provided extra hint about the photo:
"{user_context}"

Combine this hint with the visual evidence to produce the single perfect eBay search title."""

@app.route("/api/identify", methods=["POST"])
def api_identify():
    files = request.files.getlist("images") + request.files.getlist("image")
    files = [f for f in files if f and f.filename]
    if not files:
        return jsonify({"error": "No image provided"}), 400
    user_context = request.form.get("context", "").strip()
    if not GEMINI_API_KEY:
        return jsonify({"description": "", "error": "❌ Gemini AI API Key not configured! Go to your Render/deployment dashboard → Environment Variables → Add GEMINI_API_KEY (get a free key from aistudio.google.com)."}), 200
    try:
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        image_parts = []
        for f in files:
            img_bytes = f.read()
            mime_type = f.mimetype or "image/jpeg"
            image_parts.append({"mime_type": mime_type, "data": img_bytes})
        prompt = _build_gemini_identify_prompt(user_context)
        
        try:
            model = genai.GenerativeModel("gemini-2.5-flash-lite")
            response = model.generate_content(image_parts + [prompt])
        except Exception as e1:
            print(f"gemini-2.5-flash-lite failed ({e1}), trying gemini-2.5-flash...")
            model = genai.GenerativeModel("gemini-2.5-flash")
            response = model.generate_content(image_parts + [prompt])
            
        description = response.text.strip()
        description = re.sub(r'^["\']|["\']$', '', description).strip()
        return jsonify({"description": description, "provider": "gemini", "context_used": bool(user_context)})
    except Exception as e:
        print(f"Gemini identification failed: {e}")
        return jsonify({"description": "", "error": f"❌ Gemini AI error: {e}"}), 200

# ── Shipping Cost Estimator (Gemini structured JSON) ───────────────────
SHIPPING_ESTIMATE_PROMPT = """You are a shipping cost estimator for US-based eBay/flipping sellers.
Given the product below, estimate the typical cost a small online seller would pay to ship it to a domestic US buyer using USPS or UPS ground services.

Pick the cheapest reasonable shipping option for a small parcel (under 20 lb) shipped by an individual seller.
Use your real-world knowledge of current 2025 USPS/UPS retail rates.

Product name: {item_name}
Approximate weight: {weight_str}
Approximate packed dimensions: {dims_str}

Return ONLY a JSON object with these fields:
- low_usd: number (cheapest reasonable option, e.g. USPS Ground Advantage)
- mid_usd: number (most likely actual cost)
- high_usd: number (faster/premium option if applicable, e.g. USPS Priority Mail)
- carrier: string (e.g. "USPS", "UPS")
- service: string (specific service, e.g. "Ground Advantage", "Priority Mail", "UPS Ground")
- weight_lb_estimate: number (your best guess of packed weight in pounds)
- reasoning: string (one short sentence explaining the estimate)
- confidence: string ("high" if item is specific, "medium" if somewhat generic, "low" if very generic)

If the item appears to be very fragile, oversized, or hazardous, mention that in reasoning but still give a numeric estimate."""

# Cache for shipping estimates (keyed on normalized item name)
SHIPPING_CACHE: dict[str, dict] = {}
SHIPPING_CACHE_TTL = 7 * 24 * 3600  # 7 days — shipping rates don't change daily

# Rough weight hints by item keyword — used to give the AI a better starting point
WEIGHT_HINTS_LB = {
    "iphone": 1.0, "smartphone": 1.0, "phone": 1.0, "cell phone": 1.0,
    "ipad": 2.0, "tablet": 2.0,
    "macbook": 6.0, "laptop": 6.0, "chromebook": 4.0,
    "headphone": 1.5, "headphones": 1.5, "earbuds": 0.5, "airpods": 0.5,
    "watch": 1.0, "apple watch": 1.0, "smartwatch": 1.0,
    "textbook": 3.0, "book": 1.5, "hardcover book": 2.0, "paperback": 1.0,
    "comic": 0.3, "magazine": 0.5,
    "video game": 0.5, "nintendo switch": 3.0, "switch lite": 2.0,
    "playstation 5": 10.0, "ps5": 10.0, "playstation 4": 7.0, "ps4": 7.0,
    "xbox series x": 13.0, "xbox series s": 6.0, "xbox one": 8.0,
    "controller": 1.0, "joycon": 0.5,
    "camera": 3.0, "dslr": 3.0, "mirrorless camera": 2.5,
    "shoe": 3.0, "sneaker": 3.0, "boot": 4.0, "jordan": 3.0, "dunk": 3.0, "yeezy": 3.0,
    "shirt": 1.0, "t-shirt": 0.8, "jacket": 2.0, "hoodie": 1.5, "sweater": 1.5,
    "lego": 3.0, "toy": 2.0, "action figure": 1.0, "funko": 0.5, "doll": 2.0,
    "pokemon card": 0.1, "trading card": 0.1, "mtg": 0.1, "yugioh": 0.1,
    "drill": 5.0, "tool": 5.0, "dewalt": 6.0, "milwaukee": 6.0, "makita": 6.0,
    "speaker": 4.0, "bluetooth speaker": 1.5,
    "monitor": 15.0, "tv": 30.0,
    "keyboard": 3.0, "mechanical keyboard": 3.0,
    "mouse": 0.5, "gaming mouse": 0.5,
    "router": 2.0, "modem": 2.0,
    "vinyl record": 1.0, "lp": 1.0,
    "puzzle": 2.0,
    "guitar": 12.0, "fender stratocaster": 12.0, "gibson": 12.0,
    "amplifier": 15.0, "amp": 15.0,
    "purse": 2.0, "handbag": 2.0, "wallet": 0.5, "belt": 0.5,
    "hat": 0.5, "cap": 0.5, "beanie": 0.3,
    "mug": 1.5, "cup": 1.0, "glass": 1.5,
    "lamp": 3.0,
    "kayak": 50.0, "tent": 8.0,
}

def _estimate_weight_lb_hint(item_name: str) -> float:
    n = (item_name or "").lower()
    # Longest keys first so "nintendo switch" matches before "switch"
    for k in sorted(WEIGHT_HINTS_LB.keys(), key=len, reverse=True):
        if k in n:
            return WEIGHT_HINTS_LB[k]
    return 1.0  # generic small-parcel default


def _normalize_ship_key(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower().strip())


def _get_cached_shipping(item_name: str) -> dict | None:
    entry = SHIPPING_CACHE.get(_normalize_ship_key(item_name))
    if not entry:
        return None
    try:
        age = (datetime.now(timezone.utc) - entry.get("_ts", datetime.now(timezone.utc))).total_seconds()
    except Exception:
        age = SHIPPING_CACHE_TTL + 1
    if age > SHIPPING_CACHE_TTL:
        SHIPPING_CACHE.pop(_normalize_ship_key(item_name), None)
        return None
    return {k: v for k, v in entry.items() if not k.startswith("_")}


def _cache_shipping(item_name: str, data: dict) -> None:
    payload = dict(data)
    payload["_ts"] = datetime.now(timezone.utc)
    SHIPPING_CACHE[_normalize_ship_key(item_name)] = payload


def _fallback_shipping_estimate(item_name: str, weight_lb: float | None) -> dict:
    """Heuristic estimate when Gemini is unavailable."""
    w = float(weight_lb) if weight_lb and weight_lb > 0 else _estimate_weight_lb_hint(item_name)
    # Rough USPS Ground Advantage-ish pricing: $4 base + ~$1/lb for small parcels
    mid = max(4.0, min(45.0, 4.0 + w * 1.2))
    return {
        "low_usd": round(mid * 0.75, 2),
        "mid_usd": round(mid, 2),
        "high_usd": round(mid * 1.6, 2),
        "carrier": "USPS",
        "service": "Ground Advantage",
        "weight_lb_estimate": round(w, 2),
        "reasoning": f"Heuristic estimate for a ~{w:.1f} lb item via USPS Ground Advantage.",
        "confidence": "low",
    }


@app.route("/api/estimate-shipping", methods=["POST"])
def api_estimate_shipping():
    """Estimate US shipping cost for an item using Gemini (USPS/UPS ground)."""
    data = request.get_json(silent=True) or {}
    item_name = (data.get("item_name") or data.get("q") or "").strip()
    if not item_name:
        return jsonify({"error": "Missing item_name"}), 400
    if len(item_name) > 200:
        item_name = item_name[:200]

    # Optional accuracy boosters
    weight_lb_raw = data.get("weight_lb", "")
    try:
        weight_lb = float(weight_lb_raw) if weight_lb_raw not in (None, "") else None
        if weight_lb is not None and (weight_lb <= 0 or weight_lb > 200):
            weight_lb = None
    except (TypeError, ValueError):
        weight_lb = None
    dimensions = (data.get("dimensions") or "").strip()[:100]

    # Server-side cache (shared across users)
    if not weight_lb and not dimensions:
        cached = _get_cached_shipping(item_name)
        if cached:
            return jsonify({"item_name": item_name, "estimate": cached, "cached": True})

    if not GEMINI_API_KEY:
        # No API key → fall back to a heuristic so the UI never breaks
        est = _fallback_shipping_estimate(item_name, weight_lb)
        return jsonify({
            "item_name": item_name,
            "estimate": est,
            "cached": False,
            "fallback": True,
            "warning": "Gemini API key not configured. Using rough weight-based estimate.",
        })

    weight_str = f"{weight_lb:.1f} lb (user-provided)" if weight_lb else (
        f"unknown — please estimate (~{_estimate_weight_lb_hint(item_name):.1f} lb hint from category)"
    )
    dims_str = dimensions if dimensions else "unknown — please estimate packed dimensions"

    prompt = SHIPPING_ESTIMATE_PROMPT.format(
        item_name=item_name,
        weight_str=weight_str,
        dims_str=dims_str,
    )

    # Structured JSON output schema
    generation_config = {
        "response_mime_type": "application/json",
        "response_schema": {
            "type": "object",
            "properties": {
                "low_usd": {"type": "number"},
                "mid_usd": {"type": "number"},
                "high_usd": {"type": "number"},
                "carrier": {"type": "string"},
                "service": {"type": "string"},
                "weight_lb_estimate": {"type": "number"},
                "reasoning": {"type": "string"},
                "confidence": {"type": "string"},
            },
            "required": [
                "low_usd", "mid_usd", "high_usd", "carrier", "service",
                "weight_lb_estimate", "reasoning", "confidence",
            ],
        },
    }

    try:
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        try:
            model = genai.GenerativeModel("gemini-2.5-flash-lite", generation_config=generation_config)
            response = model.generate_content(prompt)
        except Exception as e1:
            print(f"gemini-2.5-flash-lite failed ({e1}), trying gemini-2.5-flash...")
            model = genai.GenerativeModel("gemini-2.5-flash", generation_config=generation_config)
            response = model.generate_content(prompt)

        try:
            estimate = json.loads(response.text)
        except Exception as parse_err:
            print(f"Shipping estimate JSON parse failed: {parse_err}; raw={response.text[:200]}")
            raise parse_err

        # Sanitize numeric values
        for k in ("low_usd", "mid_usd", "high_usd"):
            try:
                v = float(estimate.get(k, 0) or 0)
            except (TypeError, ValueError):
                v = 0.0
            v = max(0.0, min(500.0, v))
            estimate[k] = round(v, 2)

        # Enforce low <= mid <= high ordering
        if estimate["high_usd"] > 0 and estimate["mid_usd"] > estimate["high_usd"]:
            estimate["mid_usd"] = estimate["high_usd"]
        if estimate["mid_usd"] < estimate["low_usd"]:
            estimate["mid_usd"] = estimate["low_usd"]

        # Weight
        try:
            w = float(estimate.get("weight_lb_estimate", 0) or 0)
        except (TypeError, ValueError):
            w = 0.0
        estimate["weight_lb_estimate"] = round(max(0.0, min(200.0, w)), 2)

        # Confidence normalization
        conf = (estimate.get("confidence") or "").strip().lower()
        if conf not in ("high", "medium", "low"):
            conf = "medium"
        estimate["confidence"] = conf

        # Strings trimmed
        for k in ("carrier", "service", "reasoning"):
            estimate[k] = str(estimate.get(k) or "").strip()[:300]

        # Cache successful result (no weight/dim overrides — those are per-request)
        if not weight_lb and not dimensions:
            _cache_shipping(item_name, estimate)

        return jsonify({"item_name": item_name, "estimate": estimate, "cached": False})

    except Exception as e:
        print(f"Shipping estimate failed: {e}")
        traceback.print_exc()
        est = _fallback_shipping_estimate(item_name, weight_lb)
        return jsonify({
            "item_name": item_name,
            "estimate": est,
            "cached": False,
            "fallback": True,
            "error": str(e),
        })


# ── Barcode Lookup ───────────────────────────────────────────────────────
@app.route("/api/barcode")
def api_barcode():
    code = request.args.get("code", "").strip()
    if not code or not re.match(r'^\d{8,14}$', code):
        return jsonify({"error": "Invalid barcode. Must be 8-14 digits."}), 400
    try:
        r = SESSION.get(f"https://api.upcitemdb.com/prod/trial/lookup?upc={code}", timeout=10)
        if r.status_code == 200:
            data = r.json()
            if data.get("items"):
                item = data["items"][0]
                return jsonify({
                    "code": code, "title": item.get("title", ""),
                    "brand": item.get("brand", ""), "category": item.get("category", ""),
                    "source": "UPCitemdb",
                })
    except Exception:
        pass
    try:
        r = SESSION.get(f"https://world.openfoodfacts.org/api/v0/product/{code}.json", timeout=10)
        if r.status_code == 200:
            data = r.json()
            if data.get("status") == 1 and data.get("product"):
                product = data["product"]
                name = product.get("product_name", "") or product.get("generic_name", "")
                brand = product.get("brands", "")
                if name:
                    return jsonify({
                        "code": code, "title": name, "brand": brand,
                        "category": product.get("categories", ""), "source": "OpenFoodFacts",
                    })
    except Exception:
        pass
    try:
        token = _get_ebay_token()
        if token:
            url = f"{EBAY_API_BASE}/buy/browse/v1/item_summary/search"
            r = SESSION.get(url, params={"q": code, "limit": "3"}, headers={"Authorization": f"Bearer {token}"}, timeout=10)
            if r.status_code == 200 and r.json().get("itemSummaries"):
                it = r.json()["itemSummaries"][0]
                title = it.get("title", "")
                if title:
                    return jsonify({
                        "code": code, "title": _extract_product_name_from_titles(r.json()["itemSummaries"], code),
                        "brand": "", "category": "eBay Search", "source": "eBay Browse API"
                    })
    except Exception:
        pass
    try:
        r = SESSION.get(f"https://www.ebay.com/sch/i.html?_nkw={code}", timeout=10)
        matches = re.findall(r'<div class="s-item__title"><span role="heading" aria-level="3"><!--F#0-->([^<]+)<!--F#1--></span>', r.text)
        if not matches:
            matches = re.findall(r'<div class="s-item__title"><span role="heading" aria-level="3">([^<]+)</span>', r.text)
        for m in matches:
            if "Shop on eBay" not in m:
                clean_title = re.sub(r'(?i)\b(NEW|FREE SHIPPING|BRAND NEW)\b', '', m).strip()
                return jsonify({
                    "code": code, "title": clean_title,
                    "brand": "", "category": "eBay Web", "source": "eBay Scraper"
                })
    except Exception:
        pass
    return jsonify({
        "code": code, "title": "", "brand": "", "category": "",
        "source": "unknown", "hint": "No product found. Try typing the item name.",
    })

# ── Photo Gallery (eBay sold images) ─────────────────────────────────────
@app.route("/api/photos")
def api_photos():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "Query required"}), 400
    condition = request.args.get("condition", "all")
    limit = min(int(request.args.get("limit", "12") or 12), 24)
    # Reuse sold-search scrape so photo/debug behavior matches the sold-listing source.
    items = _scrape_ebay_sold_fallback(q, condition, max(limit, 24))
    debug = SOLD_SOURCE_DEBUG.get(_sold_debug_key(q, condition), {})
    photos = []
    for it in items[:limit]:
        photos.append({
            "title": (it.get("title") or "")[:100],
            "price": round(it.get("price"), 2) if it.get("price") else None,
            "image": "",
            "url": it.get("url", ""),
        })
    return jsonify({
        "query": q,
        "condition": condition,
        "photos": photos,
        "ebay_url": f"https://www.ebay.com/sch/i.html?_nkw={urllib.parse.quote_plus(q)}&LH_Sold=1&LH_Complete=1&_ipg=60",
        "debug": debug,
    })

# ── eBay Seller OAuth ───────────────────────────────────────────────────
EBAY_REDIRECT_URI = os.environ.get("EBAY_REDIRECT_URI", "https://pricespy-yx00.onrender.com/api/ebay/callback")
EBAY_SELLER_OAUTH_STATE = {}

def _get_ebay_seller_token(auth_code: str) -> dict | None:
    if not EBAY_CLIENT_ID or not EBAY_CLIENT_SECRET:
        return None
    creds = base64.b64encode(f"{EBAY_CLIENT_ID}:{EBAY_CLIENT_SECRET}".encode()).decode()
    try:
        r = SESSION.post(
            EBAY_OAUTH_URL,
            headers={"Authorization": f"Basic {creds}", "Content-Type": "application/x-www-form-urlencoded"},
            data=f"grant_type=authorization_code&code={auth_code}&redirect_uri={urllib.parse.quote(EBAY_REDIRECT_URI, safe='')}",
            timeout=15,
        )
        if r.status_code == 200:
            return r.json()
        print(f"eBay seller token exchange failed: {r.status_code} {r.text[:200]}")
    except Exception as e:
        print(f"eBay seller token exchange error: {e}")
    return None

def _refresh_ebay_seller_token(refresh_token: str) -> dict | None:
    if not EBAY_CLIENT_ID or not EBAY_CLIENT_SECRET:
        return None
    creds = base64.b64encode(f"{EBAY_CLIENT_ID}:{EBAY_CLIENT_SECRET}".encode()).decode()
    try:
        r = SESSION.post(
            EBAY_OAUTH_URL,
            headers={"Authorization": f"Basic {creds}", "Content-Type": "application/x-www-form-urlencoded"},
            data=f"grant_type=refresh_token&refresh_token={refresh_token}",
            timeout=15,
        )
        if r.status_code == 200:
            return r.json()
        print(f"eBay seller token refresh failed: {r.status_code} {r.text[:200]}")
    except Exception as e:
        print(f"eBay seller token refresh error: {e}")
    return None

def _get_ebay_seller_access_token(user_id: str) -> str | None:
    """Get a valid eBay seller access token for the user, refreshing if needed."""
    sp = get_provider()
    record = sp.get_ebay_tokens(user_id)
    if not record:
        return None
    try:
        access_token = _decrypt_token(record.get("access_token_enc", ""))
        refresh_token = _decrypt_token(record.get("refresh_token_enc", ""))
        expires_at = record.get("expires_at", 0)
        if datetime.now(timezone.utc).timestamp() >= expires_at - 300:
            refreshed = _refresh_ebay_seller_token(refresh_token)
            if not refreshed:
                return None
            access_token = refreshed.get("access_token", "")
            new_expires = datetime.now(timezone.utc).timestamp() + refreshed.get("expires_in", 7200)
            sp.save_ebay_tokens(user_id, _encrypt_token(access_token), _encrypt_token(refresh_token),
                                new_expires, record.get("scope", ""))
        return access_token
    except Exception as e:
        print(f"eBay seller token retrieval failed: {e}")
    return None

@app.route("/api/ebay/auth")
def ebay_seller_auth():
    """Return the eBay seller OAuth URL. Requires user to be logged in."""
    if not EBAY_CLIENT_ID:
        return jsonify({"error": "eBay client ID not configured"}), 400
    user_id = _get_user_id_from_request()
    if not user_id:
        return jsonify({"error": "Login required"}), 401
    import secrets
    state = secrets.token_hex(16)
    EBAY_SELLER_OAUTH_STATE[state] = {"user_id": user_id, "created_at": datetime.now(timezone.utc)}
    scopes = " ".join([
        "https://api.ebay.com/oauth/api_scope",
        "https://api.ebay.com/oauth/api_scope/sell.inventory",
        "https://api.ebay.com/oauth/api_scope/sell.fulfillment",
        "https://api.ebay.com/oauth/api_scope/sell.account",
    ])
    url = (
        f"https://auth.ebay.com/oauth2/authorize"
        f"?client_id={EBAY_CLIENT_ID}"
        f"&response_type=code"
        f"&redirect_uri={urllib.parse.quote(EBAY_REDIRECT_URI, safe='')}"
        f"&scope={urllib.parse.quote(scopes, safe='')}"
        f"&state={state}"
    )
    return jsonify({"auth_url": url, "state": state})

@app.route("/api/ebay/callback")
def ebay_seller_callback():
    """Handle eBay seller OAuth callback and persist tokens."""
    auth_code = request.args.get("code", "")
    state = request.args.get("state", "")
    error = request.args.get("error", "")
    if error:
        return jsonify({"error": error}), 400
    if not auth_code or state not in EBAY_SELLER_OAUTH_STATE:
        return jsonify({"error": "Invalid callback"}), 400
    state_data = EBAY_SELLER_OAUTH_STATE.pop(state, None)
    user_id = state_data.get("user_id") if state_data else None
    if not user_id:
        return jsonify({"error": "Invalid state"}), 400
    tokens = _get_ebay_seller_token(auth_code)
    if not tokens:
        return jsonify({"error": "Failed to exchange authorization code"}), 400
    access_token = tokens.get("access_token", "")
    refresh_token = tokens.get("refresh_token", "")
    expires_in = tokens.get("expires_in", 7200)
    expires_at = datetime.now(timezone.utc).timestamp() + expires_in
    scope = " ".join(tokens.get("scope", []))
    get_provider().save_ebay_tokens(user_id, _encrypt_token(access_token), _encrypt_token(refresh_token),
                                    expires_at, scope)
    return jsonify({
        "status": "connected",
        "expires_in": expires_in,
        "token_type": tokens.get("token_type"),
        "message": "eBay seller account connected successfully.",
    })

@app.route("/api/ebay/status")
def ebay_seller_status():
    """Check if the current user has a connected eBay seller account."""
    user_id = _get_user_id_from_request()
    if not user_id:
        return jsonify({"error": "Login required"}), 401
    record = get_provider().get_ebay_tokens(user_id)
    connected = bool(record)
    expires_at = record.get("expires_at") if record else None
    return jsonify({
        "connected": connected,
        "expires_at": expires_at,
        "token_valid": _get_ebay_seller_access_token(user_id) is not None,
    })

@app.route("/api/ebay/disconnect", methods=["POST"])
def ebay_seller_disconnect():
    """Disconnect the user's eBay seller account."""
    user_id = _get_user_id_from_request()
    if not user_id:
        return jsonify({"error": "Login required"}), 401
    get_provider().delete_ebay_tokens(user_id)
    return jsonify({"status": "disconnected"})

def _ebay_seller_api_get(user_id: str, endpoint: str, params: dict = None) -> dict | None:
    """Make an authenticated GET request to an eBay seller API."""
    access_token = _get_ebay_seller_access_token(user_id)
    if not access_token:
        return None
    try:
        r = SESSION.get(
            f"{EBAY_API_BASE}{endpoint}",
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            params=params or {},
            timeout=20,
        )
        if r.status_code == 200:
            return r.json()
        print(f"eBay seller API error {r.status_code}: {r.text[:200]}")
    except Exception as e:
        print(f"eBay seller API request failed: {e}")
    return None

@app.route("/api/ebay/inventory")
def ebay_seller_inventory():
    """Get the user's eBay inventory items."""
    user_id = _get_user_id_from_request()
    if not user_id:
        return jsonify({"error": "Login required"}), 401
    data = _ebay_seller_api_get(user_id, "/sell/inventory/v1/inventory_item")
    if data is None:
        return jsonify({"error": "Could not fetch eBay inventory. Ensure eBay seller account is connected and has inventory scope."}), 400
    items = []
    for sku, item in data.get("inventoryItems", {}).items():
        items.append({
            "sku": sku,
            "title": item.get("product", {}).get("title", ""),
            "condition": item.get("condition", ""),
            "price": item.get("availability", {}).get("shipToLocationAvailability", {}).get("availabilityThreshold", 0),
            "listing": item.get("packageWeightAndSize", {}),
        })
    return jsonify({"items": items, "count": len(items)})

@app.route("/api/ebay/sold")
def ebay_seller_sold():
    """Get the user's recent eBay sold orders."""
    user_id = _get_user_id_from_request()
    if not user_id:
        return jsonify({"error": "Login required"}), 401
    limit = min(int(request.args.get("limit", "50") or 50), 200)
    data = _ebay_seller_api_get(user_id, "/sell/fulfillment/v1/order", params={"limit": limit})
    if data is None:
        return jsonify({"error": "Could not fetch eBay orders. Ensure eBay seller account is connected and has fulfillment scope."}), 400
    orders = []
    for order in data.get("orders", []):
        total = order.get("pricingSummary", {}).get("total", {})
        price = float(total.get("value", 0)) if isinstance(total, dict) else 0
        line_items = order.get("lineItems", [])
        orders.append({
            "order_id": order.get("orderId", ""),
            "title": line_items[0].get("title", "") if line_items else "",
            "status": order.get("orderFulfillmentStatus", ""),
            "price": price,
            "sold_date": order.get("creationDate", ""),
            "buyer": order.get("buyer", {}).get("username", ""),
        })
    return jsonify({"orders": orders, "count": len(orders)})

@app.route("/api/ebay/dashboard")
def ebay_seller_dashboard():
    """Aggregate seller metrics."""
    user_id = _get_user_id_from_request()
    if not user_id:
        return jsonify({"error": "Login required"}), 401
    inventory = _ebay_seller_api_get(user_id, "/sell/inventory/v1/inventory_item")
    orders = _ebay_seller_api_get(user_id, "/sell/fulfillment/v1/order", params={"limit": 200})
    inv_count = len(inventory.get("inventoryItems", {})) if inventory else 0
    sold_count = 0
    sold_revenue = 0.0
    if orders:
        for order in orders.get("orders", []):
            sold_count += 1
            total = order.get("pricingSummary", {}).get("total", {})
            try:
                sold_revenue += float(total.get("value", 0)) if isinstance(total, dict) else 0
            except Exception:
                pass
    return jsonify({
        "inventory_count": inv_count,
        "sold_count": sold_count,
        "sold_revenue": round(sold_revenue, 2),
        "connected": True,
    })

# ── eBay Marketplace Account Deletion Notification ─────────────────────
@app.route("/ebay/account-deletion", methods=["POST"])
def ebay_account_deletion():
    try:
        data = request.get_json(force=True, silent=True) or {}
        print(f"eBay account deletion notification: {data}")
    except Exception:
        pass
    return jsonify({"status": "received", "message": "Acknowledged - no user data to delete"}), 200

@app.route("/ebay/account-deletion", methods=["GET", "HEAD", "OPTIONS"])
def ebay_account_deletion_verification():
    challenge_code = request.args.get("challenge_code", "")
    verification_token = os.environ.get("EBAY_VERIFICATION_TOKEN", EBAY_VERIFICATION_TOKEN)
    endpoint_url = "https://pricespy-yx00.onrender.com/ebay/account-deletion"
    if challenge_code and verification_token:
        hash_input = challenge_code + verification_token + endpoint_url
        challenge_response = hashlib.sha256(hash_input.encode()).hexdigest()
        return jsonify({"challengeResponse": challenge_response}), 200
    return jsonify({"challengeResponse": ""}), 200

# ── Init & Register ────────────────────────────────────────────────────
init_db()
register_routes(app, _do_search, _calculate_net_profit)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    app.run(host="0.0.0.0", port=port, debug=False)
