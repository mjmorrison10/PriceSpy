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

## eBay Browse API Setup (for real price data)

PriceSpy uses **Smart Estimates** by default, which are statistical estimates based on market baselines. To get **real eBay sold prices**, you need to configure the eBay Browse API.

### Why eBay API?

The previous scraping approach is blocked by eBay's Cloudflare protection and bot detection. The official eBay Browse API provides reliable, legal access to sold listing data.

### Setup Steps (30 min)

1. **Create eBay Developer Account**
   - Go to https://developer.ebay.com/signin
   - Create a free account if you don't have one

2. **Create an Application**
   - Go to "My Apps" → "Create App"
   - Select "Production" for live data (there's a free tier)
   - Select "Buy" for the API scope

3. **Get Your Credentials**
   - You'll receive a **Client ID** and **Client Secret**
   - Keep these secure - they're like a password

4. **Add Environment Variables**
   - `EBAY_CLIENT_ID` = your Client ID
   - `EBAY_CLIENT_SECRET` = your Client Secret

### On Render.com:
1. Go to your dashboard → Environment → Environment Variables
2. Add both `EBAY_CLIENT_ID` and `EBAY_CLIENT_SECRET`
3. Redeploy your service

### Free Tier Limits
- 5,000 API calls per day
- 10,000 API calls per month
- Plenty for personal use or small-scale flipping

### What You'll Get
Once configured, PriceSpy will show:
- "📊 Real eBay Data (N items)" badge
- Actual sold prices from eBay
- Higher confidence indicators
- No more "Smart Estimate" warnings

### Troubleshooting
- **401 errors**: Your credentials may have expired - regenerate them
- **429 rate limit**: You've hit the daily limit - wait 24 hours
- **No data returned**: Some items may not have recent sold listings on eBay
