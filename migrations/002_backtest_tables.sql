-- Backtest Results Tables
-- Run this in Supabase SQL Editor

-- Table for backtest run summaries
CREATE TABLE IF NOT EXISTS backtest_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Run parameters
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    initial_capital NUMERIC NOT NULL,
    symbols JSONB NOT NULL DEFAULT '[]',
    
    -- Results
    final_capital NUMERIC,
    status TEXT DEFAULT 'running' CHECK (status IN ('running', 'completed', 'failed')),
    
    -- Summary metrics
    summary JSONB DEFAULT '{}',
    
    -- Per-strategy breakdown
    strategy_breakdown JSONB DEFAULT '{}',
    
    -- Per-symbol breakdown
    symbol_breakdown JSONB DEFAULT '{}'
);

-- Table for individual trades
CREATE TABLE IF NOT EXISTS backtest_trades (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES backtest_runs(id) ON DELETE CASCADE,
    
    -- Trade details
    symbol TEXT NOT NULL,
    strategy TEXT NOT NULL,
    signal_type TEXT NOT NULL CHECK (signal_type IN ('LONG', 'SHORT')),
    
    -- Timing
    entry_time TIMESTAMPTZ NOT NULL,
    exit_time TIMESTAMPTZ,
    
    -- Prices
    entry_price NUMERIC NOT NULL,
    exit_price NUMERIC,
    quantity INTEGER NOT NULL,
    
    -- Result
    pnl NUMERIC DEFAULT 0,
    pnl_percent NUMERIC DEFAULT 0,
    
    -- Signal info
    confidence NUMERIC,
    reason TEXT,
    
    -- Indexes for fast queries
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_backtest_trades_run_id ON backtest_trades(run_id);
CREATE INDEX IF NOT EXISTS idx_backtest_trades_strategy ON backtest_trades(strategy);
CREATE INDEX IF NOT EXISTS idx_backtest_trades_symbol ON backtest_trades(symbol);
CREATE INDEX IF NOT EXISTS idx_backtest_runs_created_at ON backtest_runs(created_at DESC);

-- Enable RLS but allow service role access
ALTER TABLE backtest_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE backtest_trades ENABLE ROW LEVEL SECURITY;

-- Policy to allow service role full access
CREATE POLICY "Service role has full access to backtest_runs" ON backtest_runs
    FOR ALL USING (true);

CREATE POLICY "Service role has full access to backtest_trades" ON backtest_trades
    FOR ALL USING (true);
