"""
Redis Service Module for Finbot.

Handles all interactions with Redis (Upstash) including:
- Connection management with SSL
- Token caching (Angel One)
- Real-time market data caching (LTP)
- Rate limiting
- Job queue management (Backtesting)
"""

import json
import asyncio
from typing import Optional, Any, Union
from datetime import datetime, timedelta

import redis.asyncio as redis
from loguru import logger

from finbot.config import get_settings


class RedisService:
    """
    Async Redis service wrapper for Upstash/Production Redis.
    """
    _instance: Optional["RedisService"] = None
    _redis: Optional[redis.Redis] = None

    def __init__(self):
        self.settings = get_settings()
        self.prefix = "finbot:v1:"
    
    @classmethod
    def get_instance(cls) -> "RedisService":
        """Get singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def connect(self) -> None:
        """Initialize Redis connection pool."""
        if self._redis:
            return

        try:
            logger.info(f"Connecting to Redis at {self.settings.redis_url.split('@')[-1]}...")  # Log masked URL
            # from_url automatically handles SSL when URL uses rediss:// scheme
            self._redis = redis.from_url(
                self.settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_timeout=5.0,
                socket_connect_timeout=5.0,
            )
            await self._redis.ping()
            logger.info("✅ Redis connected successfully")
        except Exception as e:
            logger.error(f"❌ Redis connection failed: {e}")
            raise

    async def close(self) -> None:
        """Close Redis connection."""
        if self._redis:
            await self._redis.close()
            self._redis = None
            logger.info("Redis connection closed")

    def _key(self, key: str) -> str:
        """Get namespaced key."""
        return f"{self.prefix}{key}"

    # ==================== GENERIC METHODS ====================

    async def get(self, key: str) -> Optional[str]:
        """Get string value."""
        if not self._redis: await self.connect()
        return await self._redis.get(self._key(key))

    async def set(self, key: str, value: str, ttl: int = None) -> bool:
        """Set string value with optional TTL (seconds)."""
        if not self._redis: await self.connect()
        return await self._redis.set(self._key(key), value, ex=ttl)

    async def delete(self, key: str) -> bool:
        """Delete key."""
        if not self._redis: await self.connect()
        return await self._redis.delete(self._key(key)) > 0

    async def exists(self, key: str) -> bool:
        """Check if key exists."""
        if not self._redis: await self.connect()
        return await self._redis.exists(self._key(key)) > 0

    # ==================== TOKEN MANAGEMENT ====================

    async def cache_auth_tokens(self, data: dict, ttl: int = 86400) -> None:
        """
        Cache Angel One auth tokens.
        TTL defaults to 24 hours.
        """
        if not data:
            return
            
        pipeline = self._redis.pipeline()
        pipeline.set(self._key("auth:jwt"), data.get("jwtToken", ""), ex=ttl)
        pipeline.set(self._key("auth:feed"), data.get("feedToken", ""), ex=ttl)
        pipeline.set(self._key("auth:refresh"), data.get("refreshToken", ""), ex=ttl)
        
        # Store full user profile for quick lookup
        pipeline.set(self._key("auth:profile"), json.dumps(data), ex=ttl)
        
        await pipeline.execute()
        logger.debug("Auth tokens cached in Redis")

    async def get_auth_tokens(self) -> Optional[dict]:
        """Retrieve cached auth tokens."""
        if not self._redis: await self.connect()
        
        jwt = await self.get("auth:jwt")
        if not jwt:
            return None
            
        feed = await self.get("auth:feed")
        refresh = await self.get("auth:refresh")
        profile = await self.get("auth:profile")
        
        return {
            "jwtToken": jwt,
            "feedToken": feed,
            "refreshToken": refresh,
            "data": json.loads(profile) if profile else {}
        }

    # ==================== MARKET DATA CACHE ====================

    async def cache_ltp(self, symbol: str, token: str, price: float) -> None:
        """
        Cache Last Traded Price.
        TTL: 1 minute (ltp shouldn't be stale).
        """
        if not self._redis: await self.connect()
        await self.set(f"ltp:{symbol}:{token}", str(price), ttl=60)

    async def get_cached_ltp(self, symbol: str, token: str) -> Optional[float]:
        """Get cached LTP."""
        val = await self.get(f"ltp:{symbol}:{token}")
        return float(val) if val else None

    # ==================== RATE LIMITING ====================

    async def check_rate_limit(self, bucket: str, limit: int, window: int) -> bool:
        """
        Check if action is allowed within rate limit using sliding window.
        Returns True if allowed, False if limit exceeded.
        """
        if not self._redis: await self.connect()
        
        key = self._key(f"ratelimit:{bucket}")
        now = asyncio.get_event_loop().time()
        
        async with self._redis.pipeline(transaction=True) as pipe:
            # Remove old entries
            pipe.zremrangebyscore(key, 0, now - window)
            # Count current
            pipe.zcard(key)
            # Add new (timestamp as member and score)
            pipe.zadd(key, {str(now): now})
            # Set expiry on key
            pipe.expire(key, window)
            
            results = await pipe.execute()
            current_count = results[1]
            
            return current_count < limit

    # ==================== JOB QUEUE (BACKTEST) ====================

    async def register_job(self, job_id: str, data: dict) -> None:
        """Register a backtest job."""
        if not self._redis: await self.connect()
        # Initial status
        data["status"] = "pending"
        
        # Add to history list (keep last 50)
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.set(self._key(f"job:{job_id}"), json.dumps(data), ex=86400*7)
            pipe.lpush(self._key("jobs:history"), job_id)
            pipe.ltrim(self._key("jobs:history"), 0, 49)
            await pipe.execute()

    async def get_recent_jobs(self) -> list[dict]:
        """Get recent backtest jobs summary."""
        if not self._redis: await self.connect()
        
        # Get IDs
        job_ids = await self._redis.lrange(self._key("jobs:history"), 0, 49)
        if not job_ids:
            return []
            
        # Get details
        pipeline = self._redis.pipeline()
        for jid in job_ids:
            pipeline.get(self._key(f"job:{jid}"))
        
        results = await pipeline.execute()
        
        jobs = []
        for raw in results:
            if raw:
                try:
                    jobs.append(json.loads(raw))
                except:
                    pass
        return jobs

    async def update_job_status(
        self, 
        job_id: str, 
        status: str, 
        result: dict = None, 
        error: str = None,
        extra_data: dict = None
    ) -> None:
        """Update job status with optional extra data."""
        job_key = f"job:{job_id}"
        raw = await self.get(job_key.replace(self.prefix, "")) # .get handles prefix
        
        if not raw:
            logger.warning(f"Job {job_id} not found for update")
            return
            
        data = json.loads(raw)
        data["status"] = status
        if result:
            data["result"] = result
        if error:
            data["error"] = error
        if extra_data:
            data.update(extra_data)  # Merge extra data into job
            
        if status in ["completed", "failed"]:
            data["completed_at"] = datetime.now().isoformat()
            
        await self.set(job_key.replace(self.prefix, ""), json.dumps(data), ttl=86400*7)

    async def get_job(self, job_id: str) -> Optional[dict]:
        """Get job data."""
        raw = await self.get(f"job:{job_id}")
        return json.loads(raw) if raw else None

    async def update_job_progress(
        self, 
        job_id: str, 
        current_symbol: str,
        symbols_done: int,
        total_symbols: int
    ) -> None:
        """Update job progress without changing status."""
        job_key = f"job:{job_id}"
        raw = await self.get(job_key)
        
        if not raw:
            return
            
        data = json.loads(raw)
        
        # Don't update if job is already completed/failed/cancelled
        if data.get("status") in ["completed", "failed", "cancelled"]:
            return
        
        data["progress"] = {
            "current_symbol": current_symbol,
            "symbols_done": symbols_done,
            "total_symbols": total_symbols,
            "percentage": round((symbols_done / total_symbols) * 100, 1) if total_symbols > 0 else 0,
            "last_update": datetime.now().isoformat()
        }
        
        await self.set(job_key, json.dumps(data), ttl=86400*7)

    async def cancel_job(self, job_id: str) -> bool:
        """Cancel a running job."""
        job_key = f"job:{job_id}"
        raw = await self.get(job_key)
        
        if not raw:
            return False
            
        data = json.loads(raw)
        
        # Only cancel if running or pending
        if data.get("status") not in ["running", "pending"]:
            return False
        
        data["status"] = "cancelled"
        data["completed_at"] = datetime.now().isoformat()
        data["error"] = "Cancelled by user"
        
        await self.set(job_key, json.dumps(data), ttl=86400*7)
        return True


# Usage
redis_service = RedisService()
