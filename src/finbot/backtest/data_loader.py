"""
Data Loader for Backtesting.

Handles fetching, caching, and loading historical data.
"""

import os
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from loguru import logger
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor

from finbot.config import get_settings
from finbot.broker.angel_client import get_angel_client, AngelOneClient, Candle
from finbot.services.redis_service import RedisService

class DataLoader:
    """
    Robust data loader with chunking and caching.
    """
    
    def __init__(self):
        self.settings = get_settings()
        self.client = get_angel_client()
        self.thread_pool = ThreadPoolExecutor(max_workers=2) # Limit concurrency
        
        self.cache_dir = Path(self.settings.backtest_data_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
    def _get_cache_path(self, symbol: str, interval: str) -> Path:
        return self.cache_dir / f"{symbol}_{interval}.parquet"

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
        """Fetch data in 30-day chunks to respect API limits."""
        all_candles = []
        current_start = start
        
        # Max chunk size (approx 30 days safe)
        CHUNK_DAYS = 30
        
        while current_start < end:
            chunk_end = min(current_start + timedelta(days=CHUNK_DAYS), end)
            
            # Avoid future dates
            if current_start > datetime.now():
                break
                
            logger.debug(f"  Fetching chunk: {current_start.date()} -> {chunk_end.date()}")
            
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
            else:
                logger.warning(f"  No data for chunk {current_start.date()} - {chunk_end.date()}")
            
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
