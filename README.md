# 🕵️‍♂️ PriceSpy: The Ultimate eBay Sourcing & Financial Underwriting Engine

**PriceSpy** is an elite BOLO ("Be On the Look Out") and institutional-grade financial valuation platform built exactly for professional eBay flippers, estate sale sourcing syndicates, and liquidation buyers. 

Amateur tools give you fantasy "average" comp prices or scrape active wishful listings. PriceSpy underwrites **real eBay complete/sold market medians**, calculates exact Net Profits after fees, and analyzes sell-through saturation—allowing your sourcing buyers out in the field to make split-second *Buy / Pass* decisions with absolute certainty.

---

## ✨ Enterprise Sourcing Features

### 🔍 1. Real Sold Market Median & True Costs Engine
* **Verified Comps**: Scrapes and analyzes actual completed/sold eBay listings, removing outliers and irrelevant accessories to calculate definitive market floors and medians.
* **True Net Profit Math Engine**: Automatically deducts exact eBay Final Value Fees tailored to your specific **eBay Store Tier** (*Basic, Premium, Anchor*).
* **Ad & Shipping Underwriting**: Fully incorporates your operational shipping costs and customized **Promoted Listing ad rates** to reveal what actually hits your bank account.

### 🏷️ 2. Universal Barcode & Box Scanner
* **Live Camera Barcode Reading**: Point your mobile browser at any UPC / EAN barcode or QR code for instant, lightning-fast product detection.
* **Smart UPC Catalog Lookup**: Uses an advanced multi-tiered backend lookup (`/api/barcode`) tapping into **UPCitemdb**, **OpenFoodFacts**, and directly into **eBay's official API catalog** to convert raw UPC digits into clean, readable product names.
* **AI Box Scanning**: Upload or snap a photo of any retail box, vintage product, or unboxed hardware to instantly identify the item using AI (`/api/identify`).

### 🧮 3. Lot / Bundle ROI Calculator
* **Bin & Bundle Underwriting**: Standing at a yard sale looking at a bin of 15 video games or Funko Pops? Rapidly scan or type every item into the Lot Builder.
* **Cumulative Margin Analysis**: Enter a single asking price for the whole bin (or keep individual costs) and instantly calculate combined Market Value, total Net Profit, and an institutional *Buy / Pass* Verdict.
* **Itemized Valuation Table**: Instantly see exactly which items in the bundle are the $80 winners and which are the $5 fillers.

### 📊 4. Liquidity Index & Market Saturation
* **Active-to-Sold Velocity**: Calculates exact competition ratios by comparing live active supply against 6-month trailing sold demand.
* **Sell-Through Index**: Instantly alerts your buyers whether an item is an instant seller (*< 1.0x ratio*) or dead stock destined to sit on warehouse shelves for two years (*> 8.0x ratio*).

### 🏪 5. Comprehensive Operations Suite
* **✍️ AI Title Optimizer**: Analyzes top-selling competitor listings to construct high-converting, keyword-stuffed titles for your virtual assistants and listing staff.
* **🏪 Connected Seller Dashboard**: Links directly to your live eBay seller account via secure OAuth to track active inventory, complete orders, and monitor real-time gross revenue.
* **💵 True ROI Calculator**: Underwrites true bottom-line profitability by factoring in mileage/gas, storage unit costs, hourly labor rates, and tax brackets.
* **⭐ My Flips & Watchlist Tracker**: Log successful flips, track active ROI statuses, and export full accounting spreadsheets (`inventory.csv`) with one click.

---

## ⚙️ Setup & Installation

### Prerequisites
* Python 3.11 or higher
* Valid **eBay Developer Application** credentials ([Create App here](https://developer.ebay.com/signin))
* Optional: **Google Gemini AI API Key** (for Photo / Box AI Identification)

### Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/mjmorrison10/PriceSpy.git
   cd PriceSpy
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure Environment Variables**:
   Create a `.env` file or export the following secret credentials:
   ```bash
   export EBAY_CLIENT_ID="your_ebay_client_id"
   export EBAY_CLIENT_SECRET="your_ebay_client_secret"
   export GEMINI_API_KEY="your_google_gemini_api_key"
   ```

4. **Run the Application**:
   ```bash
   python server.py
   # Or run via Gunicorn / standard WSGI:
   # gunicorn wsgi:app
   ```
   The application will be live at `http://localhost:5000` or `http://127.0.0.1:5000`.

---

## 🛠️ Automated Syntax Validation
To maintain flawless code quality before deploying to live web servers, PriceSpy includes a dedicated pre-deployment validation script.

Run the validator to verify balanced parentheses, catch Javascript syntax imbalances, and inspect console warnings:
```bash
bash validate.sh templates/index.html
```

---

## 🚀 Continuous Deployment
PriceSpy is natively structured for instantaneous continuous deployment on **Render**, **Heroku**, or **Vercel**. 

* **Render Configuration**: Fully pre-configured via `render.yaml` and `runtime.txt`.
* Whenever commits are pushed to the `main` branch, your live web production servers will automatically pull, rebuild, and launch the newest Sourcing Syndicate updates.
