"""Supabase client for database and auth operations."""

from functools import lru_cache
from typing import Optional

from loguru import logger
from supabase import create_client, Client

from finbot.config import get_settings


@lru_cache
def get_supabase_client() -> Client:
    """Get cached Supabase client instance."""
    settings = get_settings()
    
    client = create_client(
        settings.supabase_url,
        settings.supabase_key.get_secret_value(),
    )
    
    logger.debug("Supabase client initialized")
    return client


def get_service_client() -> Client:
    """Get Supabase client with service role key for admin operations."""
    settings = get_settings()
    
    return create_client(
        settings.supabase_url,
        settings.supabase_service_key.get_secret_value(),
    )


class SupabaseDB:
    """Database operations wrapper for Supabase."""
    
    def __init__(self, client: Optional[Client] = None):
        self.client = client or get_supabase_client()
    
    # ==================== TRADES ====================
    
    async def insert_trade(self, trade_data: dict) -> dict:
        """Insert a new trade record."""
        result = self.client.table("trades").insert(trade_data).execute()
        logger.info(f"Trade inserted: {result.data[0]['id']}")
        return result.data[0]
    
    async def get_trades(
        self,
        mode: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list:
        """Get trades with optional filtering."""
        query = self.client.table("trades").select("*")
        
        if mode:
            query = query.eq("mode", mode)
        
        query = query.order("created_at", desc=True).limit(limit).offset(offset)
        result = query.execute()
        
        return result.data
    
    async def get_today_trades(self, mode: str = "paper") -> list:
        """Get today's trades."""
        from datetime import datetime, timezone
        
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        
        result = (
            self.client.table("trades")
            .select("*")
            .eq("mode", mode)
            .gte("created_at", f"{today}T00:00:00")
            .order("created_at", desc=True)
            .execute()
        )
        
        return result.data
    
    async def update_trade(self, trade_id: str, data: dict) -> dict:
        """Update an existing trade."""
        result = (
            self.client.table("trades")
            .update(data)
            .eq("id", trade_id)
            .execute()
        )
        return result.data[0] if result.data else {}
    
    # ==================== SYSTEM CONFIG ====================
    
    async def get_config(self, key: str) -> Optional[dict]:
        """Get a system configuration value."""
        result = (
            self.client.table("system_config")
            .select("value")
            .eq("key", key)
            .limit(1)
            .execute()
        )
        return result.data[0].get("value") if result.data else None

    async def set_config(self, key: str, value: dict) -> None:
        """Set a system configuration value (upsert)."""
        self.client.table("system_config").upsert({
            "key": key,
            "value": value,
        }).execute()
        logger.debug(f"Config updated: {key}")

    async def get_trading_mode(self) -> str:
        """Get current trading mode."""
        settings = get_settings()
        config = await self.get_config("trading_mode")
        return config.get("mode") if config else settings.trading_mode.value

    async def set_trading_mode(self, mode: str) -> None:
        """Set trading mode."""
        await self.set_config("trading_mode", {"mode": mode})
        logger.info(f"Trading mode set to: {mode}")

    # ==================== AUDIT LOG ====================

    async def log_action(
        self,
        action: str,
        details: Optional[dict] = None,
        user_id: Optional[str] = None,
    ) -> None:
        """Log an admin action for audit trail."""
        self.client.table("audit_log").insert({
            "user_id": user_id,
            "action": action,
            "details": details or {},
        }).execute()

    # ==================== CANDLES (Historical Data) ====================

    async def save_candles(self, symbol: str, timeframe: str, candles: list) -> None:
        """Save historical candle data."""
        records = [
            {
                "symbol": symbol,
                "timeframe": timeframe,
                **candle,
            }
            for candle in candles
        ]
        
        self.client.table("candles").upsert(
            records, on_conflict="symbol,timeframe,timestamp"
        ).execute()

    async def get_candles(
        self,
        symbol: str,
        timeframe: str,
        from_date: str,
        to_date: str,
    ) -> list:
        """Get historical candle data."""
        result = (
            self.client.table("candles")
            .select("*")
            .eq("symbol", symbol)
            .eq("timeframe", timeframe)
            .gte("timestamp", from_date)
            .lte("timestamp", to_date)
            .order("timestamp")
            .execute()
        )
        return result.data

    # ==================== LEVELS (S/R, Pivots) ====================

    async def save_levels(self, symbol: str, levels: dict) -> None:
        """Save computed support/resistance levels."""
        self.client.table("levels").upsert({
            "symbol": symbol,
            "data": levels,
        }, on_conflict="symbol").execute()

    async def get_levels(self, symbol: str) -> Optional[dict]:
        """Get computed levels for a symbol."""
        result = (
            self.client.table("levels")
            .select("data")
            .eq("symbol", symbol)
            .limit(1)
            .execute()
        )
        return result.data[0].get("data") if result.data else None

    # ==================== BACKTEST RESULTS ====================

    async def create_backtest_run(
        self,
        start_date: str,
        end_date: str,
        initial_capital: float,
        symbols: list[str],
    ) -> str:
        """Create a new backtest run and return its ID."""
        result = self.client.table("backtest_runs").insert({
            "start_date": start_date,
            "end_date": end_date,
            "initial_capital": initial_capital,
            "symbols": symbols,
            "status": "running",
        }).execute()
        
        run_id = result.data[0]["id"]
        logger.info(f"Created backtest run: {run_id}")
        return run_id

    async def update_backtest_run(
        self,
        run_id: str,
        status: str,
        final_capital: float = None,
        summary: dict = None,
        strategy_breakdown: dict = None,
        symbol_breakdown: dict = None,
    ) -> None:
        """Update backtest run with results."""
        update_data = {"status": status}
        
        if final_capital is not None:
            update_data["final_capital"] = final_capital
        if summary is not None:
            update_data["summary"] = summary
        if strategy_breakdown is not None:
            update_data["strategy_breakdown"] = strategy_breakdown
        if symbol_breakdown is not None:
            update_data["symbol_breakdown"] = symbol_breakdown
        
        self.client.table("backtest_runs").update(update_data).eq("id", run_id).execute()
        logger.info(f"Updated backtest run {run_id}: {status}")

    async def save_backtest_trades(self, run_id: str, trades: list[dict]) -> None:
        """Bulk insert backtest trades."""
        if not trades:
            return
        
        # Add run_id to each trade
        records = [{**trade, "run_id": run_id} for trade in trades]
        
        # Insert in batches of 100 to avoid payload limits
        batch_size = 100
        for i in range(0, len(records), batch_size):
            batch = records[i:i + batch_size]
            self.client.table("backtest_trades").insert(batch).execute()
        
        logger.info(f"Saved {len(trades)} trades for run {run_id}")

    async def get_backtest_run(self, run_id: str) -> Optional[dict]:
        """Get a backtest run by ID."""
        result = (
            self.client.table("backtest_runs")
            .select("*")
            .eq("id", run_id)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    async def get_backtest_trades(
        self,
        run_id: str,
        strategy: str = None,
        symbol: str = None,
        limit: int = 1000,
    ) -> list[dict]:
        """Get trades for a backtest run with optional filtering."""
        query = (
            self.client.table("backtest_trades")
            .select("*")
            .eq("run_id", run_id)
        )
        
        if strategy:
            query = query.eq("strategy", strategy)
        if symbol:
            query = query.eq("symbol", symbol)
        
        query = query.order("entry_time").limit(limit)
        result = query.execute()
        
        return result.data

    async def get_recent_backtest_runs(self, limit: int = 10) -> list[dict]:
        """Get recent backtest runs."""
        result = (
            self.client.table("backtest_runs")
            .select("id, created_at, start_date, end_date, initial_capital, final_capital, status, summary")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data


# Singleton instance
_db: Optional[SupabaseDB] = None


def get_db() -> SupabaseDB:
    """Get SupabaseDB singleton instance."""
    global _db
    if _db is None:
        # Use service client for backend operations to bypass RLS
        _db = SupabaseDB(client=get_service_client())
    return _db
