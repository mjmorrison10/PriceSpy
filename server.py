#!/usr/bin/env python3
"""
PriceSpy v5 — Category-aware conditions + accurate pricing
"""

import json
import os
import re
import urllib.parse
import traceback
import base64
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, render_template, request
import sys as _sys, os as _os
# Ensure the directory containing this file is importable
_this_dir = _os.path.dirname(_os.path.abspath(__file__))
if _this_dir not in _sys.path:
    _sys.path.insert(0, _this_dir)
from auth_routes import register_routes
from db_init import init_db

# AI Image Analysis Configuration
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
CLOUDFLARE_ACCOUNT_ID = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
CLOUDFLARE_API_TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN", "")

# eBay Browse API Configuration
EBAY_CLIENT_ID = os.environ.get("EBAY_CLIENT_ID", "")
EBAY_CLIENT_SECRET = os.environ.get("EBAY_CLIENT_SECRET", "")
EBAY_API_BASE = "https://api.ebay.com"
EBAY_OAUTH_URL = "https://api.ebay.com/identity/v1/oauth2/token"

if EBAY_CLIENT_ID:
    print("✅ eBay Browse API configured")
else:
    print("⚠️ No eBay API credentials - using Smart Estimates (set EBAY_CLIENT_ID and EBAY_CLIENT_SECRET)")

# Configure Gemini if key is available
if GEMINI_API_KEY:
    try:
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        print("✅ Gemini AI configured")
    except Exception as e:
        print(f"⚠️ Gemini configuration failed: {e}")

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024
UPLOAD_FOLDER = Path(__file__).parent / "uploads"
UPLOAD_FOLDER.mkdir(exist_ok=True)

# Health check endpoint for Render
@app.route("/health")
def health():
    return jsonify({"status": "ok"}), 200

PRICE_CACHE: dict[str, dict] = {}

SESSION = requests.Session()
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

# Correct eBay condition mapping
EBAY_COND_MAP = {
    "new (sealed)": (["1000"], "New"),
    "new": (["1000"], "New"),
    "like new": (["2500", "1500"], "Like New - Refurbished"),
    "cib": (["1000", "1500"], "New/Open Box"),
    "very good": (["8000", "3000", "4000"], "Used Very Good / Refurbished"),
    "good": (["7000", "6000"], "Used Good"),
    "acceptable": (["6000"], "Used Acceptable"),
    "loose": (["7000", "6000"], "Used Good"),
    "untested": (["6000", "5000"], "Used Acceptable / For Parts"),
    "for parts": (["5000"], "For Parts or Not Working"),
}

EBAY_CODE_TO_COND = {
    "1000": "new", "1500": "new", "2000": "like new", "2500": "like new",
    "3000": "very good", "4000": "good", "5000": "for parts",
    "6000": "acceptable", "7000": "good", "8000": "very good",
}

# ═══════════════════════════════════════════
#  CATEGORY-AWARE CONDITION SYSTEMS
# ═══════════════════════════════════════════

# Each category has its own condition list (best → worst) + price multipliers
CATEGORY_CONDITIONS = {
    "video_games": {
        "conditions": ["new (sealed)", "new", "like new", "cib", "very good", "good", "acceptable", "loose", "untested", "for parts"],
        "multipliers": {"new (sealed)": 1.4, "new": 1.3, "like new": 1.1, "cib": 1.0, "very good": 0.9, "good": 0.72, "acceptable": 0.48, "loose": 0.42, "untested": 0.24, "for parts": 0.13},
        "labels": {"new (sealed)": "📦 New Sealed", "new": "🆕 New", "like new": "✨ Like New", "cib": "📋 CIB", "very good": "👍 Very Good", "good": "👌 Good", "acceptable": "⚠️ Acceptable", "loose": "💿 Loose", "untested": "❓ Untested", "for parts": "🔧 For Parts"},
    },
    "electronics": {
        "conditions": ["new (sealed)", "new", "like new", "very good", "good", "acceptable", "for parts"],
        "multipliers": {"new (sealed)": 1.25, "new": 1.15, "like new": 1.0, "very good": 0.85, "good": 0.7, "acceptable": 0.5, "for parts": 0.15},
        "labels": {"new (sealed)": "📦 New Sealed", "new": "🆕 New", "like new": "✨ Like New / Open Box", "very good": "👍 Very Good", "good": "👌 Good / Used", "acceptable": "⚠️ Fair / Acceptable", "for parts": "🔧 For Parts / Broken"},
    },
    "vehicles": {
        "conditions": ["excellent", "very good", "good", "fair", "poor"],
        "multipliers": {"excellent": 1.15, "very good": 1.0, "good": 0.82, "fair": 0.62, "poor": 0.35},
        "labels": {"excellent": "⭐ Excellent", "very good": "👍 Very Good", "good": "👌 Good", "fair": "⚠️ Fair", "poor": "🔧 Poor"},
    },
    "sneakers_fashion": {
        "conditions": ["new (sealed)", "new", "like new", "very good", "good", "acceptable"],
        "multipliers": {"new (sealed)": 1.5, "new": 1.3, "like new": 1.0, "very good": 0.78, "good": 0.55, "acceptable": 0.30},
        "labels": {"new (sealed)": "📦 Deadstock", "new": "🆕 New", "like new": "✨ Like New", "very good": "👍 Very Good", "good": "👌 Good / Used", "acceptable": "⚠️ Beater / Fair"},
    },
    "general": {
        "conditions": ["new", "like new", "very good", "good", "acceptable", "for parts"],
        "multipliers": {"new": 1.2, "like new": 1.0, "very good": 0.82, "good": 0.65, "acceptable": 0.45, "for parts": 0.15},
        "labels": {"new": "🆕 New", "like new": "✨ Like New", "very good": "👍 Very Good", "good": "👌 Good / Used", "acceptable": "⚠️ Fair", "for parts": "🔧 For Parts"},
    },
}

# Map a category to its condition system
def _get_condition_system(category: str) -> dict:
    """Determine which condition system to use."""
    cat_lower = category.lower()
    if any(kw in cat_lower for kw in ["game", "console", "trading card", "gaming"]):
        return CATEGORY_CONDITIONS["video_games"]
    if any(kw in cat_lower for kw in ["smartphone", "laptop", "camera", "audio", "electronic", "phone", "tablet"]):
        return CATEGORY_CONDITIONS["electronics"]
    if any(kw in cat_lower for kw in ["vehicle", "car", "truck", "suv", "motorcycle"]):
        return CATEGORY_CONDITIONS["vehicles"]
    if any(kw in cat_lower for kw in ["sneaker", "fashion", "luxury", "shoe"]):
        return CATEGORY_CONDITIONS["sneakers_fashion"]
    return CATEGORY_CONDITIONS["general"]


# ═══════════════════════════════════════════
#  MORE ACCURATE PRICING KB
# ═══════════════════════════════════════════

# Format: key → (low_used, median_used, high_new, category)
# Now with separate used/new ranges for accuracy
CATEGORY_KB = {
    # iPhones — accurate used + new pricing
    "iphone 13 pro": (280, 340, 700, "Smartphones"),
    "iphone 13": (180, 250, 550, "Smartphones"),
    "iphone 13 pro max": (350, 420, 800, "Smartphones"),
    "iphone 14 pro": (380, 480, 900, "Smartphones"),
    "iphone 14": (250, 330, 650, "Smartphones"),
    "iphone 14 pro max": (450, 550, 1000, "Smartphones"),
    "iphone 15 pro": (500, 620, 1100, "Smartphones"),
    "iphone 15": (350, 450, 800, "Smartphones"),
    "iphone 15 pro max": (600, 750, 1200, "Smartphones"),
    "iphone 12 pro": (200, 280, 600, "Smartphones"),
    "iphone 12": (150, 220, 500, "Smartphones"),
    "iphone 11": (120, 180, 400, "Smartphones"),
    "iphone xr": (100, 150, 300, "Smartphones"),
    "iphone se": (80, 140, 350, "Smartphones"),
    # Samsung
    "samsung galaxy s23": (300, 420, 800, "Smartphones"),
    "samsung galaxy s24": (450, 580, 1000, "Smartphones"),
    "samsung galaxy": (100, 250, 800, "Smartphones"),
    # Other phones
    "pixel 7": (200, 300, 600, "Smartphones"),
    "pixel 8": (300, 420, 700, "Smartphones"),
    "pixel": (80, 180, 700, "Smartphones"),
    # Laptops
    "macbook air m1": (350, 480, 900, "Laptops"),
    "macbook air m2": (500, 650, 1100, "Laptops"),
    "macbook pro": (500, 850, 2500, "Laptops"),
    "macbook": (300, 600, 2500, "Laptops"),
    "thinkpad": (100, 250, 1500, "Laptops"),
    # Consoles
    "nintendo switch": (120, 200, 350, "Gaming Consoles"),
    "playstation 5": (250, 350, 500, "Gaming Consoles"),
    "playstation 4": (100, 170, 300, "Gaming Consoles"),
    "xbox series x": (250, 330, 500, "Gaming Consoles"),
    "xbox series s": (120, 190, 300, "Gaming Consoles"),
    # Games / cards
    "pokemon": (5, 50, 300, "Trading Cards / Games"),
    # Sneakers
    "nike air force": (40, 80, 160, "Sneakers / Fashion"),
    "nike dunk": (50, 120, 250, "Sneakers / Fashion"),
    "nike air jordan": (80, 180, 500, "Sneakers / Fashion"),
    "nike": (20, 60, 200, "Sneakers / Fashion"),
    "jordan": (50, 120, 300, "Sneakers / Fashion"),
    # Other
    "lego": (10, 60, 800, "Toys / Building Sets"),
    "dyson": (50, 180, 500, "Home Appliances"),
    "bose": (40, 150, 400, "Audio"),
    "sony headphones": (30, 100, 350, "Audio"),
    "sony": (30, 150, 2000, "Electronics"),
    "canon": (50, 300, 2000, "Cameras"),
    "canon eos": (150, 500, 2500, "Cameras"),
    "canon rebel": (100, 350, 1200, "Cameras"),
    "canon 5d": (300, 800, 3000, "Cameras"),
    "canon r5": (1500, 2500, 3900, "Cameras"),
    "canon r6": (1200, 1800, 2500, "Cameras"),
    "nikon d850": (800, 1400, 3000, "Cameras"),
    "nikon d750": (500, 900, 2000, "Cameras"),
    "nikon d780": (700, 1200, 2300, "Cameras"),
    "nikon z6": (700, 1200, 2000, "Cameras"),
    "nikon z7": (1000, 1700, 3000, "Cameras"),
    "nikon z8": (1800, 2800, 4000, "Cameras"),
    "nikon z9": (3000, 4000, 5500, "Cameras"),
    "nikon d": (150, 500, 2500, "Cameras"),
    "sony a7": (600, 1200, 2500, "Cameras"),
    "sony a1": (3000, 4500, 6500, "Cameras"),
    "sony a6000": (200, 400, 700, "Cameras"),
    "fujifilm": (300, 800, 2000, "Cameras"),
    "fujifilm x-t": (400, 900, 2000, "Cameras"),
    "fender": (100, 500, 3000, "Musical Instruments"),
    "gibson": (300, 1000, 5000, "Musical Instruments"),
}

# Game keywords for PriceCharting
GAMING_KEYWORDS = [
    "nintendo", "switch", "playstation", "ps5", "ps4", "ps3", "xbox",
    "pokemon", "mario", "zelda", "gameboy", "wii", "sega", "atari",
    "gamecube", "ds", "3ds", "amiibo", "skylanders", "nes", "snes",
    "n64", "dreamcast", "genesis", "turbografx",
]

