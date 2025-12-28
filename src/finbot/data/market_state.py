"""Market state dataclass for strategy evaluation."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import pandas as pd

from finbot.data.indicators import IndicatorValues


@dataclass
class Candle:
    """OHLCV candle."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass
class OpeningRange:
    """Opening range for ORB strategy."""
    high: float
    low: float
    formed_at: datetime
    broken_up: bool = False
    broken_down: bool = False


@dataclass
class MarketState:
    """
    Complete market state for strategy evaluation.
    
    Contains all data needed for strategies to make decisions:
    - Current price and candles
    - Technical indicators
    - Key levels (S/R, pivots, previous day)
    - Opening range data
    - Trend context
    """
    
    # Symbol info
    symbol: str
    token: str
    exchange: str
    
    # Current data
    current_price: float
    current_time: datetime
    
    # Candle data
    candles_1m: list[Candle] = field(default_factory=list)
    candles_5m: list[Candle] = field(default_factory=list)
    candles_15m: list[Candle] = field(default_factory=list)
    
    # Technical indicators
    indicators: IndicatorValues = field(default_factory=IndicatorValues)
    
    # Previous day levels
    prev_day_high: Optional[float] = None
    prev_day_low: Optional[float] = None
    prev_day_close: Optional[float] = None
    
    # Support/Resistance levels
    support_levels: list[float] = field(default_factory=list)
    resistance_levels: list[float] = field(default_factory=list)
    
    # Pivot points
    pivot_pp: Optional[float] = None
    pivot_r1: Optional[float] = None
    pivot_r2: Optional[float] = None
    pivot_s1: Optional[float] = None
    pivot_s2: Optional[float] = None
    
    # Opening range (9:15 - 9:30)
    opening_range: Optional[OpeningRange] = None
    
    # Trend context
    trend: str = "SIDEWAYS"  # UP, DOWN, SIDEWAYS
    trend_strength: float = 0.0  # 0-100 based on ADX
    
    # Volume context
    volume_ratio: float = 1.0  # Current volume vs average
    
    # Market context
    nifty_trend: str = "SIDEWAYS"
    
    # Metadata
    last_updated: datetime = field(default_factory=datetime.now)
    
    def to_dataframe_1m(self) -> pd.DataFrame:
        """Convert 1m candles to DataFrame."""
        if not self.candles_1m:
            return pd.DataFrame()
        
        data = [{
            'timestamp': c.timestamp,
            'open': c.open,
            'high': c.high,
            'low': c.low,
            'close': c.close,
            'volume': c.volume,
        } for c in self.candles_1m]
        
        return pd.DataFrame(data)
    
    def to_dataframe_5m(self) -> pd.DataFrame:
        """Convert 5m candles to DataFrame."""
        if not self.candles_5m:
            return pd.DataFrame()
        
        data = [{
            'timestamp': c.timestamp,
            'open': c.open,
            'high': c.high,
            'low': c.low,
            'close': c.close,
            'volume': c.volume,
        } for c in self.candles_5m]
        
        return pd.DataFrame(data)
    
    def is_near_support(self, threshold_percent: float = 0.5) -> bool:
        """Check if price is near any support level."""
        for level in self.support_levels:
            distance_percent = abs(self.current_price - level) / level * 100
            if distance_percent <= threshold_percent:
                return True
        return False
    
    def is_near_resistance(self, threshold_percent: float = 0.5) -> bool:
        """Check if price is near any resistance level."""
        for level in self.resistance_levels:
            distance_percent = abs(self.current_price - level) / level * 100
            if distance_percent <= threshold_percent:
                return True
        return False
    
    def is_above_vwap(self) -> bool:
        """Check if price is above VWAP."""
        if self.indicators.vwap:
            return self.current_price > self.indicators.vwap
        return False
    
    def is_trending(self, min_adx: float = 25) -> bool:
        """Check if market is trending (ADX > threshold)."""
        if self.indicators.adx:
            return self.indicators.adx > min_adx
        return False
    
    def get_nearest_support(self) -> Optional[float]:
        """Get nearest support level below current price."""
        supports_below = [s for s in self.support_levels if s < self.current_price]
        return max(supports_below) if supports_below else None
    
    def get_nearest_resistance(self) -> Optional[float]:
        """Get nearest resistance level above current price."""
        resistances_above = [r for r in self.resistance_levels if r > self.current_price]
        return min(resistances_above) if resistances_above else None
    
    def is_orb_breakout(self) -> Optional[str]:
        """
        Check for Opening Range Breakout.
        
        Returns:
            'long' if broken above OR high
            'short' if broken below OR low
            None if no breakout
        """
        if not self.opening_range:
            return None
        
        if self.current_price > self.opening_range.high:
            return 'long'
        elif self.current_price < self.opening_range.low:
            return 'short'
        
        return None
    
    def ema_alignment(self) -> str:
        """
        Check EMA alignment for trend confirmation.
        
        Returns:
            'bullish' if 9 > 21 > 50
            'bearish' if 9 < 21 < 50
            'mixed' otherwise
        """
        ema9 = self.indicators.ema_9
        ema21 = self.indicators.ema_21
        ema50 = self.indicators.ema_50
        
        if not all([ema9, ema21, ema50]):
            return 'mixed'
        
        if ema9 > ema21 > ema50:
            return 'bullish'
        elif ema9 < ema21 < ema50:
            return 'bearish'
        
        return 'mixed'
    
    def rsi_zone(self) -> str:
        """
        Get RSI zone.
        
        Returns:
            'oversold' if RSI < 30
            'overbought' if RSI > 70
            'neutral' otherwise
        """
        rsi = self.indicators.rsi_14
        
        if not rsi:
            return 'neutral'
        
        if rsi < 30:
            return 'oversold'
        elif rsi > 70:
            return 'overbought'
        
        return 'neutral'
    
    def get_stop_loss(self, side: str, atr_multiplier: float = 1.5) -> Optional[float]:
        """
        Calculate stop loss based on ATR.
        
        Args:
            side: 'long' or 'short'
            atr_multiplier: Multiplier for ATR
            
        Returns:
            Stop loss price
        """
        atr = self.indicators.atr_14
        
        if not atr:
            # Fallback to 1.5% stop
            if side == 'long':
                return self.current_price * 0.985
            else:
                return self.current_price * 1.015
        
        if side == 'long':
            return self.current_price - (atr * atr_multiplier)
        else:
            return self.current_price + (atr * atr_multiplier)
    
    def get_target(self, side: str, risk_reward: float = 2.0, stop_loss: Optional[float] = None) -> Optional[float]:
        """
        Calculate target based on risk:reward ratio.
        
        Args:
            side: 'long' or 'short'
            risk_reward: Target R:R ratio
            stop_loss: Stop loss price (calculates if not provided)
            
        Returns:
            Target price
        """
        if not stop_loss:
            stop_loss = self.get_stop_loss(side)
        
        if not stop_loss:
            return None
        
        risk = abs(self.current_price - stop_loss)
        reward = risk * risk_reward
        
        if side == 'long':
            return self.current_price + reward
        else:
            return self.current_price - reward
