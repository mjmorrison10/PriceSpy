"""Auth, watchlist, deal history, inventory, seller intel routes for PriceSpy."""
import bcrypt, secrets, os
from functools import wraps
from datetime import datetime, timezone
from flask import g, jsonify, request
from firebase_service import get_provider, verify_firebase_id_token

_provider = None
def _get_provider():
    global _provider
    if _provider is None: _provider = get_provider()
    return _provider

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get("Authorization","").replace("Bearer ","")
        if not token: token = request.args.get("token","")
        if not token: return jsonify({"error":"Not authenticated"}), 401
        fb_user = verify_firebase_id_token(token)
        if fb_user: g.user_id = fb_user["uid"]; return f(*args, **kwargs)
        uid = _get_provider().validate_session(token)
        if not uid: return jsonify({"error":"Session expired"}), 401
        g.user_id = uid; return f(*args, **kwargs)
    return decorated

def register_routes(app, do_search_fn):
    app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))

    # ═══ AUTH ═══
    @app.route("/api/auth/register", methods=["POST"])
    def register():
        d = request.get_json(force=True,silent=True) or {}
        email = (d.get("email") or "").strip().lower()
        pw = (d.get("password") or "").strip()
        name = (d.get("display_name") or email.split("@")[0]).strip()
        if not email or "@" not in email or len(pw) < 6:
            return jsonify({"error":"Valid email + password (6+ chars) required"}), 400
        sp = _get_provider()
        if sp.get_user_by_email(email): return jsonify({"error":"Account exists"}), 409
        h = bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()
        user = sp.create_user(email, h, name)
        token = sp.create_session(user["id"])
        return jsonify({"token":token,"user":user})

    @app.route("/api/auth/login", methods=["POST"])
    def login():
        d = request.get_json(force=True,silent=True) or {}
        email = (d.get("email") or "").strip().lower()
        pw = (d.get("password") or "").strip()
        sp = _get_provider()
        u = sp.get_user_by_email(email)
        if not u or not bcrypt.checkpw(pw.encode(), u["password_hash"].encode()):
            return jsonify({"error":"Invalid credentials"}), 401
        token = sp.create_session(u["id"])
        return jsonify({"token":token,"user":{"id":u["id"],"email":u["email"],"display_name":u.get("display_name",email)}})

    @app.route("/api/auth/firebase", methods=["POST"])
    def auth_firebase():
        d = request.get_json(force=True,silent=True) or {}
        id_token = (d.get("id_token") or "").strip()
        if not id_token: return jsonify({"error":"Firebase ID token required"}), 400
        fb_user = verify_firebase_id_token(id_token)
        if not fb_user: return jsonify({"error":"Invalid Firebase token"}), 401
        sp = _get_provider()
        uid = fb_user["uid"]; email = fb_user["email"]; name = fb_user.get("name", email.split("@")[0] if email else "User")
        if not sp.get_user_by_id(uid):
            if email: existing = sp.get_user_by_email(email)
            if not email or not existing: sp.create_user(email, "", name, google_id=fb_user.get("uid"))
            else: uid = existing["id"]
        token = sp.create_session(uid)
        return jsonify({"token":token,"user":{"id":uid,"email":email,"display_name":name}})

    @app.route("/api/auth/me")
    @require_auth
    def me():
        u = _get_provider().get_user_by_id(g.user_id)
        return jsonify(u) if u else (jsonify({"error":"Not found"}), 404)

    @app.route("/api/auth/logout", methods=["POST"])
    @require_auth
    def logout():
        t = request.headers.get("Authorization","").replace("Bearer ","") or request.args.get("token","")
        if t: _get_provider().delete_session(t)
        return jsonify({"ok":True})

    # ═══ WATCHLIST ═══
    @app.route("/api/watchlist")
    @require_auth
    def watchlist(): return jsonify(_get_provider().get_watchlist(g.user_id))

    @app.route("/api/watchlist", methods=["POST"])
    @require_auth
    def watchlist_add():
        d = request.get_json(force=True,silent=True) or {}
        q = (d.get("query") or "").strip()
        if not q: return jsonify({"error":"Query required"}), 400
        sp = _get_provider()
        try: r = do_search_fn(q, 180, "6m", d.get("condition","all"), float(d.get("buy_price",0) or 0))
        except Exception: r = None
        data = {"query":q,"condition":d.get("condition","all"),"buy_price":float(d.get("buy_price",0) or 0),
                "platform":d.get("platform","ebay"),"shipping_cost":float(d.get("shipping",0) or 0),
                "median":r["sold_summary"]["median"] if r else 0,"low":r["sold_summary"]["low"] if r else 0,
                "high":r["sold_summary"]["high"] if r else 0,"score":r["flip_analysis"]["score"] if r else 0}
        rid = sp.add_watchlist_item(g.user_id, data)
        return jsonify({"message":"Added","id":rid,"prices":{"median":data["median"],"low":data["low"],"high":data["high"],"score":data["score"]}})

    @app.route("/api/watchlist/<item_id>", methods=["DELETE"])
    @require_auth
    def watchlist_del(item_id): _get_provider().delete_watchlist_item(item_id, g.user_id); return jsonify({"ok":True})

    # ═══ DEAL HISTORY ═══
    @app.route("/api/deal-history")
    @require_auth
    def deal_history(): return jsonify(_get_provider().get_deal_history(g.user_id))

    @app.route("/api/deal-history", methods=["POST"])
    @require_auth
    def deal_history_add():
        d = request.get_json(force=True,silent=True) or {}
        _get_provider().add_deal_history(g.user_id, d); return jsonify({"ok":True})

    # ═══ ALERTS ═══
    @app.route("/api/alerts")
    @require_auth
    def alerts(): return jsonify(_get_provider().get_alerts(g.user_id))

    @app.route("/api/alerts/read-all", methods=["POST"])
    @require_auth
    def alerts_read(): _get_provider().mark_alerts_read(g.user_id); return jsonify({"ok":True})

    # ═══ TRENDING ═══
    @app.route("/api/trending")
    def trending(): return jsonify(_get_provider().get_trending_searches(20))

    @app.route("/api/record-search", methods=["POST"])
    def record_search():
        d = request.get_json(force=True,silent=True) or {}
        q = (d.get("query") or "").strip()
        if q: _get_provider().record_search(q, d.get("category",""))
        return jsonify({"ok":True})

    # ═══ PUSH ═══
    @app.route("/api/push-token", methods=["POST"])
    @require_auth
    def push_token():
        d = request.get_json(force=True,silent=True) or {}
        pt = (d.get("push_token") or "").strip()
        if pt: _get_provider().record_search(f"__push__{g.user_id}", f"push:{pt}")
        return jsonify({"ok":True})

    # ═══ INVENTORY TRACKER (Change #8) ═══
    @app.route("/api/inventory")
    @require_auth
    def inventory():
        return jsonify(_get_provider().get_inventory(g.user_id))

    @app.route("/api/inventory", methods=["POST"])
    @require_auth
    def inventory_add():
        d = request.get_json(force=True,silent=True) or {}
        rid = _get_provider().add_inventory_item(g.user_id, d)
        return jsonify({"ok":True,"id":rid})

    @app.route("/api/inventory/<item_id>", methods=["PUT"])
    @require_auth
    def inventory_update(item_id):
        _get_provider().update_inventory_item(item_id, g.user_id, request.get_json(force=True,silent=True) or {})
        return jsonify({"ok":True})

    @app.route("/api/inventory/<item_id>", methods=["DELETE"])
    @require_auth
    def inventory_delete(item_id):
        _get_provider().delete_inventory_item(item_id, g.user_id)
        return jsonify({"ok":True})

    @app.route("/api/inventory/stats")
    @require_auth
    def inventory_stats():
        return jsonify(_get_provider().get_inventory_stats(g.user_id))

    # ═══ LOT CALCULATOR (Change #9) ═══
    @app.route("/api/lot-calculate", methods=["POST"])
    def lot_calculate():
        d = request.get_json(force=True,silent=True) or {}
        items = d.get("items",[])
        platform = d.get("platform","ebay")
        try: shipping = float(d.get("shipping_per_item","0") or 0)
        except: shipping = 0
        results = []; total_cost = 0; total_profit = 0; total_market = 0
        for item in items:
            name = (item.get("name") or "").strip()
            price = float(item.get("price",0) or 0)
            if not name or price <= 0: continue
            total_cost += price
            try:
                r = do_search_fn(name, 180, "6m", "all", price, platform, shipping)
                fc = r.get("flip_analysis",{}).get("fee_calculation",{})
                net = fc.get("net_profit",0)
                total_profit += net; total_market += r["sold_summary"]["median"]
                results.append({"name":name,"cost":price,"market_median":r["sold_summary"]["median"],
                               "net_profit":net,"flip_score":r["flip_analysis"]["score"],
                               "verdict":"BUY" if net>0 else "LEAVE"})
            except Exception: results.append({"name":name,"cost":price,"error":"search failed"})
        if total_profit > 0: lot_verdict, lot_color = "🔥 BUY THE LOT", "green"
        elif total_profit > -total_cost*0.1: lot_verdict, lot_color = "🤔 NEGOTIATE", "amber"
        else: lot_verdict, lot_color = "🚫 PASS", "red"
        return jsonify({"items":results,"total_cost":round(total_cost,2),"total_profit":round(total_profit,2),
                       "total_market_value":round(total_market,2),"verdict":lot_verdict,
                       "verdict_color":lot_color,"item_count":len(results)})

    # ═══ MARKET TIMING (Change #10) ═══
    SEASONAL = {
        "toys":{1:.4,2:.3,3:.3,4:.4,5:.5,6:.5,7:.4,8:.5,9:.6,10:.7,11:.9,12:1.0},
        "electronics":{1:.6,2:.5,3:.6,4:.7,5:.8,6:.7,7:.6,8:.9,9:.8,10:.7,11:1.0,12:.9},
        "sneakers":{1:.7,2:.7,3:.6,4:.7,5:.6,6:.5,7:.5,8:.8,9:.8,10:.7,11:.8,12:1.0},
        "gaming":{1:.8,2:.7,3:.6,4:.6,5:.5,6:.4,7:.4,8:.5,9:.6,10:.7,11:.9,12:1.0},
        "vehicles":{1:.5,2:.5,3:.7,4:.9,5:1.0,6:.9,7:.8,8:.7,9:.6,10:.5,11:.4,12:.4},
        "fashion":{1:.7,2:.6,3:.7,4:.8,5:.7,6:.5,7:.4,8:.5,9:.7,10:.8,11:.9,12:1.0},
        "home":{1:.8,2:.7,3:.8,4:.9,5:.9,6:.8,7:.6,8:.7,9:.7,10:.7,11:.8,12:.9},
        "general":{1:.6,2:.6,3:.7,4:.7,5:.7,6:.6,7:.5,8:.6,9:.7,10:.7,11:.8,12:.9},
    }

    def _scat(cat):
        cl = cat.lower()
        if any(k in cl for k in ["game","console","trading card","nintendo","playstation","xbox","pokemon"]): return "gaming"
        if any(k in cl for k in ["sneaker","shoe","jordan","nike"]): return "sneakers"
        if any(k in cl for k in ["vehicle","car","truck","motorcycle"]): return "vehicles"
        if any(k in cl for k in ["phone","laptop","electronic","camera","audio"]): return "electronics"
        if any(k in cl for k in ["toy","lego","building"]): return "toys"
        if any(k in cl for k in ["fashion","luxury","clothing","watch"]): return "fashion"
        if any(k in cl for k in ["home","appliance","dyson","kitchen"]): return "home"
        return "general"

    @app.route("/api/market-timing")
    def market_timing():
        cat = request.args.get("category","general").strip()
        scat = _scat(cat)
        data = SEASONAL.get(scat, SEASONAL["general"])
        mn = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
        months = [{"month":mn[i-1],"demand":data[i]} for i in range(1,13)]
        cm = datetime.now(timezone.utc).month
        cd = data.get(cm,.5); mx = max(data,key=data.get); mi = min(data,key=data.get)
        sv = "✅ Good time to sell" if cd>=.8 else ("📊 Average time" if cd>=.6 else "⏳ Wait to sell")
        sd = f"Demand is {'high' if cd>=.8 else ('moderate' if cd>=.6 else 'low')} in {mn[cm-1]}. Best selling month: {mn[mx-1]}."
        bv = "✅ Great time to BUY" if cd<=.5 else ("⚠️ Expensive to buy" if cd>=.8 else "📊 OK to buy")
        bd = "Low demand = low prices. Stock up now." if cd<=.5 else ("High demand = high prices." if cd>=.8 else "Moderate prices.")
        return jsonify({"category":scat,"months":months,"current_month":mn[cm-1],"current_demand":round(cd,2),
                       "best_sell_month":mn[mx-1],"best_buy_month":mn[mi-1],
                       "sell_verdict":sv,"sell_desc":sd,"buy_verdict":bv,"buy_desc":bd})

    # ═══ SELLER INTEL (Change #11) ═══
    @app.route("/api/seller-intel")
    def seller_intel():
        q = request.args.get("q","").strip()
        if not q: return jsonify({"error":"Query required"}), 400
        try: r = do_search_fn(q, 180, "6m", "all", 0, "ebay", 0)
        except Exception: return jsonify({"error":"Search failed"}), 500
        active = r.get("active_listings",[]); sold = r.get("recent_sold",[])
        sat = r.get("saturation",{})
        ap = sorted([it["price"] for it in active if it.get("price")])
        sp_ = sorted([it["price"] for it in sold if it.get("price")])
        am = ap[len(ap)//2] if ap else 0; sm = sp_[len(sp_)//2] if sp_ else 0
        spread = round(ap[3*len(ap)//4]-ap[len(ap)//4],2) if len(ap)>=5 else 0
        ats = sat.get("active_sold_ratio",1)
        if ats<1: mt,ml,md = "seller_market","Seller's Market","More buyers than sellers. Price at high end."
        elif ats<3: mt,ml,md = "balanced","Balanced Market","Healthy competition. Price at median."
        else: mt,ml,md = "buyer_market","Buyer's Market","More sellers than buyers. Price competitively."
        if am>sm*1.1: pa = "⚠️ Sellers overpricing. List at or below sold median."
        elif am<sm*.9: pa = "✅ Active prices below sold. Room to price higher."
        else: pa = "📊 Active prices align with sold. Fair market."
        return jsonify({"query":q,"active_count":len(active),"sold_count":len(sold),
                       "active_median":round(am,2),"sold_median":round(sm,2),
                       "price_spread":spread,"market_type":mt,"market_label":ml,"market_desc":md,
                       "price_advice":pa,"condition_gaps":r.get("opportunity",{}).get("condition_gaps",[]),
                       "active_to_sold_ratio":round(ats,1)})


    # ═══ BULK PRICE (Change 1) ═══
    @app.route("/api/bulk-price", methods=["POST"])
    def bulk_price():
        d = request.get_json(force=True,silent=True) or {}
        items = d.get("items",[])
        platform = d.get("platform","ebay")
        try: shipping = float(d.get("shipping_per_item","0") or 0)
        except: shipping = 0.0
        if not items: return jsonify({"error":"No items"}),400
        results = []; total_cost = 0; total_profit = 0
        for item in items[:50]:
            name = (item.get("name") or "").strip()
            price = float(item.get("price",0) or 0)
            if not name or price <= 0: continue
            total_cost += price
            try:
                r = do_search_fn(name,180,"6m","all",price,platform,shipping)
                fc = r.get("flip_analysis",{}).get("fee_calculation",{})
                net = fc.get("net_profit",0); total_profit += net
                results.append({"name":name,"cost":price,"market_median":r["sold_summary"]["median"],"net_profit":net,"flip_score":r["flip_analysis"]["score"],"verdict":"BUY" if net>0 else "LEAVE"})
            except Exception: results.append({"name":name,"cost":price,"error":"failed"})
        return jsonify({"results":results,"total_cost":round(total_cost,2),"total_profit":round(total_profit,2),"total_items":len(results)})

    # ═══ COMPETITOR LANDSCAPE (Change 3) ═══
    @app.route("/api/competitor-landscape")
    def competitor_landscape():
        q = request.args.get("q","").strip()
        if not q: return jsonify({"error":"Query required"}),400
        try: r = do_search_fn(q,180,"6m","all",0,"ebay",0)
        except: return jsonify({"error":"Search failed"}),500
        active = r.get("active_listings",[]); sold = r.get("recent_sold",[])
        cond_prices = {}
        for it in active:
            c = it.get("condition","unknown"); p = it.get("price",0)
            if c not in cond_prices: cond_prices[c] = []
            if p > 0: cond_prices[c].append(p)
        cond_summary = {}
        for c, prices in cond_prices.items():
            if not prices: continue
            prices.sort()
            cond_summary[c] = {"count":len(prices),"median":round(prices[len(prices)//2],2),"low":round(prices[0],2),"high":round(prices[-1],2)}
        sp = sorted(active, key=lambda x: x.get("price",0))
        low3 = [{"title":it["title"][:60],"price":it["price"]} for it in sp[:3]]
        hi3 = [{"title":it["title"][:60],"price":it["price"]} for it in sp[-3:]]
        days = r["flip_analysis"].get("liquidity",{}).get("avg_days_to_sell",30) if "liquidity" in r.get("flip_analysis",{}) else 30
        return jsonify({"query":q,"total_active":len(active),"total_sold":len(sold),"condition_summary":cond_summary,"lowest_3":low3,"highest_3":hi3,"avg_days_to_sell":round(days,1)})

    # ═══ TRUE ROI (Change 4) ═══
    @app.route("/api/true-roi", methods=["POST"])
    def true_roi():
        d = request.get_json(force=True,silent=True) or {}
        buy = float(d.get("buy_price",0) or 0); sell = float(d.get("sell_price",0) or 0)
        pl = d.get("platform","ebay"); gas = float(d.get("gas",0) or 0)
        storage = float(d.get("storage",0) or 0); hrs = float(d.get("hours_spent",0) or 0)
        rate = float(d.get("hourly_rate",35) or 35); mats = float(d.get("shipping_materials",0) or 0)
        tax = float(d.get("tax_rate",25) or 25)
        if not buy or not sell: return jsonify({"error":"Buy and sell price required"}),400
        fc = _calculate_net_profit(sell,buy,pl,mats)
        net = fc["net_profit"]
        hidden = gas + storage + (hrs * rate)
        true_net = net - hidden
        tax_amt = max(0, true_net * (tax/100))
        final = true_net - tax_amt
        mgn = (final/buy*100) if buy>0 else 0
        return jsonify({"buy_price":round(buy,2),"sell_price":round(sell,2),"platform_fees":fc["total_fees"],"net_after_fees":round(net,2),"hidden_costs":round(hidden,2),"true_net":round(true_net,2),"tax_amount":round(tax_amt,2),"final_net":round(final,2),"final_margin":round(mgn,1),"verdict":"Profitable" if final>0 else "Losing money"})

    # ═══ DASHBOARD (Change 6) ═══
    @app.route("/api/dashboard")
    @require_auth
    def dashboard():
        sp = _get_provider()
        deals = sp.get_deal_history(g.user_id)
        inv_s = sp.get_inventory_stats(g.user_id)
        td = len(deals)
        bd = [d for d in deals if d.get("verdict")=="BUY"]
        tb = sum(d.get("your_price",0) or 0 for d in bd)
        tn = sum(d.get("net_profit",0) or 0 for d in deals)
        avg = sum(d.get("flip_score",0) or 0 for d in deals)/max(td,1)
        cats = {}
        for d in deals:
            n = d.get("item_name","").lower()
            if any(k in n for k in ["nintendo","playstation","xbox"]): c = "Gaming"
            elif any(k in n for k in ["iphone","samsung","phone"]): c = "Phones"
            elif any(k in n for k in ["nike","jordan","sneaker"]): c = "Sneakers"
            elif any(k in n for k in ["car","toyota","ford","honda"]): c = "Vehicles"
            else: c = "General"
            cats[c] = cats.get(c,0)+1
        return jsonify({"total_deals":td,"total_invested":round(tb,2),"total_net_profit":round(tn,2),"total_roi":round((tn/tb*100),1) if tb>0 else 0,"avg_flip_score":round(avg,1),"inventory":inv_s,"categories":cats})

    # ═══ PLATFORM OPTIMIZER (Change 7) ═══
    @app.route("/api/platform-optimize")
    def platform_optimize():
        q = request.args.get("q","").strip()
        bp = float(request.args.get("buy_price","0") or 0)
        if not q: return jsonify({"error":"Query required"}),400
        platforms = ["ebay","mercari","poshmark","facebook","local"]
        results = []
        for pl in platforms:
            try:
                r = do_search_fn(q,180,"6m","all",bp,pl,0)
                fc = r["flip_analysis"]["fee_calculation"]
                liq = r["flip_analysis"].get("liquidity",{})
                results.append({"platform":PLATFORM_FEES[pl]["name"],"platform_key":pl,"sell_price":fc["sell_price"],"net_profit":fc["net_profit"],"net_margin":fc["net_margin_pct"],"days_to_sell":round(liq.get("avg_days_to_sell",30),1),"recommended":False})
            except: pass
        results.sort(key=lambda x: x["net_profit"], reverse=True)
        if results: results[0]["recommended"] = True
        return jsonify({"query":q,"buy_price":bp,"platforms":results})

    # ═══ WHAT'S HOT (Change 8) ═══
    @app.route("/api/whats-hot")
    def whats_hot():
        sp = _get_provider()
        trending = sp.get_trending_searches(30)
        hot = []
        for it in trending:
            if it.get("count",0) < 3: continue
            try:
                r = do_search_fn(it["query"],180,"1m","all",0,"ebay",0)
                vt = r["flip_analysis"]["liquidity"]["volume_trend"] if "liquidity" in r.get("flip_analysis",{}) else "stable"
                hot.append({"query":it["query"],"watchers":it.get("count",0),"market_median":r["sold_summary"]["median"],"direction":r["direction"],"volume_trend":vt,"flip_score":r["flip_analysis"]["score"]})
            except: hot.append({"query":it["query"],"watchers":it.get("count",0),"market_median":0,"direction":"stable","volume_trend":"stable","flip_score":0})
        return jsonify(hot[:15])

    # ═══ JOURNAL NOTES (Change 9) ═══
    @app.route("/api/inventory/<item_id>/notes", methods=["PUT"])
    @require_auth
    def inventory_notes(item_id):
        d = request.get_json(force=True,silent=True) or {}
        _get_provider().update_inventory_item(item_id, g.user_id, {"notes": d.get("notes","")})
        return jsonify({"ok":True})

    # ═══ SHARE DEAL (Change 10) ═══
    @app.route("/api/share-deal", methods=["POST"])
    def share_deal():
        d = request.get_json(force=True,silent=True) or {}
        q = d.get("query",""); c = d.get("condition","all")
        bp = float(d.get("buy_price",0) or 0); pl = d.get("platform","ebay")
        if not q: return jsonify({"error":"Query required"}),400
        try: r = do_search_fn(q,180,"6m",c,bp,pl,0)
        except: return jsonify({"error":"Search failed"}),500
        sid = secrets.token_hex(8)
        if not hasattr(app,'shared_deals'): app.shared_deals = {}
        app.shared_deals[sid] = r
        return jsonify({"share_id":sid,"share_url":f"/api/shared-deal/{sid}","summary":{"query":q,"median":r["sold_summary"]["median"],"flip_score":r["flip_analysis"]["score"],"verdict":r["flip_analysis"]["verdict"]}})

    @app.route("/api/shared-deal/<sid>")
    def get_shared_deal(sid):
        if not hasattr(app,'shared_deals') or sid not in app.shared_deals:
            return jsonify({"error":"Not found"}),404
        return jsonify(app.shared_deals[sid])

    print("auth_routes.py loaded successfully")
