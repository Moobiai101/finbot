"""Configuration management using pydantic-settings with Supabase integration."""

from enum import Enum
from functools import lru_cache
from typing import Optional, List
import os

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class TradingMode(str, Enum):
    """Trading mode enumeration."""
    PAPER = "paper"
    LIVE = "live"
    BACKTEST = "backtest"
    
    @classmethod
    def _missing_(cls, value: object):
        """Handle case-insensitive enum lookup."""
        if isinstance(value, str):
            lower_value = value.lower()
            for member in cls:
                if member.value == lower_value:
                    return member
        return None


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Supabase
    supabase_url: str = Field(..., description="Supabase project URL")
    supabase_key: SecretStr = Field(..., description="Supabase anon key")
    supabase_service_key: SecretStr = Field(..., description="Supabase service role key")

    # Angel One Broker
    angel_api_key: SecretStr = Field(..., description="Angel One API key")
    angel_client_id: str = Field(..., description="Angel One client ID")
    angel_password: SecretStr = Field(..., description="Angel One PIN")
    angel_totp_secret: SecretStr = Field(..., description="TOTP secret for 2FA")

    # Redis
    redis_url: str = Field(default="redis://localhost:6379", description="Redis URL")

    # Data Configuration
    backtest_data_dir: str = Field(default="data/historical", description="Directory for historical data cache")

    # Trading Configuration
    trading_mode: TradingMode = Field(
        default=TradingMode.PAPER, description="Trading mode"
    )
    trading_capital: float = Field(default=15000.0, description="Trading capital in INR")

    # Risk Parameters
    max_risk_per_trade: float = Field(
        default=0.01, description="Maximum risk per trade (1%)"
    )
    max_daily_loss: float = Field(
        default=0.03, description="Maximum daily loss (3%)"
    )
    max_positions: int = Field(default=1, description="Maximum concurrent positions")
    leverage: float = Field(default=5.0, description="Broker leverage")
    effective_leverage: float = Field(
        default=3.0, description="Effective leverage to use"
    )

    # Trading Hours (IST)
    market_open: str = Field(default="09:15", description="Market open time")
    entry_cutoff: str = Field(default="14:30", description="No new entries after")
    square_off_time: str = Field(default="15:15", description="Square off all positions")
    market_close: str = Field(default="15:30", description="Market close time")

    # Logging
    log_level: str = Field(default="INFO", description="Logging level")

    # API Configuration
    api_host: str = Field(default="0.0.0.0", description="API host")
    port: int = Field(default=8000, description="API port (Railway sets PORT env var)")
    
    # CORS - comma-separated list of allowed origins
    cors_origins: str = Field(
        default="http://localhost:5173,http://localhost:3000",
        description="Comma-separated list of allowed CORS origins"
    )
    
    # Frontend URL (for redirects, etc.)
    frontend_url: str = Field(
        default="http://localhost:5173",
        description="Frontend URL"
    )
    
    @property
    def cors_origins_list(self) -> List[str]:
        """Parse CORS origins into a list."""
        origins = [o.strip() for o in self.cors_origins.split(",") if o.strip()]
        # Always allow Railway and Cloudflare patterns
        patterns = ["https://*.railway.app", "https://*.pages.dev"]
        return origins + patterns
    
    @property
    def max_position_value(self) -> float:
        """Calculate maximum position value with leverage."""
        return self.trading_capital * self.effective_leverage

    @property
    def max_loss_per_trade(self) -> float:
        """Calculate maximum loss amount per trade."""
        return self.trading_capital * self.max_risk_per_trade

    @property
    def max_daily_loss_amount(self) -> float:
        """Calculate maximum daily loss amount."""
        return self.trading_capital * self.max_daily_loss


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
