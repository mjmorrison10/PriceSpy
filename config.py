import os

EBAY_CLIENT_ID = os.environ.get("EBAY_CLIENT_ID", "").strip()
EBAY_CLIENT_SECRET = os.environ.get("EBAY_CLIENT_SECRET", "").strip()
EBAY_OAUTH_URL = "https://api.ebay.com/identity/v1/oauth2/token"
EBAY_API_BASE = "https://api.ebay.com"
EBAY_FINDING_API = "https://svcs.ebay.com/services/search/FindingService/v1"
EBAY_REDIRECT_URI = os.environ.get("EBAY_REDIRECT_URI", "https://pricespy-yx00.onrender.com/api/ebay/callback")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
ENABLE_PRICECHARTING = os.environ.get("ENABLE_PRICECHARTING", "true").lower() == "true"
EBAY_VERIFICATION_TOKEN = os.environ.get("EBAY_VERIFICATION_TOKEN", "pricespy-ebay-notification-token-2024")

PERIOD_DAYS = {
    "1w": 7, "1m": 30, "3m": 90, "6m": 180,
    "1y": 365, "2y": 730, "3y": 1095,
    "5y": 1825, "10y": 3650,
}

# eBay Conditions
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
