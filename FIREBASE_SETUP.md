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