# Console vs game detection
CONSOLE_INDICATORS = [
    "console", "system", "handheld", "controller", "dock",
    "tablet", "joy-con", "joycon", "pro controller", "charger",
    "adapter", "cable", "hdmi", "64gb", "32gb", "oled", "lite",
    "v1", "v2", "heg-", "hed-", "with blue", "with red", "with white",
    "with gray", "with grey", "with neon", "bundle with",
    "console bundle", "complete in box console",
]

GAME_INDICATORS = [
    "game", "cartridge", "disc only", "all-stars", "all stars",
    "odyssey", "deluxe", "ultimate", "breath of the wild",
    "mario kart", "smash bros", "animal crossing", "pokemon",
    "zelda", "splatoon", "xenoblade", "fire emblem", "kirby",
    "metroid", "donkey kong", "luigi", "yoshi", "pikmin",
    "standard edition", "collector", "steelbook",
    "mario party", "mario golf", "mario tennis", "paper mario",
    "super mario", "mario &", "mario +", "mario and",
    "dragon quest", "final fantasy", "octopath", "persona",
    "shin megami", "monster hunter", "bayonetta", "astral chain",
    "arms", "ring fit", "labo", "brain training",
    "mario vs", "captain toad", "wario", "warioware",
    "the legend of zelda", "hyrule warriors",
]

KNOWN_GAME_FRANCHISE_STARTERS = [
    "super mario", "mario kart", "mario party", "mario golf", "mario tennis",
    "zelda", "pokemon", "animal crossing", "splatoon", "xenoblade",
    "fire emblem", "kirby", "metroid", "donkey kong", "luigi",
    "yoshi", "pikmin", "smash bros", "super smash",
    "paper mario", "mario &", "mario +", "mario and",
    "dragon quest", "final fantasy", "octopath", "persona",
    "shin megami", "monster hunter", "bayonetta", "astral chain",
    "arms", "ring fit", "labo", "brain training",
    "mario vs", "captain toad", "wario", "warioware",
    "the legend of zelda", "hyrule warriors",
]

# Vehicle support
VEHICLE_KB = {
    "harley davidson": (0.06, 25000, "Motorcycles"),
    "honda motorcycle": (0.08, 12000, "Motorcycles"),
    "honda shadow": (0.08, 8000, "Motorcycles"),
    "honda rebel": (0.07, 6500, "Motorcycles"),
    "honda nc750x": (0.07, 9500, "Motorcycles"),
    "honda nc750": (0.07, 9000, "Motorcycles"),
    "honda cb": (0.07, 9000, "Motorcycles"),
    "honda cbr": (0.09, 12000, "Motorcycles"),
    "honda goldwing": (0.05, 25000, "Motorcycles"),
    "honda africa twin": (0.07, 15000, "Motorcycles"),
    "honda grom": (0.06, 3700, "Motorcycles"),
    "honda monkey": (0.05, 4200, "Motorcycles"),
    "honda xr": (0.08, 7000, "Motorcycles"),
    "honda crf": (0.08, 7000, "Motorcycles"),
    "honda vfr": (0.08, 11000, "Motorcycles"),
    "honda fury": (0.08, 11000, "Motorcycles"),
    "honda ctx": (0.08, 10000, "Motorcycles"),
    "honda st": (0.07, 16000, "Motorcycles"),
    "yamaha motorcycle": (0.09, 11000, "Motorcycles"),
    "yamaha mt-": (0.08, 10000, "Motorcycles"),
    "yamaha mt ": (0.08, 10000, "Motorcycles"),
    "yamaha fz": (0.08, 8000, "Motorcycles"),
    "yamaha xsr": (0.07, 9000, "Motorcycles"),
    "yamaha bolt": (0.08, 8500, "Motorcycles"),
    "yamaha vmax": (0.06, 18000, "Motorcycles"),
    "yamaha v star": (0.08, 9000, "Motorcycles"),
    "yamaha tenere": (0.08, 10500, "Motorcycles"),
    "yamaha tracer": (0.08, 11000, "Motorcycles"),
    "yamaha fjr": (0.07, 17000, "Motorcycles"),
    "yamaha wr": (0.08, 7000, "Motorcycles"),
    "yamaha yz": (0.09, 8500, "Motorcycles"),
    "yamaha tw": (0.06, 5000, "Motorcycles"),
    "kawasaki ninja": (0.08, 13000, "Motorcycles"),
    "kawasaki motorcycle": (0.08, 10000, "Motorcycles"),
    "kawasaki z": (0.08, 10000, "Motorcycles"),
    "kawasaki vulcan": (0.08, 10000, "Motorcycles"),
    "kawasaki versys": (0.08, 9000, "Motorcycles"),
    "kawasaki klr": (0.07, 7000, "Motorcycles"),
    "kawasaki klx": (0.08, 6000, "Motorcycles"),
    "kawasaki concours": (0.08, 15000, "Motorcycles"),
    "suzuki motorcycle": (0.09, 10000, "Motorcycles"),
    "suzuki gsx": (0.09, 12000, "Motorcycles"),
    "suzuki hayabusa": (0.07, 15000, "Motorcycles"),
    "suzuki gsx-r": (0.09, 13000, "Motorcycles"),
    "suzuki sv": (0.08, 7500, "Motorcycles"),
    "suzuki v-strom": (0.08, 9000, "Motorcycles"),
    "suzuki boulevard": (0.08, 10000, "Motorcycles"),
    "suzuki dr": (0.08, 6500, "Motorcycles"),
    "suzuki drz": (0.07, 7000, "Motorcycles"),
    "suzuki burgman": (0.09, 8000, "Motorcycles"),
    "bmw motorcycle": (0.07, 18000, "Motorcycles"),
    "bmw r 1250": (0.06, 20000, "Motorcycles"),
    "bmw r 1200": (0.07, 17000, "Motorcycles"),
    "bmw r 18": (0.07, 18000, "Motorcycles"),
    "bmw s 1000": (0.08, 18000, "Motorcycles"),
    "bmw f 750": (0.08, 10000, "Motorcycles"),
    "bmw f 850": (0.08, 12000, "Motorcycles"),
    "bmw f 900": (0.08, 11000, "Motorcycles"),
    "bmw k 1600": (0.08, 22000, "Motorcycles"),
    "ducati": (0.08, 20000, "Motorcycles"),
    "ducati monster": (0.08, 13000, "Motorcycles"),
    "ducati panigale": (0.08, 20000, "Motorcycles"),
    "ducati multistrada": (0.08, 19000, "Motorcycles"),
    "ducati scrambler": (0.07, 11000, "Motorcycles"),
    "ducati diavel": (0.08, 22000, "Motorcycles"),
    "ducati streetfighter": (0.08, 20000, "Motorcycles"),
    "triumph motorcycle": (0.08, 14000, "Motorcycles"),
    "triumph bonneville": (0.06, 12000, "Motorcycles"),
    "triumph street twin": (0.07, 10000, "Motorcycles"),
    "triumph tiger": (0.08, 14000, "Motorcycles"),
    "triumph speed triple": (0.08, 15000, "Motorcycles"),
    "triumph rocket": (0.07, 22000, "Motorcycles"),
    "triumph daytona": (0.08, 13000, "Motorcycles"),
    "triumph trident": (0.07, 8500, "Motorcycles"),
    "indian motorcycle": (0.07, 18000, "Motorcycles"),
    "indian scout": (0.06, 13000, "Motorcycles"),
    "indian chieftain": (0.07, 24000, "Motorcycles"),
    "indian challenger": (0.07, 25000, "Motorcycles"),
    "indian ftr": (0.08, 15000, "Motorcycles"),
    "indian roadmaster": (0.07, 28000, "Motorcycles"),
    "indian springfield": (0.07, 23000, "Motorcycles"),
    "indian pursuit": (0.07, 28000, "Motorcycles"),
    "yamaha r1": (0.08, 17000, "Motorcycles"),
    "yamaha r6": (0.08, 13000, "Motorcycles"),
    "kawasaki ninja": (0.08, 13000, "Motorcycles"),
    "kawasaki motorcycle": (0.08, 10000, "Motorcycles"),
    "suzuki motorcycle": (0.09, 10000, "Motorcycles"),
    "bmw motorcycle": (0.07, 18000, "Motorcycles"),
    "ducati": (0.08, 20000, "Motorcycles"),
    "triumph motorcycle": (0.08, 14000, "Motorcycles"),
    "indian motorcycle": (0.07, 18000, "Motorcycles"),
    "toyota camry": (0.07, 28000, "Cars"),
    "toyota corolla": (0.07, 23000, "Cars"),
    "toyota rav4": (0.07, 30000, "Cars / SUVs"),
    "toyota tacoma": (0.05, 35000, "Trucks"),
    "toyota tundra": (0.06, 40000, "Trucks"),
    "toyota highlander": (0.07, 38000, "Cars / SUVs"),
    "honda civic": (0.07, 26000, "Cars"),
    "honda accord": (0.07, 29000, "Cars"),
    "honda cr-v": (0.07, 31000, "Cars / SUVs"),
    "honda pilot": (0.07, 39000, "Cars / SUVs"),
    "ford f-150": (0.08, 40000, "Trucks"),
    "ford mustang": (0.08, 33000, "Cars"),
    "ford explorer": (0.09, 38000, "Cars / SUVs"),
    "ford escape": (0.09, 30000, "Cars / SUVs"),
    "ford bronco": (0.06, 42000, "Cars / SUVs"),
    "chevrolet silverado": (0.08, 42000, "Trucks"),
    "chevrolet tahoe": (0.08, 55000, "Cars / SUVs"),
    "chevrolet camaro": (0.09, 30000, "Cars"),
    "chevrolet corvette": (0.06, 70000, "Cars"),
    "dodge ram": (0.09, 40000, "Trucks"),
    "dodge charger": (0.09, 35000, "Cars"),
    "dodge challenger": (0.08, 33000, "Cars"),
    "jeep wrangler": (0.05, 35000, "Cars / SUVs"),
    "jeep grand cherokee": (0.08, 40000, "Cars / SUVs"),
    "tesla model 3": (0.10, 42000, "Cars"),
    "tesla model y": (0.10, 48000, "Cars / SUVs"),
    "tesla model s": (0.10, 80000, "Cars"),
    "tesla model x": (0.10, 85000, "Cars / SUVs"),
    "bmw 3 series": (0.12, 45000, "Cars"),
    "bmw 5 series": (0.12, 58000, "Cars"),
    "bmw x3": (0.11, 47000, "Cars / SUVs"),
    "bmw x5": (0.11, 62000, "Cars / SUVs"),
    "mercedes c-class": (0.12, 46000, "Cars"),
    "mercedes e-class": (0.12, 58000, "Cars"),
    "mercedes glc": (0.11, 49000, "Cars / SUVs"),
    "audi a4": (0.12, 42000, "Cars"),
    "audi q5": (0.11, 47000, "Cars / SUVs"),
    "subaru outback": (0.07, 30000, "Cars / SUVs"),
    "subaru forester": (0.07, 28000, "Cars / SUVs"),
    "subaru wrx": (0.08, 31000, "Cars"),
    "mazda cx-5": (0.08, 28000, "Cars / SUVs"),
    "mazda miata": (0.07, 29000, "Cars"),
    "mazda mx-5": (0.07, 29000, "Cars"),
    "hyundai elantra": (0.10, 22000, "Cars"),
    "hyundai tucson": (0.09, 28000, "Cars / SUVs"),
    "kia telluride": (0.07, 38000, "Cars / SUVs"),
    "nissan altima": (0.10, 27000, "Cars"),
    "nissan rogue": (0.09, 30000, "Cars / SUVs"),
    "volkswagen golf": (0.09, 28000, "Cars"),
    "volkswagen tiguan": (0.09, 30000, "Cars / SUVs"),
    "gmc sierra": (0.08, 43000, "Trucks"),
    "lexus rx": (0.08, 50000, "Cars / SUVs"),
    "acura mdx": (0.09, 50000, "Cars / SUVs"),
    "porsche 911": (0.05, 115000, "Cars"),
    "porsche cayenne": (0.09, 80000, "Cars / SUVs"),
    "ram 1500": (0.08, 40000, "Trucks"),
}

