-- ==============================================================================
-- NIFTY Autonomous Trader — Supabase Database Schema
-- ==============================================================================
-- Run this script in the Supabase Dashboard -> SQL Editor to initialize all tables
-- for persistent cloud storage and synchronization with Render deployments.

-- 1. Market News & Sentiment Table
CREATE TABLE IF NOT EXISTS public.market_news (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    summary TEXT,
    source TEXT DEFAULT 'Market Wire',
    category TEXT DEFAULT 'MARKET_IMPACT',
    impact_type TEXT DEFAULT 'NEUTRAL',
    impact_score INTEGER DEFAULT 3,
    market_effect TEXT,
    is_important INTEGER DEFAULT 0,
    url TEXT,
    published_at TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_supabase_news_published ON public.market_news(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_supabase_news_impact ON public.market_news(impact_type);
CREATE INDEX IF NOT EXISTS idx_supabase_news_important ON public.market_news(is_important, published_at DESC);

-- 2. NSE Spot & Futures Telemetry Table (5-Minute Bars)
CREATE TABLE IF NOT EXISTS public.nse_spot_data (
    id BIGSERIAL PRIMARY KEY,
    timestamp_ist TEXT NOT NULL,
    timestamp_utc TEXT NOT NULL,
    symbol TEXT NOT NULL,
    spot_price NUMERIC(10, 2) NOT NULL,
    day_open NUMERIC(10, 2),
    day_high NUMERIC(10, 2),
    day_low NUMERIC(10, 2),
    day_close NUMERIC(10, 2),
    previous_close NUMERIC(10, 2),
    change_pts NUMERIC(10, 2),
    change_pct NUMERIC(6, 2),
    volume BIGINT DEFAULT 0,
    pdh NUMERIC(10, 2),
    pdl NUMERIC(10, 2),
    r1 NUMERIC(10, 2),
    r2 NUMERIC(10, 2),
    s1 NUMERIC(10, 2),
    s2 NUMERIC(10, 2),
    pivot NUMERIC(10, 2),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_supabase_spot_sym_time ON public.nse_spot_data(symbol, timestamp_ist DESC);

-- 3. Completed Paper Trades Table
CREATE TABLE IF NOT EXISTS public.paper_trades (
    trade_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    strike INTEGER NOT NULL,
    option_type VARCHAR(5) NOT NULL,
    lots INTEGER DEFAULT 1,
    qty INTEGER DEFAULT 65,
    entry_time TEXT NOT NULL,
    exit_time TEXT NOT NULL,
    entry_premium NUMERIC(10, 2) NOT NULL,
    exit_premium NUMERIC(10, 2) NOT NULL,
    exit_reason TEXT NOT NULL,
    gross_pnl NUMERIC(12, 2) NOT NULL,
    charges NUMERIC(10, 2) NOT NULL,
    net_pnl NUMERIC(12, 2) NOT NULL,
    pnl_pct NUMERIC(6, 2) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_supabase_trades_time ON public.paper_trades(entry_time DESC);

-- 4. Active Open Position State (Single active position tracked in real-time)
CREATE TABLE IF NOT EXISTS public.active_positions (
    id TEXT PRIMARY KEY DEFAULT 'CURRENT_ACTIVE_POSITION',
    trade_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    option_type VARCHAR(5) NOT NULL,
    strike INTEGER NOT NULL,
    lots INTEGER DEFAULT 1,
    qty INTEGER DEFAULT 65,
    entry_time TEXT NOT NULL,
    entry_spot NUMERIC(10, 2),
    entry_premium NUMERIC(10, 2) NOT NULL,
    current_premium NUMERIC(10, 2) NOT NULL,
    sl_price NUMERIC(10, 2) NOT NULL,
    target_price NUMERIC(10, 2) NOT NULL,
    mtm_pnl NUMERIC(12, 2) DEFAULT 0.0,
    status TEXT DEFAULT 'OPEN',
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- 5. Custom Level Triggers Table
CREATE TABLE IF NOT EXISTS public.level_triggers (
    trigger_id TEXT PRIMARY KEY,
    instrument TEXT NOT NULL,
    trigger_price NUMERIC(10, 2) NOT NULL,
    condition TEXT NOT NULL,
    option_type VARCHAR(5) NOT NULL,
    strike_mode TEXT DEFAULT 'ATM',
    sl_type TEXT DEFAULT 'POINTS',
    sl_val NUMERIC(10, 2) DEFAULT 20.0,
    target_type TEXT DEFAULT 'POINTS',
    target_val NUMERIC(10, 2) DEFAULT 40.0,
    lots INTEGER DEFAULT 1,
    status TEXT DEFAULT 'ARMED',
    created_at TEXT NOT NULL,
    triggered_at TEXT,
    executed_trade_id TEXT,
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_supabase_triggers_status ON public.level_triggers(status);

-- 6. AI Brain Reasoning History Table
CREATE TABLE IF NOT EXISTS public.brain_history (
    id BIGSERIAL PRIMARY KEY,
    timestamp TEXT NOT NULL,
    instrument TEXT NOT NULL,
    one_hour_bias TEXT,
    fifteen_minute_state TEXT,
    action TEXT,
    setup_status TEXT,
    market_context TEXT,
    reasoning JSONB,
    uncertainties JSONB,
    important_levels JSONB,
    confidence NUMERIC(4, 2),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- 7. High-Resolution Market Ticks Tables (Dedicated Per-Instrument Stores)
-- 7A. NIFTY 50 Dedicated Ticks Table
CREATE TABLE IF NOT EXISTS public.nifty_ticks (
    id BIGSERIAL PRIMARY KEY,
    timestamp_ist TEXT NOT NULL,
    timestamp_utc TEXT NOT NULL,
    symbol TEXT DEFAULT 'NIFTY',
    price NUMERIC(10, 2) NOT NULL,
    open NUMERIC(10, 2),
    high NUMERIC(10, 2),
    low NUMERIC(10, 2),
    close NUMERIC(10, 2),
    volume BIGINT DEFAULT 0,
    change_pts NUMERIC(10, 2) DEFAULT 0.0,
    change_pct NUMERIC(6, 2) DEFAULT 0.0,
    bid NUMERIC(10, 2) DEFAULT 0.0,
    ask NUMERIC(10, 2) DEFAULT 0.0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_supabase_nifty_ticks_time ON public.nifty_ticks(timestamp_ist DESC);
CREATE INDEX IF NOT EXISTS idx_supabase_nifty_ticks_created ON public.nifty_ticks(created_at DESC);

-- 7B. BANKNIFTY Dedicated Ticks Table
CREATE TABLE IF NOT EXISTS public.banknifty_ticks (
    id BIGSERIAL PRIMARY KEY,
    timestamp_ist TEXT NOT NULL,
    timestamp_utc TEXT NOT NULL,
    symbol TEXT DEFAULT 'BANKNIFTY',
    price NUMERIC(10, 2) NOT NULL,
    open NUMERIC(10, 2),
    high NUMERIC(10, 2),
    low NUMERIC(10, 2),
    close NUMERIC(10, 2),
    volume BIGINT DEFAULT 0,
    change_pts NUMERIC(10, 2) DEFAULT 0.0,
    change_pct NUMERIC(6, 2) DEFAULT 0.0,
    bid NUMERIC(10, 2) DEFAULT 0.0,
    ask NUMERIC(10, 2) DEFAULT 0.0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_supabase_bank_ticks_time ON public.banknifty_ticks(timestamp_ist DESC);
CREATE INDEX IF NOT EXISTS idx_supabase_bank_ticks_created ON public.banknifty_ticks(created_at DESC);

-- 7C. General / Global Market Ticks Table (e.g. GIFT NIFTY, INDIA VIX)
CREATE TABLE IF NOT EXISTS public.market_ticks (
    id BIGSERIAL PRIMARY KEY,
    timestamp_ist TEXT NOT NULL,
    timestamp_utc TEXT NOT NULL,
    symbol TEXT NOT NULL,
    price NUMERIC(10, 2) NOT NULL,
    open NUMERIC(10, 2),
    high NUMERIC(10, 2),
    low NUMERIC(10, 2),
    close NUMERIC(10, 2),
    volume BIGINT DEFAULT 0,
    change_pts NUMERIC(10, 2) DEFAULT 0.0,
    change_pct NUMERIC(6, 2) DEFAULT 0.0,
    bid NUMERIC(10, 2) DEFAULT 0.0,
    ask NUMERIC(10, 2) DEFAULT 0.0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_supabase_ticks_sym_time ON public.market_ticks(symbol, timestamp_ist DESC);
CREATE INDEX IF NOT EXISTS idx_supabase_ticks_created ON public.market_ticks(created_at DESC);

-- 8. NSE Option Chain Snapshots Table (Separate Dedicated Derivatives Store)
CREATE TABLE IF NOT EXISTS public.option_chain_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    timestamp_ist TEXT NOT NULL,
    timestamp_utc TEXT NOT NULL,
    symbol TEXT NOT NULL,
    expiry TEXT NOT NULL,
    spot_price NUMERIC(10, 2) NOT NULL,
    atm_strike NUMERIC(10, 2) NOT NULL,
    pcr NUMERIC(6, 2) NOT NULL,
    max_pain NUMERIC(10, 2),
    total_ce_oi BIGINT DEFAULT 0,
    total_pe_oi BIGINT DEFAULT 0,
    strikes_data JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_supabase_oc_sym_exp ON public.option_chain_snapshots(symbol, expiry, timestamp_ist DESC);
CREATE INDEX IF NOT EXISTS idx_supabase_oc_created ON public.option_chain_snapshots(created_at DESC);

-- ==============================================================================
-- ROW LEVEL SECURITY (RLS) POLICIES
-- ==============================================================================
-- Enable RLS and grant service/anon roles full read/write for API access.
ALTER TABLE public.market_news ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.nse_spot_data ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.paper_trades ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.active_positions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.level_triggers ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.brain_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.nifty_ticks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.banknifty_ticks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.market_ticks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.option_chain_snapshots ENABLE ROW LEVEL SECURITY;

-- Allow anon and service role to select, insert, update, and delete
DO $$
DECLARE
    tbl text;
BEGIN
    FOR tbl IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename IN (
        'market_news', 'nse_spot_data', 'paper_trades', 'active_positions', 'level_triggers', 'brain_history', 'nifty_ticks', 'banknifty_ticks', 'market_ticks', 'option_chain_snapshots'
    )
    LOOP
        EXECUTE format('DROP POLICY IF EXISTS "Public access policy" ON public.%I', tbl);
        EXECUTE format('CREATE POLICY "Public access policy" ON public.%I FOR ALL USING (true) WITH CHECK (true)', tbl);
    END LOOP;
END $$;
