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


# Singleton instance
_db: Optional[SupabaseDB] = None


def get_db() -> SupabaseDB:
    """Get SupabaseDB singleton instance."""
    global _db
    if _db is None:
        # Use service client for backend operations to bypass RLS
        _db = SupabaseDB(client=get_service_client())
    return _db
