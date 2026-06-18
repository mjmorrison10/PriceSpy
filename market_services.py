import concurrent.futures
from ebay_api import ebay_sold_listings, ebay_active_listings, calculate_ebay_fees
from utils import (
    tokenize, singularize, compact, compute_stats, stats_by_condition,
    filter_by_condition, generate_trend, ebay_condition_to_canonical
)
from config import EBAY_CATEGORY_FVF, EBAY_STORE_TIERS, EBAY_COND

def relevance_score(query, product_title):
    q_tokens = [singularize(t) for t in tokenize(query)]
    p_tokens = tokenize(product_title)
    if not q_tokens: return 1.0
    
    compact_query = compact(query)
    compact_title = compact(product_title)
    matched = [t for t in q_tokens if t in p_tokens or t in compact_title]
    recall = len(matched) / len(q_tokens)
    
    phrase_bonus = 0.35 if compact_query in compact_title else 0.0
    length_penalty = min(1.0, 12 / max(len(p_tokens), 1))
    return max(0.0, min(1.0, recall * 0.75 + length_penalty * 0.10 + phrase_bonus))

def is_relevant_listing(query, title):
    q_tokens = [singularize(t) for t in tokenize(query)]
    if not q_tokens: return True
    title_tokens = tokenize(title)
    compact_title = compact(title)
    matches = sum(1 for t in q_tokens if t in title_tokens or t in compact_title)
    return matches >= max(2, int(len(q_tokens) * 0.75 + 0.999))

def filter_by_relevance(items, query):
    filtered = []
    for it in items:
        if is_relevant_listing(query, it.get("title", "")):
            it["relevance"] = round(relevance_score(query, it.get("title", "")), 3)
            filtered.append(it)
    return filtered

def analyze_flip(sold_stats, active_stats, sold_items, active_items, trend,
                 condition_stats, buy_price=0.0, category="default",
                 store_tier="none", shipping_cost=0.0, promoted_rate=0.0):
    sm = sold_stats.get("median", 0) or 0
    sc = sold_stats.get("count", 0) or 0
    
    if sc == 0:
        return {"score": 0, "verdict": "❓ No Sold Data"}

    potential_buy = buy_price if buy_price > 0 else (sold_stats.get("low", 0) or sm * 0.7)
    potential_sell = sm
    
    fees = calculate_ebay_fees(potential_sell, shipping_cost, category, store_tier, promoted_rate)
    net_profit = potential_sell - potential_buy - fees["total_fees"] - shipping_cost
    margin_pct = (net_profit / potential_buy * 100) if potential_buy > 0 else 0
    
    score = 50
    if margin_pct > 30: score += 20
    elif margin_pct < 0: score -= 20
    
    return {
        "score": max(0, min(100, score)),
        "verdict": "🔥 Great Flip" if score >= 70 else "✅ Decent Flip" if score >= 50 else "🚫 Avoid",
        "potential_buy_price": round(potential_buy, 2),
        "potential_sell_price": round(potential_sell, 2),
        "net_profit": round(net_profit, 2),
        "fee_calculation": fees
    }

def do_coordinated_search(query, period_days=180, filter_condition="all", buy_price=0.0):
    # Use a thread pool for parallel API calls
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        future_sold = executor.submit(ebay_sold_listings, query, filter_condition)
        future_active = executor.submit(ebay_active_listings, query, filter_condition)
        
        sold_raw = future_sold.result()
        active_raw = future_active.result()
        
    sold_items = filter_by_relevance(sold_raw, query)
    active_items = filter_by_relevance(active_raw, query)
    
    sold_stats = compute_stats(sold_items)
    active_stats = compute_stats(active_items)
    
    trend = generate_trend(sold_stats.get("median", 0), sold_items, period_days)
    
    flip = analyze_flip(sold_stats, active_stats, sold_items, active_items, trend, {}, buy_price)
    
    return {
        "query": query,
        "sold_summary": sold_stats,
        "active_summary": active_stats,
        "recent_sold": sold_items,
        "active_listings": active_items,
        "trend": trend,
        "flip_analysis": flip,
        "data_source": "eBay (Refactored)"
    }
