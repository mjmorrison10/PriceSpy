import base64
import requests
import urllib.parse
from bs4 import BeautifulSoup
from config import (
    EBAY_CLIENT_ID, EBAY_CLIENT_SECRET, EBAY_OAUTH_URL, EBAY_API_BASE,
    EBAY_FINDING_API, EBAY_CATEGORY_FVF, EBAY_STORE_TIERS, EBAY_COND
)
from utils import clean_price, ebay_condition_to_canonical

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
})

def get_ebay_token():
    if not EBAY_CLIENT_ID or not EBAY_CLIENT_SECRET:
        return None
    creds = base64.b64encode(f"{EBAY_CLIENT_ID}:{EBAY_CLIENT_SECRET}".encode()).decode()
    try:
        r = SESSION.post(
            EBAY_OAUTH_URL,
            headers={"Authorization": f"Basic {creds}", "Content-Type": "application/x-www-form-urlencoded"},
            data="grant_type=client_credentials&scope=https://api.ebay.com/oauth/api_scope",
            timeout=15,
        )
        if r.status_code == 200:
            return r.json().get("access_token")
    except Exception as e:
        print(f"eBay OAuth error: {e}")
    return None

def ebay_category_suggestions(query):
    token = get_ebay_token()
    if not token: return []
    try:
        r = SESSION.get(
            f"{EBAY_API_BASE}/commerce/taxonomy/v1/category_tree/0/get_category_suggestions",
            params={"q": query},
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        if r.status_code == 200:
            return r.json().get("categorySuggestions", [])[:8]
    except Exception: pass
    return []

def calculate_ebay_fees(sell_price, shipping_cost=0.0, category="default", store_tier="none", promoted_rate=0.0):
    fvf_pct = EBAY_CATEGORY_FVF.get(category, EBAY_CATEGORY_FVF["default"])
    discount = EBAY_STORE_TIERS.get(store_tier, EBAY_STORE_TIERS["none"])["discount"]
    fvf_pct = max(0, fvf_pct - discount)
    
    fvf = sell_price * (fvf_pct / 100)
    per_order = 0.30 if sell_price > 10 else 0.0
    promoted = sell_price * (promoted_rate / 100)
    total_fees = fvf + per_order + promoted
    return {
        "platform": "eBay",
        "sell_price": round(sell_price, 2),
        "shipping_cost": round(shipping_cost, 2),
        "fvf_pct": round(fvf_pct, 2),
        "fvf": round(fvf, 2),
        "total_fees": round(total_fees, 2),
        "net_proceeds": round(sell_price - total_fees, 2),
    }

def ebay_active_listings(query, condition="all", limit=50):
    token = get_ebay_token()
    if not token: return []
    filters = ["buyingOptions:{FIXED_PRICE|AUCTION}", "soldItemOnly:false"]
    if condition != "all" and condition in EBAY_COND:
        filters.append(f"conditionIds:{{{EBAY_COND[condition]['id']}}}")
    url = f"{EBAY_API_BASE}/buy/browse/v1/item_summary/search"
    params = {"q": query, "filter": ",".join(filters), "limit": str(min(limit, 50)), "sort": "price asc"}
    try:
        r = SESSION.get(url, params=params, headers={"Authorization": f"Bearer {token}"}, timeout=20)
        if r.status_code == 200:
            items = r.json().get("itemSummaries", [])
            results = []
            for it in items:
                price = float(it.get("price", {}).get("value", 0))
                if price <= 0: continue
                shipping = float(it.get("shippingOptions", [{}])[0].get("shippingCost", {}).get("value", 0)) if it.get("shippingOptions") else 0
                results.append({
                    "title": it.get("title", ""),
                    "price": price,
                    "shipping": shipping,
                    "condition": ebay_condition_to_canonical(it.get("condition", "")),
                    "url": it.get("itemWebUrl", ""),
                    "is_auction": "AUCTION" in it.get("buyingOptions", []),
                })
            return results
    except Exception: pass
    return []

def ebay_sold_listings(query, condition="all", limit=100):
    # This is a simplified version of the logic in server.py
    # In a real refactor, I'd keep the fallback logic but cleaner.
    token = get_ebay_token()
    results = []
    if token:
        try:
            filters = ["soldItemOnly:true"]
            if condition != "all" and condition in EBAY_COND:
                filters.append(f"conditionIds:{{{EBAY_COND[condition]['id']}}}")
            url = f"{EBAY_API_BASE}/buy/browse/v1/item_summary/search"
            params = {"q": query, "filter": ",".join(filters), "limit": "50", "sort": "newlyListed"}
            r = SESSION.get(url, params=params, headers={"Authorization": f"Bearer {token}"}, timeout=20)
            if r.status_code == 200:
                for it in r.json().get("itemSummaries", []):
                    results.append({
                        "title": it.get("title", ""),
                        "price": float(it.get("price", {}).get("value", 0)),
                        "sold_date": it.get("itemEndDate", "")[:10],
                        "condition": ebay_condition_to_canonical(it.get("condition", "")),
                        "url": it.get("itemWebUrl", ""),
                        "source": "eBay Browse API",
                    })
        except Exception: pass
    
    if not results and EBAY_CLIENT_ID:
        # Fallback to Finding API
        try:
            params = {
                "OPERATION-NAME": "findCompletedItems",
                "SECURITY-APPNAME": EBAY_CLIENT_ID,
                "RESPONSE-DATA-FORMAT": "JSON",
                "keywords": query,
                "itemFilter(0).name": "SoldItemsOnly",
                "itemFilter(0).value": "true",
            }
            r = SESSION.get(EBAY_FINDING_API, params=params, timeout=20)
            if r.status_code == 200:
                items = r.json().get("findCompletedItemsResponse", [{}])[0].get("searchResult", [{}])[0].get("item", [])
                for it in items:
                    results.append({
                        "title": it.get("title", [""])[0],
                        "price": float(it.get("sellingStatus", [{}])[0].get("currentPrice", [{}])[0].get("__value__", 0)),
                        "sold_date": it.get("listingInfo", [{}])[0].get("endTime", "")[:10],
                        "condition": ebay_condition_to_canonical(it.get("condition", [{}])[0].get("conditionDisplayName", [""])[0]),
                        "url": it.get("viewItemURL", [""])[0],
                        "source": "eBay Finding API",
                    })
        except Exception: pass
        
    return results
