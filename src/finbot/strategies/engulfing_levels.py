"""Engulfing at Key Levels Strategy.

Reversal strategy using candlestick patterns (50-70% accuracy):
- Identify key support/resistance levels
- Wait for price to reach these levels
- Look for engulfing pattern with volume
- Trade the reversal
"""

from finbot.data.market_state import MarketState
from finbot.data.indicators import IndicatorEngine
from finbot.strategies.base import BaseStrategy, Signal, SignalType


class EngulfingLevelsStrategy(BaseStrategy):
    """
    Engulfing at Key Levels Strategy.
    
    Setup conditions:
    1. Price near support or resistance level
    2. Bullish/bearish engulfing pattern forms
    3. Volume is above average
    4. RSI confirms (oversold for longs, overbought for shorts)
    """
    
    def __init__(
        self,
        level_threshold: float = 0.7,  # % distance from level (was 0.5%)
        volume_multiplier: float = 1.2,  # Reduced from 1.3 (more signals)
        enabled: bool = True,
    ):
        """
        Initialize Engulfing strategy.
        
        Args:
            level_threshold: Max distance from S/R level (%)
            volume_multiplier: Required volume vs average
        """
        super().__init__(enabled)
        self.level_threshold = level_threshold
        self.volume_multiplier = volume_multiplier
    
    @property
    def name(self) -> str:
        return "ENGULFING_LEVELS"
    
    @property
    def description(self) -> str:
        return "Engulfing at Levels - Trade reversals at support/resistance"
    
    def evaluate(self, state: MarketState) -> Signal:
        """Evaluate for engulfing setup at key levels."""
        if not self.enabled:
            return self._hold_signal(state, "Strategy disabled")
        
        # Need enough candle data
        df = state.to_dataframe_5m()
        if len(df) < 2:
            return self._hold_signal(state, "Not enough candle data")
        
        # Check for engulfing pattern
        engulfing = IndicatorEngine.detect_engulfing(df)
        
        if not engulfing:
            return self._hold_signal(state, "No engulfing pattern")
        
        price = state.current_price
        
        # Check volume (more lenient threshold)
        if state.volume_ratio < self.volume_multiplier:
            return self._hold_signal(
                state,
                f"Volume too low: {state.volume_ratio:.1f}x"
            )
        
        # Bullish engulfing at support
        if engulfing == 'bullish':
            near_support = state.is_near_support(self.level_threshold)
            
            if not near_support:
                return self._hold_signal(state, "Bullish engulfing but not at support")
            
            # Check RSI for oversold (tighter threshold)
            rsi = state.indicators.rsi_14
            confidence = 0.58
            if rsi and rsi < 35:
                confidence = 0.75  # Higher confidence if RSI oversold
            elif rsi and rsi < 45:
                confidence = 0.65
            
            # Get nearest support for stop
            support = state.get_nearest_support()
            stop_loss = support * 0.995 if support else price * 0.985
            
            # Target next resistance
            resistance = state.get_nearest_resistance()
            target = resistance if resistance else price * 1.02
            
            return self._create_signal(
                signal_type=SignalType.LONG,
                state=state,
                confidence=confidence,
                reason=f"Bullish Engulfing at support {support:.2f}, RSI:{rsi:.0f}" if rsi else f"Bullish Engulfing at support {support:.2f}",
                stop_loss=stop_loss,
                target=target,
            )
        
        # Bearish engulfing at resistance
        elif engulfing == 'bearish':
            near_resistance = state.is_near_resistance(self.level_threshold)
            
            if not near_resistance:
                return self._hold_signal(state, "Bearish engulfing but not at resistance")
            
            # Check RSI for overbought (tighter threshold)
            rsi = state.indicators.rsi_14
            confidence = 0.58
            if rsi and rsi > 65:
                confidence = 0.75  # Higher confidence if RSI overbought
            elif rsi and rsi > 55:
                confidence = 0.65
            
            # Get nearest resistance for stop
            resistance = state.get_nearest_resistance()
            stop_loss = resistance * 1.005 if resistance else price * 1.015
            
            # Target next support
            support = state.get_nearest_support()
            target = support if support else price * 0.98
            
            return self._create_signal(
                signal_type=SignalType.SHORT,
                state=state,
                confidence=confidence,
                reason=f"Bearish Engulfing at resistance {resistance:.2f}, RSI:{rsi:.0f}" if rsi else f"Bearish Engulfing at resistance {resistance:.2f}",
                stop_loss=stop_loss,
                target=target,
            )
        
        return self._hold_signal(state, "No setup")

