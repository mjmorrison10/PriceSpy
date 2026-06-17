# Firebase Setup Guide — PriceSpy

## What Firebase gives you
1. Google Sign-In, cross-device sync, push notifications, trending data, Firestore

## Setup (5 min)
1. Create project at https://console.firebase.google.com
2. Enable Authentication (Google + Email/Password)
3. Create Firestore database (production mode, us-central)
4. Get web app config → paste into templates/index.html (FIREBASE_CONFIG)
5. Generate service account key → save as firebase-key.json
6. Set: export FIREBASE_CREDENTIALS=/path/to/firebase-key.json
7. Enable Cloud Messaging → copy VAPID key → paste into index.html

## Modes
- Local: SQLite + bcrypt (no Firebase needed)
- Firebase: Firestore + Firebase Auth (set FIREBASE_CREDENTIALS env var)
- Hybrid: Firebase Auth + SQLite (set Firebase config in HTML only)

## Deploy to Render
1. Add env var: FIREBASE_CREDENTIALS = paste service account JSON
2. Add env var: SECRET_KEY = random string
3. Build: pip install -r requirements.txt
4. Start: gunicorn server:app --bind 0.0.0.0:$PORT

---

## eBay API Setup (for real price data)

PriceSpy pulls **real eBay sold and active prices** using official eBay APIs. No synthetic data, no fake listings.

### How it works

PriceSpy tries APIs in this order:
1. **eBay Browse API** (OAuth) — for sold listings + active listings
2. **eBay Finding API** (App ID only) — fallback for sold listings
3. **HTML scraping** — last resort, often blocked by eBay

For best results, configure both the Browse API and the Finding API.

### Setup Steps (30 min)

1. **Create eBay Developer Account**
   - Go to https://developer.ebay.com/signin
   - Create a free account if you don't have one

2. **Create an Application**
   - Go to "My Apps" → "Create App"
   - Select **"Production"** for live data
   - Enable both API scopes:
     - **Buy → Browse API** (for sold + active listings, OAuth)
     - **Buy → Finding API** (for completed/sold listings, App ID only)
   - For seller features, also enable:
     - **Sell → Inventory API**
     - **Sell → Fulfillment API**
     - **Sell → Account API**

3. **Get Your Credentials**
   - You'll receive a **Client ID** and **Client Secret**
   - These are the same as your **App ID** and **Cert ID** for older APIs

4. **Add Environment Variables**
   - `EBAY_CLIENT_ID` = your Client ID / App ID
   - `EBAY_CLIENT_SECRET` = your Client Secret / Cert ID
   - `EBAY_REDIRECT_URI` = `https://your-domain.com/api/ebay/callback` (for seller OAuth)

### On Render.com:
1. Go to your dashboard → Environment → Environment Variables
2. Add `EBAY_CLIENT_ID`, `EBAY_CLIENT_SECRET`, and `EBAY_REDIRECT_URI`
3. Redeploy your service

### Free Tier Limits
- Browse API: 5,000+ calls per day depending on plan
- Finding API: 5,000 calls per day
- Plenty for personal use or small-scale flipping

### What You'll Get
Once configured, PriceSpy will show:
- ✅ "Real eBay Data (N items via Browse API)" badge
- ✅ Actual sold prices from eBay
- ✅ Real active listings + competition data
- ✅ eBay seller dashboard + sales analytics

### Troubleshooting
- **Sold listings return 0 but eBay.com shows sales**: The Browse API may not expose all sold items. The app automatically falls back to the Finding API. Make sure your app has **Finding API** enabled.
- **401 errors**: Your credentials may have expired - regenerate them
- **429 rate limit**: You've hit the daily limit - wait 24 hours
- **No data returned**: Some items may not have recent sold listings on eBay
