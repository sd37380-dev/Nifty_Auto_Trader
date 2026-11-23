# 🚀 Render & Supabase Deployment Guide

This guide details how to deploy **NIFTY Autonomous Trader** to **[Render.com](https://render.com)** with **[Supabase](https://supabase.com)** cloud database persistence.

---

## 🏗️ Architecture Overview

- **Local Mode (Default)**: Runs seamlessly offline using dedicated SQLite databases in `data/market/` and `data/paper_trading/`. Zero external database required.
  - `data/market/nifty_ticks.db`: **Dedicated NIFTY 50 Tick Database** storing high-resolution NIFTY market ticks (LTP, bid/ask, volume, price changes).
  - `data/market/banknifty_ticks.db`: **Dedicated BANKNIFTY Tick Database** storing high-resolution BANKNIFTY ticks.
  - `data/market/option_chain.db`: **Dedicated Option Chain Database** storing complete derivatives strike ladders, PCR, Max Pain, and Greeks.
  - `data/market/nse_spot_data.db`: 5-minute multi-instrument spot telemetry (NIFTY 50, BANKNIFTY, GIFT NIFTY).
  - `data/paper_trading/`: Simulator audit databases and active position tracking.
- **Render Cloud Web Service**: Runs headless with continuous 5-minute spot data telemetry, Indian market news classifier, and interactive dashboard bound to dynamic `$PORT` (`0.0.0.0`).
- **Supabase Cloud Dual-Persistence**: Every high-resolution tick (to `nifty_ticks` and `banknifty_ticks`), option chain snapshot, news item, spot record, level trigger, and paper trade is non-blockingly synchronized to Supabase PostgreSQL via PostgREST REST API. When Render restarts (or deploys a fresh container), local SQLite is automatically hydrated from the cloud.

---

## 🗄️ Step 1: Set Up Supabase

1. Create a free account at **[supabase.com](https://supabase.com)** and create a new project (e.g., `nifty-trader`).
2. Go to **SQL Editor** in your Supabase dashboard.
3. Open [`supabase_schema.sql`](./supabase_schema.sql) in this repository, copy all contents, paste into the SQL Editor, and click **Run**.
   - This creates 10 dedicated tables:
     1. `nifty_ticks` (Dedicated NIFTY tick store)
     2. `banknifty_ticks` (Dedicated BANKNIFTY tick store)
     3. `market_ticks` (General / Global market ticks e.g. GIFT NIFTY)
     4. `option_chain_snapshots` (Dedicated full option chain matrix store)
     5. `market_news` (Financial news, category, sentiment & impact)
     6. `nse_spot_data` (5-minute multi-instrument spot bars)
     7. `paper_trades` (Completed option simulator audits)
     8. `active_positions` (Real-time active open position & MTM P&L)
     9. `level_triggers` (Custom breakout/breakdown level triggers)
     10. `brain_history` (Gemini AI Brain reasoning evaluations)
   - Sets up indexes, updated_at triggers, and Row Level Security (RLS) policies.
4. Go to **Project Settings -> API**:
   - Copy **Project URL** (e.g., `https://xyzcompany.supabase.co`).
   - Copy **anon / public** or **service_role** key.

---

## 🌐 Step 2: Deploy on Render (render.com)

### Option A: 1-Click Blueprint Deploy (`render.yaml`)

1. Push this repository to your GitHub or GitLab account.
2. Log in to **[dashboard.render.com](https://dashboard.render.com)**.
3. Click **New +** -> **Blueprint**.
4. Connect your repository. Render will automatically detect [`render.yaml`](./render.yaml).
5. Set your environment variables:
   - `SUPABASE_URL`: Your Supabase URL (e.g. `https://xyzcompany.supabase.co`)
   - `SUPABASE_KEY`: Your Supabase anon or service-role key
   - `GEMINI_API_KEY`: Your Google Gemini API key (optional, for LLM Brain)
6. Click **Apply**. Render will build and deploy the service.

### Option B: Manual Web Service Setup

If setting up manually without Blueprints:
- **Environment**: `Python 3` (or `Docker`)
- **Build Command**: `pip install -r requirements.txt && pip install -e .`
- **Start Command**: `python -m nifty_trader.cli dashboard --host 0.0.0.0 --port $PORT --no-open`
- **Health Check Path**: `/health`
- **Environment Variables**:
  - `PYTHON_VERSION`: `3.11.9`
  - `RENDER`: `true`
  - `HOST`: `0.0.0.0`
  - `SUPABASE_URL`: (your Supabase URL)
  - `SUPABASE_KEY`: (your Supabase key)

---

## 🔍 Step 3: Verify Deployment

Once Render displays **Live**:
1. Open your Render app URL: `https://nifty-autonomous-trader.onrender.com`
2. **Health Check**: Visit `/health` — verify it returns:
   ```json
   {
     "status": "healthy",
     "service": "nifty-autonomous-trader",
     "render": true
   }
   ```
3. **Supabase Status**: Visit `/api/supabase/status` or check the dashboard header badge:
   - Connected: `☁️ SUPABASE: CONNECTED`
   - Standalone Local: `💾 LOCAL SQLITE (CLOUD READY)`
4. **Trigger Manual Cloud Hydration**: Send a POST request to `/api/supabase/sync` to restore all historical data to the container.

---

## 🐳 Optional: Local Docker Run

You can also run the exact same container locally:

```bash
docker build -t nifty-trader .
docker run -p 8080:8080 -e SUPABASE_URL="https://xyz.supabase.co" -e SUPABASE_KEY="your-key" nifty-trader
```
Visit `http://localhost:8080` in your browser.
