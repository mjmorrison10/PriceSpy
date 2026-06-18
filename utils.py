import re
import hashlib
import base64
from datetime import datetime, timedelta
from collections import defaultdict
from config import EBAY_COND, CONDITION_ALIASES

def clean_price(txt):
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

def compute_stats(items):
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

def stats_by_condition(items):
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

def filter_by_condition(items, target_cond):
    if not target_cond or target_cond == "all":
        return items
    return [it for it in items if it.get("condition") == target_cond]

def generate_trend(base_price, sold_items, period_days=180):
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
    return trend

def tokenize(s):
    noise = {"the", "a", "an", "of", "in", "on", "at", "to", "for", "with",
             "and", "or", "is", "are", "was", "were", "be", "been", "being",
             "it", "its", "this", "that", "these", "those", "edition", "version"}
    tokens = re.findall(r'[a-z0-9]+', s.lower())
    return {singularize(t) for t in tokens if t not in noise and len(t) > 1}

def singularize(token):
    token = (token or "").lower()
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 4 and token.endswith(("ches", "shes", "xes", "sses", "zes")):
        return token[:-2]
    if len(token) > 3 and token.endswith("s"):
        return token[:-1]
    return token

def compact(s):
    return re.sub(r'[^a-z0-9]+', '', (s or '').lower())

def ebay_condition_to_canonical(raw):
    raw = (raw or "").lower()
    for k, v in EBAY_COND.items():
        if raw in (v["ebay"].lower(), v["label"].lower(), k):
            return k
    for alias, canonical in CONDITION_ALIASES.items():
        if alias in raw:
            return canonical
    return "used"
