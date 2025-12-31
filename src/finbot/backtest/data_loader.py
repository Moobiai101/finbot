"""
Data Loader for Backtesting.

Handles fetching, caching, and loading historical data.
Includes automatic token refresh for long-running data fetches.
"""

import os
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from loguru import logger
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor

from finbot.config import get_settings
from finbot.broker.angel_client import get_angel_client, AngelOneClient, Candle
from finbot.services.redis_service import RedisService


class DataLoader:
    """
    Robust data loader with chunking, caching, and rate limiting.
    
    Rate Limits (Angel One):
    - Historical data API: 3 requests per second
    """
    
    # Rate limiting: 3 requests per second
    MIN_REQUEST_INTERVAL = 0.35  # seconds between requests (slightly > 1/3 for safety)
    _last_request_time: float = 0.0
    
    def __init__(self):
        self.settings = get_settings()
        self.client = get_angel_client()
        self.thread_pool = ThreadPoolExecutor(max_workers=2) # Limit concurrency
        
        self.cache_dir = Path(self.settings.backtest_data_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def _rate_limit(self):
        """Enforce rate limiting for API calls."""
        elapsed = time.time() - DataLoader._last_request_time
        if elapsed < self.MIN_REQUEST_INTERVAL:
            sleep_time = self.MIN_REQUEST_INTERVAL - elapsed
            time.sleep(sleep_time)
        DataLoader._last_request_time = time.time()
        
    def _get_cache_path(self, symbol: str, interval: str) -> Path:
        return self.cache_dir / f"{symbol}_{interval}.parquet"

    def _refresh_token_sync(self) -> bool:
        """
        Synchronously refresh the Angel One token.
        This handles token expiration during long-running data fetches.
        
        Returns:
            bool: True if refresh was successful, False otherwise.
        """
        try:
            logger.info("🔄 Attempting to refresh Angel One session...")
            
            # Get or create an event loop for the async operation
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            
            if loop and loop.is_running():
                # We're in an async context but need to run sync
                # Create a new thread to run the async login
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(self._run_async_login)
                    return future.result(timeout=60)
            else:
                # No event loop running, we can create one
                return asyncio.run(self._async_login())
                
        except Exception as e:
            logger.error(f"Token refresh failed: {e}")
            return False
    
    async def _async_login(self) -> bool:
        """Perform async login to refresh tokens."""
        try:
            # First try refresh_token, then fallback to full login
            if await self.client.refresh_token():
                logger.info("✅ Token refreshed via refresh_token()")
                return True
            
            # Fallback to full login
            await self.client.login()
            logger.info("✅ Token refreshed via full login()")
            return True
        except Exception as e:
            logger.error(f"Async login failed: {e}")
            return False
    
    def _run_async_login(self) -> bool:
        """Run async login in a new event loop (for thread context)."""
        return asyncio.run(self._async_login())

    def fetch_data(
        self,
        symbol: str,
        token: str,
        start_date: datetime,
        end_date: datetime,
        interval: str = "5m",
        force_refresh: bool = False
    ) -> pd.DataFrame:
        """
        Fetch data for a symbol. 
        1. Check cache.
        2. If missing/incomplete, fetch from API (chunked).
        3. Save to cache.
        """
        cache_path = self._get_cache_path(symbol, interval)
        
        existing_df = pd.DataFrame()
        if cache_path.exists() and not force_refresh:
            try:
                existing_df = pd.read_parquet(cache_path)
                logger.info(f"📂 Loaded cached data for {symbol} ({len(existing_df)} rows)")
                
                # Check if coverage is sufficient
                if not existing_df.empty:
                    # Convert index to datetime if needed
                    if 'timestamp' in existing_df.columns:
                        existing_df['timestamp'] = pd.to_datetime(existing_df['timestamp'])
                        existing_df.set_index('timestamp', inplace=True)
                    
                    cached_start = existing_df.index.min().to_pydatetime()
                    cached_end = existing_df.index.max().to_pydatetime()
                    
                    # Strip timezone info if present (normalize to naive datetime for comparison)
                    if cached_start.tzinfo is not None:
                        cached_start = cached_start.replace(tzinfo=None)
                    if cached_end.tzinfo is not None:
                        cached_end = cached_end.replace(tzinfo=None)
                    
                    # If request is within cache, return subset
                    if cached_start <= start_date and cached_end >= end_date:
                        mask = (existing_df.index >= start_date) & (existing_df.index <= end_date)
                        return existing_df.loc[mask]
                    
                    logger.info(f"Cache partial. Needed: {start_date} to {end_date}. Have: {cached_start} to {cached_end}")
                    # For simplicity in this v1, if cache miss, we re-fetch the whole requested range OR update.
                    # Merging logic is complex. We'll implement a 'fetch fresh' strategy for now if gaps exist.
            except Exception as e:
                logger.warning(f"Cache read error: {e}")
        
        # Fetch from API
        logger.info(f"🌐 Fetching API data for {symbol} ({start_date.date()} to {end_date.date()})...")
        df = self._fetch_chunked(symbol, token, start_date, end_date, interval)
        
        if not df.empty:
            # Save to cache
            save_df = df.reset_index() if not df.empty else df
            save_df.to_parquet(cache_path)
            logger.info(f"💾 Saved {len(df)} rows to {cache_path}")
            
        return df

    def _fetch_chunked(
        self, 
        symbol: str, 
        token: str, 
        start: datetime, 
        end: datetime, 
        interval: str
    ) -> pd.DataFrame:
        """
        Fetch data in 30-day chunks to respect API limits.
        Includes automatic token refresh on consecutive failures.
        """
        all_candles = []
        current_start = start
        
        # Max chunk size (approx 30 days safe)
        CHUNK_DAYS = 30
        
        # Track consecutive empty responses (may indicate token expiration)
        consecutive_empty = 0
        MAX_CONSECUTIVE_EMPTY_BEFORE_REFRESH = 3
        token_refreshed_this_symbol = False
        
        while current_start < end:
            chunk_end = min(current_start + timedelta(days=CHUNK_DAYS), end)
            
            # Avoid future dates
            if current_start > datetime.now():
                break
                
            logger.debug(f"  Fetching chunk: {current_start.date()} -> {chunk_end.date()}")
            
            # Rate limit: 3 requests per second max (Angel One limit)
            self._rate_limit()
            
            candles = self.client.get_historical_data(
                symbol=symbol,
                token=token,
                exchange="NSE",
                interval=interval,
                from_date=current_start,
                to_date=chunk_end
            )
            
            if candles:
                all_candles.extend(candles)
                consecutive_empty = 0  # Reset counter on success
            else:
                consecutive_empty += 1
                logger.warning(f"  No data for chunk {current_start.date()} - {chunk_end.date()} (consecutive empty: {consecutive_empty})")
                
                # If we get multiple consecutive empty responses, token may have expired
                if consecutive_empty >= MAX_CONSECUTIVE_EMPTY_BEFORE_REFRESH and not token_refreshed_this_symbol:
                    logger.warning(f"  🔐 Multiple consecutive empty responses - attempting token refresh...")
                    try:
                        # Try to re-authenticate
                        success = self._refresh_token_sync()
                        if success:
                            logger.info(f"  ✅ Token refreshed successfully - retrying from last failed chunk")
                            token_refreshed_this_symbol = True
                            consecutive_empty = 0
                            # Retry this chunk by not advancing current_start
                            continue
                        else:
                            logger.error(f"  ❌ Token refresh failed - continuing without data")
                    except Exception as e:
                        logger.error(f"  ❌ Token refresh error: {e}")
            
            # Rate limit sleep
            time.sleep(0.4) 
            
            current_start = chunk_end
            
        if not all_candles:
            return pd.DataFrame()
            
        # Convert to DataFrame
        data = [{
            'timestamp': c.timestamp,
            'open': c.open,
            'high': c.high,
            'low': c.low,
            'close': c.close,
            'volume': c.volume,
        } for c in all_candles]
        
        df = pd.DataFrame(data)
        df.set_index('timestamp', inplace=True)
        
        # Drop duplicates
        df = df[~df.index.duplicated(keep='first')]
        df.sort_index(inplace=True)
        
        return df

# Singleton
_loader: Optional[DataLoader] = None

def get_data_loader() -> DataLoader:
    global _loader
    if _loader is None:
        _loader = DataLoader()
    return _loader