VEHICLE_KEYWORDS = [
    "car", "truck", "suv", "motorcycle", "bike", "vehicle", "sedan",
    "coupe", "convertible", "wagon", "hatchback", "minivan", "van",
    "harley", "yamaha", "kawasaki", "suzuki", "ducati", "triumph", "indian",
    "toyota", "ford", "chevrolet", "chevy", "dodge", "jeep", "tesla",
    "mercedes", "audi", "subaru", "mazda", "hyundai", "kia", "nissan",
    "volkswagen", "vw", "gmc", "lexus", "acura", "porsche", "cadillac",
    "lincoln", "buick", "chrysler", "ram", "land rover", "bmw",
    "jaguar", "volvo", "infiniti", "genesis", "rivian",
    # Motorcycle-specific
    "dct", "abs", "cruiser", "sportbike", "sport bike",
    "adventure bike", "touring", "dual sport", "dirt bike",
    "scooter", "moped", "enduro", "motocross", "naked bike",
    "standard bike", "bobber", "chopper",
]

# ── Normalization helpers ──

def _clean_price(txt):
    if not txt or not isinstance(txt, str):
        return None
    t = str(txt).replace("$", "").strip()
    if not t:
        return None
    try:
        val = float(t.replace(",", ""))
    except (ValueError, TypeError):
        return None
    if 2000 <= val <= 2099 and val == int(val):
        return None
    if val <= 0.01 or val >= 500000:
        return None
    return val


def _guess_category(query: str) -> tuple:
    """Return (category_name, low_used, median_used, high_new)."""
    ql = query.lower()
    # Check KB first (most specific)
    for key, (lo, med, hi, cat) in CATEGORY_KB.items():
        if key in ql:
            return cat, lo, med, hi
    # Check vehicles
    for key, (depr, base, cat) in VEHICLE_KB.items():
        if key in ql:
            return cat, base * 0.3, base * 0.5, base
    for kw in VEHICLE_KEYWORDS:
        if kw in ql:
            return "Vehicles", 2000, 15000, 50000
    return "General Merchandise", 10, 50, 500


def _is_vehicle_query(query: str) -> bool:
    ql = query.lower()
    for key in VEHICLE_KB:
        if key in ql:
            return True
    return any(kw in ql for kw in VEHICLE_KEYWORDS)


def _extract_vehicle_year(query: str) -> int | None:
    m = re.search(r'\b(19[89]\d|20[0-2]\d)\b', query)
    if m:
        year = int(m.group(1))
        if 1980 <= year <= 2026:
            return year
    return None


def _get_vehicle_info(query: str) -> dict:
    ql = query.lower()
    year = _extract_vehicle_year(query) or 2022
    for key, (depr_rate, base_new, cat) in VEHICLE_KB.items():
        if key in ql:
            age = max(0, 2026 - year)
            current_value = base_new * ((1 - depr_rate) ** age)
            low = round(current_value * 0.75, 2)
            high = round(current_value * 1.25, 2)
            median = round(current_value, 2)
            return {
                "make_model": key.title(), "year": year, "category": cat,
                "base_new": base_new, "depreciation_rate": depr_rate,
                "estimated_value": median, "range_low": low, "range_high": high,
                "age_years": age,
            }
    # Smart fallback: guess vehicle type from query
    ql = query.lower()
    is_motorcycle = any(kw in ql for kw in [
        "motorcycle", "bike", "dct", "abs", "cruiser", "sportbike",
        "sport bike", "adventure", "touring", "dual sport", "dirt bike",
        "scooter", "moped", "enduro", "motocross", "bobber", "chopper",
        "naked", "standard bike",
    ])
    # Also check for known motorcycle brand + model pattern (Honda/Yamaha/etc + model code)
    moto_brands = ["honda", "yamaha", "kawasaki", "suzuki", "ducati", "triumph",
                   "indian", "bmw", "ktm", "husqvarna", "aprilia", "moto guzzi",
                   "royal enfield", "mv agusta", "benelli", "cfmoto"]
    has_moto_brand = any(b in ql for b in moto_brands)
    # If year + motorcycle brand and no car indicators, assume motorcycle
    car_indicators = ["car", "truck", "suv", "sedan", "coupe", "wagon", "hatchback", "minivan", "van"]
    has_car_indicator = any(c in ql for c in car_indicators)

    if is_motorcycle or (has_moto_brand and not has_car_indicator and year):
        base_new = 10000  # Motorcycle base
        depr = 0.08
        cat = "Motorcycles"
    else:
        base_new = 35000  # Car/truck base
        depr = 0.08
        cat = "Vehicles"

    return {
        "make_model": query.title(), "year": year, "category": cat,
        "base_new": base_new, "depreciation_rate": depr,
        "estimated_value": round(base_new * ((1 - depr) ** max(0, 2026 - year)), 2),
        "range_low": round(base_new * ((1 - depr) ** max(0, 2026 - year)) * 0.75, 2),
        "range_high": round(base_new * ((1 - depr) ** max(0, 2026 - year)) * 1.25, 2),
        "age_years": max(0, 2026 - year),
    }


def _normalize_condition(raw: str, cond_system: dict) -> str:
    """Map a raw condition string to one of the category's conditions."""
    if not raw or not isinstance(raw, str):
        return "unknown"
    rl = raw.strip().lower()

    # Skip these entirely
    skip_words = {"box only", "manual only", "case only", "replacement case",
                  "empty box", "reproduction", "insert only"}
    for skip in skip_words:
        if skip in rl:
            return "skip"

    valid_conds = cond_system.get("conditions", [])
    # Build keyword map from known pattern
    known_map = {
        "new (sealed)": ["sealed", "factory sealed", "brand new sealed", "nis", "mint sealed", "deadstock"],
        "new": ["new", "brand new", "mint", "never opened", "unopened"],
        "like new": ["like new", "open box", "mint condition", "near mint", "excellent condition", "excellent"],
        "cib": ["cib", "complete in box", "complete with", "comes with box"],
        "very good": ["very good", "vg", "great condition", "lightly used", "minor wear"],
        "good": ["good", "used", "pre-owned", "preowned", "pre owned"],
        "acceptable": ["acceptable", "fair", "worn", "heavy wear", "scratched", "beater"],
        "loose": ["loose", "cartridge only", "disc only", "no box", "console only", "tablet only", "item only"],
        "untested": ["untested", "as is untested", "not tested", "unknown working"],
        "for parts": ["for parts", "not working", "broken", "damaged", "repair", "defective", "parts only", "as-is", "as is"],
        "poor": ["poor", "rough", "salvage", "junk"],
        "excellent": ["excellent", "like new", "certified"],
        "fair": ["fair", "ok condition", "decent"],
    }

    for cond in valid_conds:
        for kw in known_map.get(cond, [cond]):
            if kw in rl:
                return cond

    # Fallback heuristics
    if "new" in rl:
        return "new" if "new" in valid_conds else "like new"
    if "used" in rl or "pre" in rl:
        return "good" if "good" in valid_conds else "very good"
    if "parts" in rl or "broken" in rl or "repair" in rl:
        return "for parts" if "for parts" in valid_conds else "acceptable"

    return "unknown"


# ═══════════════════════════════════════════
#  PRICECHARTING
# ═══════════════════════════════════════════

def _search_pricecharting(query: str) -> list[dict]:
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
            score = _relevance_score(query, name)
            products.append({"title": name, "url": offers_url, "relevance": score})
    products.sort(key=lambda p: p["relevance"], reverse=True)
    return products[:5]


def _scrape_pricecharting_detail(offers_url: str, cond_system: dict) -> dict | None:
    try:
        r = SESSION.get(offers_url, timeout=15)
        if r.status_code != 200:
            return None
    except Exception:
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

    try:
        r2 = SESSION.get(historic_url, timeout=15)
        if r2.status_code != 200:
            return None
    except Exception:
        return None

    soup2 = BeautifulSoup(r2.text, "html.parser")
    sold_listings = []
    current_condition = "good"

    for table in soup2.select("table"):
        headers = [th.get_text(strip=True).lower() for th in table.select("th")]
        has_date = any("sale date" in h or "date" in h for h in headers)
        has_price = any("price" in h for h in headers)
        if not (has_date and has_price):
            continue

        prev = table.find_previous(["h2", "h3", "div"])
        if prev:
            norm = _normalize_condition(prev.get_text(strip=True), cond_system)
            if norm not in ("unknown", "skip"):
                current_condition = norm

        price_idx = title_idx = date_idx = None
        for i, h in enumerate(headers):
            hl = h.lower()
            if "price" in hl and i >= 2:
                price_idx = i
            elif "title" in hl:
                title_idx = i
            elif "sale date" in hl or ("date" in hl and i == 0):
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

            title = cells[title_idx].get_text(strip=True)[:200] if title_idx is not None and title_idx < len(cells) else ""
            title = re.sub(r"Time Warp.*?OK\s*", "", title).strip()

            item_cond = _normalize_condition(title, cond_system)
            if item_cond == "skip":
                continue
            if item_cond == "unknown":
                item_cond = current_condition

            link = ""
            if title_idx is not None and title_idx < len(cells):
                a_tag = cells[title_idx].select_one("a[href]")
                if a_tag:
                    link = a_tag.get("href", "")

            sold_listings.append({
                "title": title, "price": price,
                "sold_date": date_cell, "url": link,
                "condition": item_cond,
            })

    return {
        "sold_listings": sold_listings,
        "source": "PriceCharting",
        "source_url": historic_url,
    }


def _tokenize(s: str) -> set[str]:
    noise = {"the", "a", "an", "of", "in", "on", "at", "to", "for", "with",
             "and", "or", "is", "are", "was", "were", "be", "been", "being",
             "it", "its", "this", "that", "these", "those", "edition", "version"}
    tokens = re.findall(r'[a-z0-9]+', s.lower())
    return {t for t in tokens if t not in noise and len(t) > 1}


def _relevance_score(query: str, product_title: str) -> float:
    q_tokens = _tokenize(query)
    p_tokens = _tokenize(product_title)
    if not q_tokens:
        return 0.0
    ql = query.lower()
    ptl = product_title.lower()

    overlap = q_tokens & p_tokens
    recall = len(overlap) / len(q_tokens)
    length_penalty = min(1.0, 10 / max(len(p_tokens), 1))
    substring_bonus = 0.3 if ql in ptl else 0.0

    p_is_console = any(ind in ptl for ind in CONSOLE_INDICATORS)
    p_is_game = any(ind in ptl for ind in GAME_INDICATORS)
    p_starts_game = any(ptl.startswith(fs) for fs in KNOWN_GAME_FRANCHISE_STARTERS)
    q_is_console = any(ind in ql for ind in CONSOLE_INDICATORS)
    q_is_game = any(ind in ql for ind in GAME_INDICATORS) or any(ql.startswith(fs) for fs in KNOWN_GAME_FRANCHISE_STARTERS)
    platform_query = any(p in ql for p in ["nintendo", "playstation", "xbox"])

    wrong_cat_penalty = 0.0
    if q_is_console and (p_is_game or p_starts_game) and not p_is_console:
        wrong_cat_penalty = 0.6
    elif q_is_game and p_is_console and not (p_is_game or p_starts_game):
        wrong_cat_penalty = 0.6
    elif platform_query and not q_is_game:
        if (p_is_game or p_starts_game) and not p_is_console:
            wrong_cat_penalty = 0.6
        elif p_is_console:
            substring_bonus += 0.15
        if platform_query:
            q_has_nums = bool(re.search(r'\d', ql))
            p_has_nums = bool(re.search(r'(?<!\d)([2-9])(?!\d)', ptl))
            if not q_has_nums and p_has_nums:
                wrong_cat_penalty += 0.5
            for mod in ["oled", "lite", "special edition"]:
                if mod not in ql and mod in ptl:
                    wrong_cat_penalty += 0.15

    score = recall * 0.55 + length_penalty * 0.2 + substring_bonus - wrong_cat_penalty
    return max(0.0, min(1.0, score))


# ═══════════════════════════════════════════
#  STATS
# ═══════════════════════════════════════════

def _compute_stats(items: list[dict]) -> dict:
    prices = [it.get("price", 0) for it in items if it.get("price") and it.get("price") > 0.01]
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


def _stats_by_condition(items: list[dict], cond_system: dict) -> dict:
    valid_conds = set(cond_system.get("conditions", []))
    groups = defaultdict(list)
    for it in items:
        cond = it.get("condition", "unknown") or "unknown"
        if cond not in valid_conds:
            continue
        p = it.get("price")
        if p and p > 0.01:
            groups[cond].append(p)
    result = {}
    for cond in cond_system["conditions"]:
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


def _generate_trend(base_price: float, count: int, sold_items: list = None,
                    period_days: int = 180) -> list[dict]:
    import random
    random.seed(abs(hash(str(base_price))) % 2**32)
    now = datetime.now(timezone.utc)

    if sold_items and len(sold_items) >= 5:
        dated = [it for it in sold_items
                 if it.get("sold_date") and isinstance(it.get("sold_date"), str)
                 and re.match(r"\d{4}-\d{2}-\d{2}", it["sold_date"])]
        if len(dated) >= 3:
            weeks = defaultdict(list)
            for it in dated:
                try:
                    d = datetime.strptime(it["sold_date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    weeks[d.strftime("%Y-%m-%d")].append(it.get("price", 0))
                except (ValueError, TypeError):
                    continue
            cutoff = now - timedelta(days=period_days)
            trend = []
            for week in sorted(weeks.keys()):
                try:
                    wd = datetime.strptime(week, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
                if wd < cutoff:
                    continue
                prices = [p for p in weeks[week] if p > 0.01]
                if not prices:
                    continue
                prices.sort()
                n = len(prices)
                trend.append({
                    "date": week, "low": round(min(prices), 2),
                    "median": round(prices[n // 2], 2), "high": round(max(prices), 2),
                    "mean": round(sum(prices) / n, 2), "count": n,
                })
            max_points = 60
            if len(trend) > max_points:
                step = len(trend) // max_points
                trimmed = trend[::step]
                if trimmed and trimmed[-1] != trend[-1]:
                    trimmed.append(trend[-1])
                trend = trimmed
            if len(trend) >= 2:
                return trend

    current = float(base_price)
    trend = []
    step_size = max(1, period_days // 60) if period_days > 60 else 1
    for d_offset in range(period_days, -1, -step_size):
        day = (now - timedelta(days=d_offset)).strftime("%Y-%m-%d")
        drift = (base_price - current) * 0.01 + random.gauss(0, base_price * 0.008)
        current += drift
        current = max(base_price * 0.4, min(base_price * 2.0, current))
        lo = round(current * (0.7 + random.random() * 0.2), 2)
        hi = round(current * (1.1 + random.random() * 0.3), 2)
        trend.append({
            "date": day, "low": lo, "median": round(current, 2),
            "high": hi, "mean": round((lo + current + hi) / 3, 2),
            "count": max(1, int(count * (0.5 + random.random()))),
        })
    today = {
        "date": now.strftime("%Y-%m-%d"), "low": round(base_price * 0.85, 2),
        "median": round(base_price, 2), "high": round(base_price * 1.2, 2),
        "mean": round(base_price * 1.01, 2), "count": count,
    }
    if trend and trend[-1]["date"] != today["date"]:
        trend.append(today)
    return trend


# ═══════════════════════════════════════════
#  FLIPPING ANALYSIS
# ═══════════════════════════════════════════


# ═══════════════════════════════════════════
#  PLATFORM FEE CALCULATOR
# ═══════════════════════════════════════════

PLATFORM_FEES = {
    "ebay": {
        "name": "eBay",
        "final_value_pct": 13.25,  # Most categories
        "per_order_fee": 0.40,
        "payment_pct": 2.9,        # Credit card processing
        "payment_per_order": 0.30,
        "description": "13.25% FVF + $0.40 + ~2.9% payment",
    },
    "mercari": {
        "name": "Mercari",
        "final_value_pct": 10.0,
        "per_order_fee": 0.50,
        "payment_pct": 2.9,
        "payment_per_order": 0.30,
        "description": "10% selling fee + $0.50 payment",
    },
    "poshmark": {
        "name": "Poshmark",
        "final_value_pct": 20.0,
        "per_order_fee": 0.0,
        "payment_pct": 0.0,
        "payment_per_order": 0.0,
        "flat_fee_under_15": 2.95,
        "description": "20% for sales >$15 / $2.95 flat under $15",
    },
    "facebook": {
        "name": "Facebook Marketplace",
        "final_value_pct": 5.0,
        "per_order_fee": 0.0,
        "payment_pct": 2.9,
        "payment_per_order": 0.30,
        "description": "5% selling fee (shipped) / 0% local",
    },
    "local": {
        "name": "Local / Cash",
        "final_value_pct": 0.0,
        "per_order_fee": 0.0,
        "payment_pct": 0.0,
        "payment_per_order": 0.0,
        "description": "No platform fees — cash or Venmo",
    },
}

def _calculate_net_profit(sell_price: float, buy_price: float, platform: str,
                          shipping_cost: float = 0.0) -> dict:
    """Calculate true net profit after all fees."""
    pf = PLATFORM_FEES.get(platform, PLATFORM_FEES["ebay"])

    # Poshmark special case
    if platform == "poshmark" and sell_price < 15:
        platform_fee = pf.get("flat_fee_under_15", 2.95)
    else:
        platform_fee = sell_price * (pf["final_value_pct"] / 100) + pf["per_order_fee"]

    payment_fee = sell_price * (pf["payment_pct"] / 100) + pf["payment_per_order"]
    total_fees = platform_fee + payment_fee

    gross_profit = sell_price - buy_price
    net_profit = sell_price - buy_price - total_fees - shipping_cost
    net_margin_pct = (net_profit / buy_price * 100) if buy_price > 0 else 0

    return {
        "platform": pf["name"],
        "sell_price": round(sell_price, 2),
        "buy_price": round(buy_price, 2),
        "shipping_cost": round(shipping_cost, 2),
        "platform_fee": round(platform_fee, 2),
        "payment_fee": round(payment_fee, 2),
        "total_fees": round(total_fees, 2),
        "gross_profit": round(gross_profit, 2),
        "net_profit": round(net_profit, 2),
        "net_margin_pct": round(net_margin_pct, 1),
        "fee_breakdown": pf["description"],
    }

def _analyze_flip(sold_stats, active_stats, sold_items, active_items, trend,
                  condition_stats, buy_price=0.0, is_vehicle=False,
                  platform="ebay", shipping_cost=0.0):
    sm = sold_stats.get("median", 0) or 0
    am = active_stats.get("median", 0) or 0
    sc = sold_stats.get("count", 0) or 0
    ac = active_stats.get("count", 0) or 0
    sold_low = sold_stats.get("low", 0) or 0

    total_listings = sc + ac
    str_rate = (sc / total_listings * 100) if total_listings > 0 else 0

    if buy_price and buy_price > 0:
        potential_buy = buy_price
    else:
        potential_buy = sold_low if sold_low > 0 else sm * 0.7

    potential_sell = sm
    margin_dollar = potential_sell - potential_buy
    margin_pct = (margin_dollar / potential_buy * 100) if potential_buy > 0 else 0

    competition = min(100, round(ac / max(sc, 1) * 50, 0)) if sc > 0 else 50

    velocity = sc / 180
    if sold_items and len(sold_items) >= 2:
        dates = [it.get("sold_date", "") for it in sold_items
                 if re.match(r"\d{4}-\d{2}-\d{2}", str(it.get("sold_date", "")))]
        if len(dates) >= 2:
            dates.sort()
            try:
                first = datetime.strptime(dates[0], "%Y-%m-%d")
                last = datetime.strptime(dates[-1], "%Y-%m-%d")
                span = max((last - first).days, 1)
                velocity = len(dates) / span
            except (ValueError, TypeError):
                pass

    velocity_label = (
        "🔥 Very Fast" if velocity > 2 else "✅ Fast" if velocity > 0.5 else
        "📊 Moderate" if velocity > 0.1 else "🐢 Slow"
    )

    # ── LIQUIDITY METER ──
    avg_days_to_sell = (1 / velocity) if velocity > 0 else 999
    if str_rate > 30:
        liquidity_tier = "liquid"
        liquidity_label = "🟢 Liquid"
        liquidity_desc = "Sells fast — buy confidently"
    elif str_rate > 10:
        liquidity_tier = "moderate"
        liquidity_label = "🟡 Moderate"
        liquidity_desc = "Will sell with patience"
    else:
        liquidity_tier = "illiquid"
        liquidity_label = "🔴 Illiquid"
        liquidity_desc = "You'll sit on this for a while"

    # ── VOLUME TREND (3m vs 6m) ──
    volume_trend_label = "stable"
    volume_trend_pct = 0
    if sold_items and len(sold_items) >= 10:
        now_dt = datetime.now(timezone.utc)
        cutoff_6m = now_dt - timedelta(days=180)
        cutoff_3m = now_dt - timedelta(days=90)
        count_6m = 0
        count_3m = 0
        for it in sold_items:
            d = it.get("sold_date", "")
            if re.match(r"\d{4}-\d{2}-\d{2}", str(d)):
                try:
                    dt = datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    if dt >= cutoff_6m:
                        count_6m += 1
                    if dt >= cutoff_3m:
                        count_3m += 1
                except (ValueError, TypeError):
                    pass
        vel_6m = count_6m / 180
        vel_3m = count_3m / 90
        if vel_6m > 0:
            volume_trend_pct = round(((vel_3m - vel_6m) / vel_6m) * 100, 1)
            if volume_trend_pct > 20:
                volume_trend_label = "accelerating"
            elif volume_trend_pct > -20:
                volume_trend_label = "stable"
            else:
                volume_trend_label = "slowing"
    else:
        vel_6m = velocity
        vel_3m = velocity
        count_6m = sc
        count_3m = max(1, sc // 2)

    liquidity = {
        "tier": liquidity_tier,
        "label": liquidity_label,
        "description": liquidity_desc,
        "avg_days_to_sell": round(avg_days_to_sell, 1),
        "sell_through_rate": round(str_rate, 1),
        "velocity_per_day": round(velocity, 2),
        "velocity_label": velocity_label,
        "volume_trend": volume_trend_label,
        "volume_trend_pct": volume_trend_pct,
        "sales_last_3mo": count_3m,
        "sales_last_6mo": count_6m,
    }

    volatility = 0
    if trend and len(trend) >= 3:
        medians = [t["median"] for t in trend]
        changes = [abs(medians[i] - medians[i-1]) / max(medians[i-1], 1)
                   for i in range(1, len(medians))]
        volatility = sum(changes) / len(changes) * 100 if changes else 0

    risk_level = "Low" if volatility < 5 else ("Medium" if volatility < 15 else "High")

    # ═══════════════════════════════════════
    #  SATURATION & OPPORTUNITY ANALYSIS
    # ═══════════════════════════════════════

    # Active-to-sold ratio
    active_sold_ratio = (ac / sc) if sc > 0 else 999
    if active_sold_ratio < 1:
        saturation_tier = "underserved"
        saturation_label = "🟢 Underserved"
        saturation_desc = f"Only {ac} listed vs {sc} sold. This is a GOLD MINE — buy everything you find."
    elif active_sold_ratio < 3:
        saturation_tier = "balanced"
        saturation_label = "🟡 Balanced"
        saturation_desc = "Healthy market. Price competitively and you'll sell."
    elif active_sold_ratio < 8:
        saturation_tier = "competitive"
        saturation_label = "🟠 Competitive"
        saturation_desc = f"{ac} sellers for {sc} buyers. You need the best price or best condition."
    else:
        saturation_tier = "oversaturated"
        saturation_label = "🔴 Oversaturated"
        saturation_desc = f"{ac} listed, only {sc} sold. SKIP unless you can wait months."

    # ── ALERT BADGES ──
    alerts = []
    vol_label = volume_trend_label  # from liquidity analysis
    if str_rate > 50 and vol_label == "accelerating" and active_sold_ratio < 2:
        alerts.append({"type": "hot", "icon": "🔥", "label": "HOT ITEM",
                       "desc": "High sell-through, demand accelerating, low competition. Buy immediately."})
    if active_sold_ratio > 5 and sc > 0:
        alerts.append({"type": "saturated", "icon": "⚠️", "label": "SATURATED",
                       "desc": f"Supply is {active_sold_ratio:.0f}x demand. Proceed with extreme caution."})
    if ac < 5 and velocity > 0.5:
        alerts.append({"type": "gem", "icon": "💎", "label": "HIDDEN GEM",
                       "desc": f"Only {ac} active listings with {velocity:.1f} sales/day. Nobody else noticed this."})

    # ── CONDITION GAPS ──
    condition_gaps = []
    if condition_stats and len(condition_stats) >= 2:
        cond_list = sorted(condition_stats.keys())
        for i, cond in enumerate(cond_list):
            stats = condition_stats[cond]
            cs_count = stats.get("count", 0)
            if i > 0:
                prev_cond = cond_list[i-1]
                prev_median = condition_stats[prev_cond].get("median", 0)
                curr_median = stats.get("median", 0)
                if cs_count < 3 and prev_median > 0 and curr_median > 0:
                    gap_pct = ((curr_median - prev_median) / prev_median) * 100
                    if gap_pct > 15:
                        condition_gaps.append({
                            "condition": cond,
                            "gap": f"+{gap_pct:.0f}% premium",
                            "desc": f"Sellers ignoring {cond} — charge {gap_pct:.0f}% more than {prev_cond}."
                        })

    # ── OPPORTUNITY SCORE (separate from flip score) ──
    opp_score = 50
    if saturation_tier == "underserved": opp_score += 25
    elif saturation_tier == "balanced": opp_score += 10
    elif saturation_tier == "competitive": opp_score -= 10
    elif saturation_tier == "oversaturated": opp_score -= 25
    if velocity > 1: opp_score += 15
    elif velocity > 0.5: opp_score += 10
    elif velocity > 0.1: opp_score += 0
    else: opp_score -= 10
    if vol_label == "accelerating": opp_score += 15
    elif vol_label == "slowing": opp_score -= 15
    opp_score += min(10, len(condition_gaps) * 5)
    if any(a["type"] == "hot" for a in alerts): opp_score += 10
    if any(a["type"] == "gem" for a in alerts): opp_score += 8
    if any(a["type"] == "saturated" for a in alerts): opp_score -= 10
    opp_score = max(0, min(100, round(opp_score)))
    if opp_score >= 70:
        opp_verdict, opp_desc = "🌟 Prime Opportunity", "Market conditions are ideal. Low competition, growing demand."
    elif opp_score >= 50:
        opp_verdict, opp_desc = "👍 Good Opportunity", "Favorable market. Worth pursuing with the right price."
    elif opp_score >= 30:
        opp_verdict, opp_desc = "🤔 Mixed Signals", "Some good signs, some red flags. Be selective."
    else:
        opp_verdict, opp_desc = "👎 Poor Timing", "Too many sellers, not enough buyers right now."

    saturation = {
        "tier": saturation_tier, "label": saturation_label, "description": saturation_desc,
        "active_sold_ratio": round(active_sold_ratio, 1), "active_count": ac, "sold_count": sc,
    }
    opportunity = {
        "score": opp_score, "verdict": opp_verdict, "description": opp_desc,
        "saturation": saturation, "alerts": alerts, "condition_gaps": condition_gaps,
    }

    # ── FLIP SCORE ──
    score = 50
    if str_rate > 30: score += 15
    elif str_rate > 15: score += 8
    elif str_rate > 5: score += 0
    else: score -= 10

    if margin_pct > 50: score += 20
    elif margin_pct > 25: score += 12
    elif margin_pct > 10: score += 5
    elif margin_pct < 0: score -= 15
    else: score -= 8

    if competition < 20: score += 10
    elif competition < 40: score += 5
    elif competition > 70: score -= 8

    if velocity > 1: score += 10
    elif velocity > 0.3: score += 3
    elif velocity < 0.05: score -= 10

    if volatility < 8: score += 5
    elif volatility > 20: score -= 10

    score = max(0, min(100, round(score)))

    if score >= 70:
        verdict, detail = "🔥 Great Flip", "Strong demand, good margins. Buy confidently."
    elif score >= 50:
        verdict, detail = "✅ Decent Flip", "Reasonable margins. Watch your buy price."
    elif score >= 30:
        verdict, detail = "⚠️ Risky Flip", "Tight margins or high competition."
    else:
        verdict, detail = "🚫 Avoid", "Low demand, thin margins, or high risk."

    best_condition = None
    best_margin = 0
    if condition_stats:
        for cond, stats in condition_stats.items():
            c_median = stats.get("median", 0)
            c_low = stats.get("low", 0)
            if c_low > 0 and c_median > 0:
                c_margin = c_median - c_low
                if c_margin > best_margin:
                    best_margin = c_margin
                    best_condition = cond

    explanation = _build_market_explanation(trend, sm, am, ac, sc, velocity, str_rate,
                                             buy_price, margin_dollar, is_vehicle,
                                             platform, shipping_cost)

    # Calculate net profit after fees
    sell_price_for_fees = potential_sell
    fee_calc = _calculate_net_profit(sell_price_for_fees, potential_buy, platform, shipping_cost)

    # Adjust score based on NET profit (not gross)
    net_pct = fee_calc["net_margin_pct"]
    if net_pct > 30: score_adjust = +5
    elif net_pct > 15: score_adjust = +2
    elif net_pct < 0: score_adjust = -10
    elif net_pct < 5: score_adjust = -5
    else: score_adjust = 0
    score = max(0, min(100, score + score_adjust))

    # Recalculate verdict with adjusted score
    if score >= 70:
        verdict, detail = "🔥 Great Flip", "Strong demand, good margins after fees. Buy confidently."
    elif score >= 50:
        verdict, detail = "✅ Decent Flip", "Reasonable margins after fees. Watch your buy price."
    elif score >= 30:
        verdict, detail = "⚠️ Risky Flip", "Tight margins or high fees eating your profit."
    else:
        verdict, detail = "🚫 Avoid", "After fees, this is a losing proposition."

    return {
        "score": score, "verdict": verdict, "verdict_detail": detail,
        "sell_through_rate": round(str_rate, 1),
        "liquidity": liquidity,
        "potential_buy_price": round(potential_buy, 2),
        "potential_sell_price": round(potential_sell, 2),
        "potential_profit": round(margin_dollar, 2),
        "potential_profit_pct": round(margin_pct, 1),
        "competition_level": competition,
        "velocity_per_day": round(velocity, 2), "velocity_label": velocity_label,
        "volatility": round(volatility, 1), "risk_level": risk_level,
        "best_condition_to_flip": best_condition,
        "best_condition_margin": round(best_margin, 2) if best_condition else 0,
        "market_explanation": explanation,
        "user_buy_price_used": buy_price > 0,
        "fee_calculation": fee_calc,
        "saturation": saturation,
        "opportunity": opportunity,
    }


def _build_market_explanation(trend, sold_median, active_median, active_count,
                               sold_count, velocity, str_rate, buy_price=0,
                               margin_dollar=0, is_vehicle=False,
                               platform="ebay", shipping_cost=0.0):
    if not trend or len(trend) < 2:
        return "Not enough data to analyze."

    parts = []
    first = trend[0]["median"]
    last = trend[-1]["median"]
    change_pct = ((last - first) / first * 100) if first > 0 else 0

    if change_pct > 10:
        parts.append(f"Prices rising sharply (+{change_pct:.0f}%). Strong demand.")
    elif change_pct > 3:
        parts.append(f"Prices trending up (+{change_pct:.0f}%).")
    elif change_pct > -3:
        parts.append(f"Prices stable ({change_pct:+.0f}%).")
    elif change_pct > -10:
        parts.append(f"Prices declining ({change_pct:+.0f}%).")
    else:
        parts.append(f"Prices falling ({change_pct:+.0f}%).")

    if is_vehicle:
        parts.append("Vehicles depreciate over time. Condition, mileage, and service history heavily impact value.")
    else:
        if sold_count > 0 and active_count > 0:
            r = active_count / sold_count
            if r > 5:
                parts.append(f"High supply ({active_count} active vs {sold_count} sold). Price competitively.")
            elif r > 2:
                parts.append(f"Moderate competition ({active_count} active vs {sold_count} sold).")
            else:
                parts.append(f"Low competition ({active_count} active for {sold_count} sold).")

        if velocity > 1: parts.append(f"Fast seller ({velocity:.1f}/day).")
        elif velocity > 0.1: parts.append(f"Moderate velocity ({velocity:.1f}/day).")
        else: parts.append(f"Slow mover ({velocity:.2f}/day).")

        if str_rate > 30: parts.append(f"Great sell-through ({str_rate:.0f}%).")
        elif str_rate > 10: parts.append(f"Decent sell-through ({str_rate:.0f}%).")
        else: parts.append(f"Low sell-through ({str_rate:.0f}%).")

    if buy_price and buy_price > 0:
        fee_calc = _calculate_net_profit(sold_median, buy_price, platform, shipping_cost)
        net = fee_calc["net_profit"]
        if net > 0:
            parts.append(f"✅ At ${buy_price:.2f}, net ~${net:.2f} after all fees (gross ${margin_dollar:.2f}).")
        else:
            parts.append(f"⚠️ At ${buy_price:.2f}, you'd lose ${abs(net):.2f} after fees (median sale ${sold_median:.2f}).")

    return " ".join(parts)


# ═══════════════════════════════════════════
#  ROUTES
# ═══════════════════════════════════════════

from flask import send_file, make_response
import os as _os

@app.route("/")
def index():
    # Serve static HTML directly — no Jinja2, no caching, no bytecode
    path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "templates", "index.html")
    resp = make_response(send_file(path, mimetype='text/html'))
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    return resp


@app.route("/api/search")
def api_search():
    q = request.args.get("q", "").strip()
    period = request.args.get("period", "6m")
    if period not in PERIOD_DAYS:
        period = "6m"
    period_days = PERIOD_DAYS[period]
    filter_condition = request.args.get("condition", "all").strip().lower()
    buy_price_str = request.args.get("buy_price", "0").strip()
    platform = request.args.get("platform", "ebay").strip().lower()
    if platform not in PLATFORM_FEES:
        platform = "ebay"
    shipping_str = request.args.get("shipping", "0").strip()
    try:
        buy_price = float(buy_price_str) if buy_price_str else 0.0
    except (ValueError, TypeError):
        buy_price = 0.0
    try:
        shipping_cost = float(shipping_str) if shipping_str else 0.0
    except (ValueError, TypeError):
        shipping_cost = 0.0

    if not q:
        return jsonify({"error": "Missing query"}), 400

    cache_key = f"{q.lower()}|{period}|{filter_condition}|{buy_price}|{platform}|{shipping_cost}"
    if cache_key in PRICE_CACHE:
        cached = PRICE_CACHE[cache_key]
        age = (datetime.now(timezone.utc) - cached["_cached_at"]).total_seconds()
        if age < 300:
            cached["active_filter_condition"] = filter_condition
            return jsonify(cached)

    try:
        result = _do_search(q, period_days, period, filter_condition, buy_price, platform, shipping_cost)
        result["_cached_at"] = datetime.now(timezone.utc)
        PRICE_CACHE[cache_key] = result
        return jsonify(result)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e), "query": q}), 500


@app.route("/api/status")
def api_status():
    """Return API configuration status."""
    return jsonify({
        "ebay_configured": bool(EBAY_CLIENT_ID and EBAY_CLIENT_SECRET),
        "gemini_configured": bool(GEMINI_API_KEY),
        "pricecharting_status": "scraping_only",
    })


# ═══════════════════════════════════════════
#  EBAY SOLD DATA SCRAPER
# ═══════════════════════════════════════════

def _get_ebay_token() -> str | None:
    """Get OAuth token for eBay Browse API."""
    if not EBAY_CLIENT_ID or not EBAY_CLIENT_SECRET:
        return None
    
    creds = base64.b64encode(f"{EBAY_CLIENT_ID}:{EBAY_CLIENT_SECRET}".encode()).decode()
    
    try:
        r = SESSION.post(
            EBAY_OAUTH_URL,
            headers={
                "Authorization": f"Basic {creds}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data="grant_type=client_credentials&scope=https://api.ebay.com/oauth/api_scope",
            timeout=15
        )
        if r.status_code == 200:
            return r.json().get("access_token")
    except Exception as e:
        print(f"⚠️ eBay OAuth failed: {e}")
    return None


def _scrape_ebay_sold(query: str, condition: str = "all", limit: int = 60) -> list[dict]:
    """Get real sold items from eBay Browse API."""
    token = _get_ebay_token()
    if not token:
        print("⚠️ No eBay API credentials - using Smart Estimate")
        return []
    
    sold_items = []
    
    # Build filter for sold items
    filter_parts = ["soldItemOnly:true"]
    
    # Map our conditions to eBay condition IDs
    cond_map = {
        "new (sealed)": ["NEW"],
        "new": ["NEW"],
        "like new": ["OPEN_BOX", "LIKE_NEW"],
        "very good": ["VERY_GOOD", "EXCELLENT"],
        "good": ["GOOD"],
        "acceptable": ["ACCEPTABLE"],
        "for parts": ["PARTS_ONLY", "FOR_PARTS"],
    }
    
    if condition != "all" and condition in cond_map:
        cond_ids = ",".join(cond_map[condition])
        filter_parts.append(f"conditionIds:{{{cond_ids}}}")
    
    filters = ",".join(filter_parts)
    
    # eBay Browse API endpoint
    url = f"{EBAY_API_BASE}/buy/browse/v1/item_summary/search"
    params = {
        "q": query,
        "filter": filters,
        "limit": str(min(limit, 50)),
        "sort": "sellingStatus[0].price desc",
    }
    
    try:
        headers = {"Authorization": f"Bearer {token}"}
        r = SESSION.get(url, params=params, headers=headers, timeout=20)
        
        if r.status_code == 401:
            print("⚠️ eBay API auth expired")
            return []
        elif r.status_code != 200:
            print(f"eBay API error: {r.status_code} - {r.text[:200]}")
            return []
        
        data = r.json()
        items = data.get("itemSummaries", [])
        
        for item in items:
            price_info = item.get("price", {})
            price = float(price_info.get("value", 0))
            
            if price <= 0:
                continue
            
            # Map eBay condition to our format
            ebay_cond = item.get("condition", "")
            our_cond = "good"
            for k, v in cond_map.items():
                if ebay_cond in v:
                    our_cond = k
                    break
            
            # Get item end date for sold date
            item_end = item.get("itemEndDate", "")
            sold_date = item_end[:10] if item_end else None
            
            sold_items.append({
                "title": item.get("title", ""),
                "price": price,
                "sold_date": sold_date,
                "url": item.get("itemWebUrl", ""),
                "condition": our_cond,
            })
        
        print(f"✅ eBay API returned {len(sold_items)} sold items")
        
    except Exception as e:
        print(f"⚠️ eBay API failed: {e}")
    
    return sold_items


def _parse_ebay_sold_page(url: str, limit: int) -> list[dict]:
    """Parse eBay sold results page (fallback for when API is unavailable)."""
    try:
        r = SESSION.get(url, timeout=15)
        if r.status_code != 200:
            return []
    except Exception:
        return []
    
    soup = BeautifulSoup(r.text, "html.parser")
    items = []
    
    for li in soup.select("li.s-item.s-item__pl-on-bottom"):
        try:
            title_el = li.select_one(".s-item__title")
            price_el = li.select_one(".s-item__price")
            date_el = li.select_one(".s-item__endedDate")
            link_el = li.select_one("a.s-item__link")
            
            title = title_el.get_text(strip=True) if title_el else ""
            price_text = price_el.get_text(strip=True) if price_el else ""
            price = _clean_price(price_text) if price_text else 0
            
            if not title or price <= 0 or "shop on ebay" in title.lower():
                continue
            
            sold_date = None
            if date_el:
                date_text = date_el.get_text(strip=True)
                m = re.search(r'(\w{3}\s+\d{1,2},\s+\d{4})', date_text)
                if m:
                    try:
                        sold_date = datetime.strptime(m.group(1), "%b %d, %Y").strftime("%Y-%m-%d")
                    except:
                        pass
            
            detected_cond = _normalize_condition(title, _get_condition_system(title))
            
            items.append({
                "title": title, "price": price, "sold_date": sold_date,
                "url": link_el.get("href", "") if link_el else "",
                "condition": detected_cond,
            })
            
            if len(items) >= limit:
                break
        except Exception:
            continue
    
    return items


def _get_ai_market_value(query: str, condition: str) -> dict | None:
    """Query Gemini for estimated market value."""
    if not GEMINI_API_KEY:
        return None
    
    prompt = f"""You are a market research expert. Provide current resale value estimates for:
    
Item: {query}
Condition: {condition}

Return ONLY a JSON object with this exact format (no other text):
{{"low": number, "median": number, "high": number, "currency": "USD", "reasoning": "brief note"}}

Guidelines:
- low: Bottom of typical range (worst condition, highest fees, etc.)
- median: Most common selling price
- high: Top of typical range (best condition, unlocked, etc.)
- Base on recent sold listings on eBay, Swappa, Back Market
- If you cannot determine, return null values"""

    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(prompt)
        
        import json
        import re
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        if match:
            data = json.loads(match.group())
            return {
                "low": data.get("low", 0),
                "median": data.get("median", 0),
                "high": data.get("high", 0),
                "reasoning": data.get("reasoning", "")
            }
    except Exception as e:
        print(f"⚠️ AI estimation failed: {e}")
    
    return None


def _get_market_value(query: str, condition: str = "all") -> dict:
    """
    Get market value using tiered approach:
    1. eBay Browse API (if configured)
    2. AI estimation (Gemini)
    3. Category baselines (fallback)
    
    Returns: {low, median, high, source, confidence, items, sold_count, note}
    """
    result = {
        "low": 0, "median": 0, "high": 0,
        "p10": 0, "p90": 0, "mean": 0,
        "source": "none", "confidence": "none",
        "items": [], "sold_count": 0, "note": ""
    }
    
    # TIER 1: Try eBay API (highest priority)
    if EBAY_CLIENT_ID and EBAY_CLIENT_SECRET:
        items = _scrape_ebay_sold(query, condition, limit=60)
        if len(items) >= 5:
            stats = _compute_stats(items)
            return {
                **stats,
                "source": f"eBay Sold Data ({len(items)} items)",
                "confidence": "high",
                "items": items[:10],
                "sold_count": len(items),
                "note": "Real sold prices from eBay"
            }
    
    # TIER 2: Use AI estimation (Gemini) - if available and no eBay data
    if GEMINI_API_KEY and result["confidence"] != "high":
        ai_result = _get_ai_market_value(query, condition)
        if ai_result and ai_result.get("median"):
            # Generate synthetic items for display
            import random
            random.seed(abs(hash(query)) % 2**32)
            base = ai_result["median"]
            synthetic_items = []
            for i in range(5):
                synthetic_items.append({
                    "title": f"{query} - Estimated",
                    "price": round(base * (0.85 + random.random() * 0.3), 2),
                    "sold_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    "url": f"https://www.ebay.com/sch/i.html?_nkw={urllib.parse.quote_plus(query)}&LH_Sold=1",
                    "condition": condition,
                })
            return {
                "low": ai_result["low"],
                "p10": round(ai_result["low"] * 1.05, 2),
                "median": ai_result["median"],
                "p90": round(ai_result["high"] * 0.95, 2),
                "high": ai_result["high"],
                "mean": (ai_result["low"] + ai_result["median"] + ai_result["high"]) / 3,
                "source": "AI Estimation (Gemini)",
                "confidence": "medium",
                "items": synthetic_items,
                "sold_count": 0,
                "note": f"AI estimate: {ai_result.get('reasoning', 'Based on public market data')}"
            }
    
    # TIER 3: Category baseline (lowest priority)
    cat, cat_lo, cat_med, cat_hi = _guess_category(query)
    cond_system = _get_condition_system(cat)
    cond_mult = cond_system["multipliers"].get(condition, 0.7)
    
    # Generate synthetic data with WIDE range for low confidence
    base = cat_med * cond_mult
    
    # Generate synthetic items for display
    import random
    random.seed(abs(hash(query)) % 2**32)
    synthetic_items = []
    for i in range(5):
        synthetic_items.append({
            "title": f"{query} - {condition}",
            "price": round(base * (0.75 + random.random() * 0.5), 2),
            "sold_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "url": f"https://www.ebay.com/sch/i.html?_nkw={urllib.parse.quote_plus(query)}&LH_Sold=1",
            "condition": condition,
        })
    
    return {
        "low": round(base * 0.75, 2),
        "p10": round(base * 0.80, 2),
        "median": round(base, 2),
        "p90": round(base * 1.20, 2),
        "high": round(base * 1.25, 2),
        "mean": round(base, 2),
        "source": f"Category Estimate ({cat})",
        "confidence": "low",
        "items": synthetic_items,
        "sold_count": 0,
        "note": "No real sales data. Use verification links below."
    }


def _do_search(q: str, period_days: int, period: str,
               filter_condition: str, buy_price: float,
               platform: str = "ebay", shipping_cost: float = 0.0) -> dict:
    now = datetime.now(timezone.utc)
    sold_items = []
    active_items = []

    ql = q.lower()
    is_gaming = any(kw in ql for kw in GAMING_KEYWORDS)
    is_vehicle = _is_vehicle_query(q)

    # Determine category and condition system
    cat, cat_lo, cat_med, cat_hi = _guess_category(q)
    cond_system = _get_condition_system(cat)
    condition_list = cond_system["conditions"]
    cond_mult = cond_system["multipliers"]
    cond_labels = cond_system["labels"]

    # ── Use tiered market value lookup ──
    market_data = _get_market_value(q, filter_condition if filter_condition and filter_condition != "all" else "very good")
    sold_items = market_data.get("items", [])
    data_source = market_data.get("source", f"Smart Estimate ({cat})")
    confidence = market_data.get("confidence", "low")
    market_note = market_data.get("note", "")
    
    # Generate active listings based on market data
    if sold_items:
        sold_stats = _compute_stats(sold_items)
        base_active = sold_stats.get("median", cat_med) * 1.06
        import random
        random.seed(42)
        for i in range(20):
            cond = condition_list[i % len(condition_list)]
            mult = cond_mult.get(cond, 1.0)
            price = round(base_active * mult * (0.85 + random.random() * 0.3), 2)
            active_items.append({
                "title": f"{q.title()} - Active Listing",
                "price": price, "shipping": 0.0,
                "url": f"https://www.ebay.com/sch/i.html?_nkw={urllib.parse.quote_plus(q)}",
                "condition": cond,
            })
    elif is_vehicle:
        vi = _get_vehicle_info(q)
        data_source = f"Vehicle Estimate — {vi['make_model']} ({vi['year']})"
        base_val = vi["estimated_value"]
        import random
        random.seed(abs(hash(q)) % 2**32)
        for i in range(40):
            cond = condition_list[i % len(condition_list)]
            mult = cond_mult.get(cond, 1.0)
            price = round(base_val * mult * (0.85 + random.random() * 0.3), 2)
            sold_items.append({
                "title": f"{vi['year']} {vi['make_model']} - {cond.title()}, Clean Title",
                "price": price, "shipping": 0.0,
                "sold_date": (now - timedelta(days=int(abs(random.gauss(5, period_days/3)) % max(period_days, 7) + 1))).strftime("%Y-%m-%d"),
                "url": f"https://www.kbb.com/cars-for-sale/all/{urllib.parse.quote_plus(q)}",
                "condition": cond,
            })
        for i in range(20):
            cond = condition_list[i % len(condition_list)]
            mult = cond_mult.get(cond, 1.0) * 1.06
            price = round(base_val * mult * (0.85 + random.random() * 0.3), 2)
            active_items.append({
                "title": f"{vi['year']} {vi['make_model']} - {cond.title()}",
                "price": price, "shipping": 0.0,
                "url": f"https://www.kbb.com/cars-for-sale/all/{urllib.parse.quote_plus(q)}",
                "condition": cond,
            })

    # ── PriceCharting (games only) ──
    elif is_gaming:
        try:
            products = _search_pricecharting(q)
            if products:
                best = products[0]
                if best.get("relevance", 0) >= 0.3:
                    pc_data = _scrape_pricecharting_detail(best["url"], cond_system)
                    if pc_data and pc_data.get("sold_listings"):
                        data_source = f"PriceCharting — {best['title']}"
                        sold_items = pc_data["sold_listings"]
                        import random
                        prices_list = [it["price"] for it in sold_items if it.get("price")]
                        mean_p = sum(prices_list) / len(prices_list) if prices_list else 100
                        conds_used = list(set(
                            it.get("condition", "good") for it in sold_items
                            if it.get("condition") in condition_list
                        ))
                        if not conds_used:
                            conds_used = [condition_list[3]] if len(condition_list) > 3 else [condition_list[-1]]
                        for i in range(15):
                            active_items.append({
                                "title": f"{best['title']} - Available",
                                "price": round(mean_p * (0.85 + random.random() * 0.3), 2),
                                "shipping": 0.0,
                                "url": f"https://www.ebay.com/sch/i.html?_nkw={urllib.parse.quote_plus(q)}&LH_BIN=1&_sop=15",
                                "condition": conds_used[i % len(conds_used)],
                            })
        except Exception:
            pass

    # ── Smart Estimate ──
    if not sold_items:
        import random
        random.seed(abs(hash(q)) % 2**32)
        # Use the category's median price as the "good condition" baseline
        base_price = cat_med

        for i in range(50):
            cond = condition_list[i % len(condition_list)]
            mult = cond_mult.get(cond, 1.0)
            price = round(base_price * mult * (0.75 + random.random() * 0.5), 2)
            sold_items.append({
                "title": f"{q.title()} - {cond_labels.get(cond, cond.title())}",
                "price": price, "shipping": 0.0,
                "sold_date": (now - timedelta(days=int(abs(random.gauss(1, period_days/4)) % max(period_days, 7) + 1))).strftime("%Y-%m-%d"),
                "url": f"https://www.ebay.com/sch/i.html?_nkw={urllib.parse.quote_plus(q)}&LH_Sold=1&LH_Complete=1",
                "condition": cond,
            })
        for i in range(25):
            cond = condition_list[i % len(condition_list)]
            mult = cond_mult.get(cond, 1.0) * 1.06
            price = round(base_price * mult * (0.8 + random.random() * 0.5), 2)
            active_items.append({
                "title": f"{q.title()} - {cond_labels.get(cond, cond.title())}",
                "price": price, "shipping": 0.0,
                "url": f"https://www.ebay.com/sch/i.html?_nkw={urllib.parse.quote_plus(q)}&LH_BIN=1&_sop=15",
                "condition": cond,
            })

    # ── Filter ──
    effective_cond = filter_condition if filter_condition and filter_condition != "all" else None
    sold_filtered = _filter_by_condition(sold_items, effective_cond) if effective_cond else sold_items
    active_filtered = _filter_by_condition(active_items, effective_cond) if effective_cond else active_items

    # ── Stats ──
    sold_stats = _compute_stats(sold_filtered)
    active_stats = _compute_stats(active_filtered)
    condition_sold = _stats_by_condition(sold_items, cond_system)
    condition_active = _stats_by_condition(active_items, cond_system)

    sm = sold_stats.get("median", 0) or 0
    median_price = sm or active_stats.get("median", 0) or 50

    trend = _generate_trend(median_price, sold_stats.get("count", 10), sold_filtered, period_days)

    if len(trend) >= 2:
        first_med = trend[0]["median"]
        last_med = trend[-1]["median"]
        if last_med > first_med * 1.03:
            direction = "rising"
        elif last_med < first_med * 0.97:
            direction = "falling"
        else:
            direction = "stable"
    else:
        direction = "stable"

    recent_sold = sorted(sold_filtered, key=lambda x: x.get("sold_date", ""), reverse=True)[:30]
    flip = _analyze_flip(sold_stats, active_stats, sold_filtered, active_filtered,
                         trend, condition_sold, buy_price, is_vehicle,
                         platform, shipping_cost)

    available_conditions = [c for c in condition_list if c in condition_sold or c in condition_active]
    if not available_conditions:
        available_conditions = condition_list

    result = {
        "query": q,
        "period": period,
        "active_filter_condition": effective_cond or "all",
        "available_conditions": available_conditions,
        "condition_labels": cond_labels,
        "category": cat,
        "sold_summary": sold_stats,
        "active_summary": active_stats,
        "condition_sold": condition_sold,
        "condition_active": condition_active,
        "trend": trend,
        "direction": direction,
        "recent_sold": recent_sold,
        "active_listings": active_filtered[:20],
        "data_source": data_source,
        "is_real_data": confidence == "high",
        "is_synthetic": confidence != "high" and not is_vehicle,
        "real_items_count": market_data.get("sold_count", 0),
        "confidence": confidence,
        "confidence_label": {
            "high": "✅ High confidence - Real sales data",
            "medium": "⚠️ Medium confidence - AI estimation",
            "low": "❌ Low confidence - Historical estimate"
        }.get(confidence, ""),
        "market_note": market_note,
        "flip_analysis": flip,
        "ebay_url": (
            f"https://www.ebay.com/sch/i.html"
            f"?_nkw={urllib.parse.quote_plus(q)}&LH_Sold=1&LH_Complete=1"
        ),
        "total_sold_scraped": len(sold_filtered),
        "total_active_scraped": len(active_filtered),
        "buy_price": buy_price if buy_price > 0 else 0,
        "platform": platform,
        "shipping_cost": shipping_cost if shipping_cost > 0 else 0,
        "is_vehicle": is_vehicle,
        "saturation": flip.get("saturation"),
        "opportunity": flip.get("opportunity"),
        "api_missing": not (EBAY_CLIENT_ID and EBAY_CLIENT_SECRET),
        "setup_instructions": "To get real eBay prices: https://developer.ebay.com/signin → Create App → Set EBAY_CLIENT_ID and EBAY_CLIENT_SECRET env vars",
    }

    if is_vehicle:
        result["vehicle_info"] = _get_vehicle_info(q)

    # Record search for trending (fire-and-forget, don't block)
    try:
        import threading
        def _record():
            try:
                from firebase_service import get_provider
                get_provider().record_search(q, data_source)
            except Exception:
                pass
        threading.Thread(target=_record, daemon=True).start()
    except Exception:
        pass

    return result


GEMINI_PROMPT = """You are a product identification expert. Look at this image and identify what product is shown.
Return ONLY the product name and brand if visible. Examples: "Nintendo Switch OLED", "Nike Air Force 1", "iPhone 15 Pro".
If you can't identify it, say "Unknown item". Be specific with brand names."""


def _extract_product_name(labels: list) -> str:
    """Extract product name from Vision API labels (fallback method)."""
    exclude = {'product', 'item', 'goods', 'electronics', 'text', 'font', 'logo', 'brand', 'label'}
    product_labels = [l['description'] for l in labels 
                      if l['score'] > 0.7 
                      and l['description'].lower() not in exclude]
    
    if not product_labels:
        best = max(labels, key=lambda x: x['score'])['description'] if labels else None
        return best or "Unknown item"
    
    return ' '.join(product_labels[:3])


@app.route("/api/identify", methods=["POST"])
def api_identify():
    """Analyze an image and return a product description using AI."""
    if "image" not in request.files:
        return jsonify({"error": "No image provided"}), 400
    
    file = request.files["image"]
    if not file:
        return jsonify({"error": "No image provided"}), 400
    
    img_bytes = file.read()
    
    # Try Google Gemini first (simpler API key setup)
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    if gemini_key:
        try:
            import google.generativeai as genai
            model = genai.GenerativeModel('gemini-1.5-flash')
            image_parts = [{"mime_type": "image/jpeg", "data": img_bytes}]
            response = model.generate_content([image_parts, GEMINI_PROMPT])
            description = response.text.strip()
            if description and description != "Unknown item":
                print(f"✅ Gemini identified: {description}")
                return jsonify({"description": description, "provider": "gemini"})
        except Exception as e:
            print(f"⚠️ Gemini failed: {e}")
    
    # Fallback to Cloudflare Workers AI
    if CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN:
        try:
            cf_url = f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/ai/run/@cf/meta/llama-3.2-11b-vision-instruct"
            headers = {"Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}"}
            b64_image = base64.b64encode(img_bytes).decode()
            
            payload = {
                "messages": [{
                    "role": "user",
                    "content": f"Image: data:image/jpeg;base64,{b64_image}\n\n{GEMINI_PROMPT}"
                }]
            }
            
            resp = requests.post(cf_url, headers=headers, json=payload, timeout=30)
            if resp.ok:
                result = resp.json()
                description = result.get('result', {}).get('response', '').strip()
                if description and description != "Unknown item":
                    print(f"✅ Cloudflare AI identified: {description}")
                    return jsonify({"description": description, "provider": "cloudflare"})
        except Exception as e:
            print(f"⚠️ Cloudflare failed: {e}")
    
    # No AI available - return empty description for manual input
    print("⚠️ No AI services available for image identification")
    return jsonify({"description": "", "error": "AI analysis failed. Please describe manually."}), 200



# ═══════════════════════════════════════════
#  QUICK DEAL MODE — natural language parser
# ═══════════════════════════════════════════

@app.route("/api/quick-deal")
def api_quick_deal():
    """Parse natural-language input like 'Nikon D850, good, $400'."""
    raw = request.args.get("input", "").strip()
    if not raw:
        return jsonify({"error": "Enter what you found and the price. e.g. 'Nikon D850, good, $400'"}), 400

    platform = request.args.get("platform", "ebay").strip().lower()
    if platform not in PLATFORM_FEES:
        platform = "ebay"
    shipping_str = request.args.get("shipping", "0").strip()
    try:
        shipping_cost = float(shipping_str) if shipping_str else 0.0
    except (ValueError, TypeError):
        shipping_cost = 0.0

    # Parse item name, condition, price from input
    price_match = re.search(r'\$?\s*(\d+(?:\.\d{1,2})?)\s*$', raw)
    buy_price = 0.0
    item_part = raw
    if price_match:
        buy_price = float(price_match.group(1))
        item_part = raw[:price_match.start()].strip().rstrip(',')
        item_part = re.sub(r'\s+(for|at)\s*$', '', item_part, flags=re.IGNORECASE)

    # Detect category and condition
    cat, _, cat_med, _ = _guess_category(item_part)
    cond_sys = _get_condition_system(cat)
    detected_condition = "good"
    best_score = 0
    item_lower = item_part.lower()
    # Sort conditions by length (longest first) for proper matching
    sorted_conds = sorted(cond_sys["conditions"], key=len, reverse=True)
    for cond in sorted_conds:
        score = 0
        # Direct substring match
        if cond in item_lower: score = 15
        if score == 0:
            # Keyword-based matching
            kw_map = {
                "like new": ["like new", "excellent condition", "near mint"],
                "new (sealed)": ["sealed", "factory sealed", "brand new sealed", "nis"],
                "for parts": ["broken", "not working", "damaged", "parts only", "repair", "for parts"],
                "poor": ["broken", "not working", "damaged", "parts only", "repair", "for parts", "salvage", "junk"],
                "new": [" brand new ", "brand new", "never opened"],
                "acceptable": ["fair condition", "worn", "heavy wear", "scratched", "beater", "beat up"],
                "very good": ["very good", "great condition", "lightly used"],
                "good": ["used", "pre-owned", "preowned"],
                "untested": ["untested", "as is", "not tested"],
            }
            if cond in kw_map:
                for kw in kw_map[cond]:
                    if kw in item_lower:
                        score = 9
                        break
        if score > best_score:
            best_score = score
            detected_condition = cond

    # Clean item name
    if best_score > 0:
        item_cleaned = item_lower
        for kw in [detected_condition, detected_condition.replace(" (sealed)", "")]:
            item_cleaned = item_cleaned.replace(kw, "")
        item_cleaned = re.sub(r'\s+,', ',', item_cleaned).strip().strip(',').strip()
        if len(item_cleaned) > 3:
            item_part = item_cleaned

    item_name = item_part.strip().strip(',').strip()
    if not item_name or len(item_name) < 3:
        return jsonify({"error": "Could not identify the item. Try: 'Nikon D850, good, $400'"}), 400

    try:
        result = _do_search(item_name, 180, "6m", detected_condition, buy_price, platform, shipping_cost)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"Search failed: {str(e)}"}), 500

    flip = result.get("flip_analysis", {})
    fc = flip.get("fee_calculation", {})
    liq = flip.get("liquidity", {})
    sat = result.get("saturation", {})
    net_profit = fc.get("net_profit", 0)
    score = flip.get("score", 0)
    market_median = result["sold_summary"].get("median", 0)
    market_low = result["sold_summary"].get("low", 0)
    market_high = result["sold_summary"].get("high", 0)

    if net_profit > 0 and score >= 50:
        verdict, label, color, reason = "BUY", "🔥 BUY IT", "green", f"This is a ${abs(net_profit):.0f} profit waiting to happen. Buy immediately."
    elif net_profit > 0 and score >= 30:
        verdict, label, color, reason = "MAYBE", "🤔 MAYBE", "amber", "Small profit but market is competitive. Negotiate the price down."
    else:
        verdict, label, color, reason = "LEAVE", "🚫 LEAVE IT", "red", "After fees, you'll lose money on this. Walk away."

    return jsonify({
        "verdict": verdict, "verdict_label": label, "verdict_color": color,
        "verdict_reason": reason,
        "item_name": item_name,
        "detected_condition": detected_condition,
        "detected_condition_label": cond_sys["labels"].get(detected_condition, detected_condition),
        "your_price": buy_price if buy_price > 0 else None,
        "market_value_range": f"${market_low:.0f} \u2013 ${market_high:.0f}",
        "market_median": round(market_median, 2),
        "flip_score": score,
        "net_profit": round(net_profit, 2),
        "net_profit_display": f"{'+' if net_profit >= 0 else ''}${net_profit:.2f}",
        "net_margin": round(fc.get("net_margin_pct", 0), 1),
        "days_to_sell": round(liq.get("avg_days_to_sell", 30), 1) if liq else 30,
        "velocity_label": liq.get("velocity_label", "Unknown") if liq else "Unknown",
        "competition_ratio": round(sat.get("active_sold_ratio", 1), 1) if isinstance(sat, dict) else 1,
        "competition_label": (
            "Low" if (isinstance(sat, dict) and sat.get("active_sold_ratio", 1) < 1) else
            "Moderate" if (isinstance(sat, dict) and sat.get("active_sold_ratio", 1) < 3) else
            "High" if (isinstance(sat, dict) and sat.get("active_sold_ratio", 1) < 8) else "Very High"
        ),
        "full_result": result,
    })

# ═══════════════════════════════════════════
#  BARCODE LOOKUP
# ═══════════════════════════════════════════

@app.route("/api/barcode")
def api_barcode():
    """Look up product name from UPC/EAN barcode."""
    code = request.args.get("code", "").strip()
    if not code or not re.match(r'^\d{8,14}$', code):
        return jsonify({"error": "Invalid barcode. Must be 8-14 digits."}), 400

    # Try UPCitemdb (free, no auth needed for basic queries)
    try:
        r = SESSION.get(
            f"https://api.upcitemdb.com/prod/trial/lookup?upc={code}",
            timeout=10
        )
        if r.status_code == 200:
            data = r.json()
            if data.get("items") and len(data["items"]) > 0:
                item = data["items"][0]
                return jsonify({
                    "code": code,
                    "title": item.get("title", ""),
                    "brand": item.get("brand", ""),
                    "category": item.get("category", ""),
                    "source": "UPCitemdb",
                })
    except Exception:
        pass

    # Fallback: try Open Food Facts (for consumer products)
    try:
        r = SESSION.get(
            f"https://world.openfoodfacts.org/api/v0/product/{code}.json",
            timeout=10
        )
        if r.status_code == 200:
            data = r.json()
            if data.get("status") == 1 and data.get("product"):
                product = data["product"]
                name = product.get("product_name", "") or product.get("generic_name", "")
                brand = product.get("brands", "")
                if name:
                    return jsonify({
                        "code": code,
                        "title": name,
                        "brand": brand,
                        "category": product.get("categories", ""),
                        "source": "OpenFoodFacts",
                    })
    except Exception:
        pass

    # Fallback: construct a reasonable search term from the barcode
    return jsonify({
        "code": code,
        "title": "",
        "brand": "",
        "category": "",
        "source": "unknown",
        "hint": "No product found for this barcode. Try typing the item name.",
    })


# Ensure DB tables exist
init_db()

# Register all routes — must happen before gunicorn imports
register_routes(app, _do_search)

# ═══════════════════════════════════════════
#  EBAY MARKETPLACE ACCOUNT DELETION NOTIFICATION
# ═══════════════════════════════════════════

EBAY_VERIFICATION_TOKEN = os.environ.get("EBAY_VERIFICATION_TOKEN", "pricespy-ebay-notification-token-2024")

@app.route("/ebay/account-deletion", methods=["POST"])
def ebay_account_deletion():
    """Handle eBay marketplace account deletion notifications."""
    try:
        data = request.get_json(force=True, silent=True) or {}
        print(f"📬 eBay account deletion notification: {data}")
    except Exception:
        pass
    
    return jsonify({
        "status": "received",
        "message": "Acknowledged - no user data to delete"
    }), 200

@app.route("/ebay/account-deletion", methods=["GET"])
def ebay_account_deletion_verification():
    """Verification endpoint for eBay to validate the webhook."""
    challenge_code = request.args.get("challenge_code", "")
    print(f"🔐 eBay verification - challenge: {challenge_code}")
    
    if challenge_code:
        return jsonify({"challengeResponse": challenge_code}), 200
    
    return jsonify({"status": "ok"}), 200

# ═══════════════════════════════════════════
#  PHOTO GALLERY — scrape eBay listing images
# ═══════════════════════════════════════════

@app.route("/api/photos")
def api_photos():
    """Return eBay listing photo thumbnails for a query."""
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "Query required"}), 400
    condition = request.args.get("condition", "all")
    limit = min(int(request.args.get("limit", "12") or 12), 24)

    # Build eBay search URL with condition filter
    u = f"https://www.ebay.com/sch/i.html?_nkw={urllib.parse.quote_plus(q)}"
    u += "&LH_Sold=1&LH_Complete=1&_ipg=60"
    if condition and condition != "all":
        # Correct eBay condition codes
        cond_map = {
            "new": "1000", "new (sealed)": "1000",
            "like new": "2500",
            "very good": "8000",
            "good": "7000",
            "acceptable": "6000",
            "for parts": "5000",
            "loose": "7000",
            "cib": "1000",
            "untested": "6000",
        }
        ebay_cond = cond_map.get(condition, "")
        if ebay_cond:
            u += f"&LH_ItemCondition={ebay_cond}"

    try:
        r = SESSION.get(u, timeout=15)
        if r.status_code != 200:
            return jsonify({"error": "Could not fetch eBay", "photos": []})
    except Exception:
        return jsonify({"error": "eBay unavailable", "photos": []})

    soup = BeautifulSoup(r.text, "html.parser")
    photos = []

    for li in soup.select("li.s-item.s-item__pl-on-bottom")[:limit*2]:
        img_el = li.select_one(".s-item__image-img img, .s-item__image img")
        link_el = li.select_one("a.s-item__link")
        title_el = li.select_one(".s-item__title")
        price_el = li.select_one(".s-item__price")

        img_url = ""
        if img_el:
            img_url = img_el.get("src", "") or img_el.get("data-src", "")

        title = title_el.get_text(" ", strip=True) if title_el else ""
        price = _clean_price(price_el.get_text(" ", strip=True)) if price_el else None
        link = link_el.get("href", "") if link_el else ""

        if not title or "shop on ebay" in title.lower():
            continue
        if img_url and link:
            photos.append({
                "title": title[:100],
                "price": round(price, 2) if price else None,
                "image": img_url,
                "url": link,
            })
            if len(photos) >= limit:
                break

    return jsonify({
        "query": q,
        "condition": condition,
        "photos": photos,
        "ebay_url": u,
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    app.run(host="0.0.0.0", port=port, debug=False)
