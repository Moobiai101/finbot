"""EMA Pullback in Trend Strategy.

Trend-following strategy:
- Confirm strong trend with EMA alignment
- Wait for pullback to 21 EMA
- Enter on rejection from EMA
- Ride the trend continuation
"""

from finbot.data.market_state import MarketState
from finbot.strategies.base import BaseStrategy, Signal, SignalType


class EMAPullbackStrategy(BaseStrategy):
    """
    EMA Pullback Strategy.
    
    Setup conditions:
    1. Strong trend: 9 EMA > 21 EMA > 50 EMA (bullish) or reverse
    2. Price pulls back to 21 EMA
    3. RSI not extreme
    4. Rejection candle at 21 EMA
    """
    
    def __init__(
        self,
        ema_touch_threshold: float = 0.3,  # % distance from 21 EMA
        require_adx: bool = True,
        min_adx: float = 25,
        enabled: bool = True,
    ):
        """
        Initialize EMA Pullback strategy.
        
        Args:
            ema_touch_threshold: Max distance from 21 EMA (%)
            require_adx: Whether to require strong ADX
            min_adx: Minimum ADX for trending confirmation
        """
        super().__init__(enabled)
        self.ema_touch_threshold = ema_touch_threshold
        self.require_adx = require_adx
        self.min_adx = min_adx
    
    @property
    def name(self) -> str:
        return "EMA_PULLBACK"
    
    @property
    def description(self) -> str:
        return "EMA Pullback - Trade pullbacks to 21 EMA in trending markets"
    
    def evaluate(self, state: MarketState) -> Signal:
        """Evaluate for EMA pullback setup."""
        if not self.enabled:
            return self._hold_signal(state, "Strategy disabled")
        
        # Need all EMAs
        ema9 = state.indicators.ema_9
        ema21 = state.indicators.ema_21
        ema50 = state.indicators.ema_50
        
        if not all([ema9, ema21, ema50]):
            return self._hold_signal(state, "EMAs not available")
        
        # Check EMA alignment
        alignment = state.ema_alignment()
        
        if alignment == 'mixed':
            return self._hold_signal(state, "No clear trend (EMAs mixed)")
        
        # Check ADX for trend strength
        if self.require_adx:
            adx = state.indicators.adx
            if adx is None or adx < self.min_adx:
                return self._hold_signal(
                    state, 
                    f"Weak trend (ADX: {adx:.1f})" if adx else "ADX not available"
                )
        
        price = state.current_price
        
        # Calculate distance from 21 EMA
        ema21_distance = abs(price - ema21) / ema21 * 100
        
        # Bullish setup
        if alignment == 'bullish':
            # Price should be near or touching 21 EMA from above
            if ema21_distance > self.ema_touch_threshold:
                return self._hold_signal(
                    state, 
                    f"Price not at 21 EMA: {ema21_distance:.2f}% away"
                )
            
            # Price should be between 21 and 9 EMA (pullback)
            if price < ema21 * 0.997:  # Allow slight overshoot
                return self._hold_signal(state, "Price broke below 21 EMA")
            
            if price > ema9:
                return self._hold_signal(state, "Price above 9 EMA - wait for pullback")
            
            # Look for bullish candle
            df = state.to_dataframe_5m()
            if len(df) >= 1:
                last_candle = df.iloc[-1]
                
                if last_candle['close'] > last_candle['open']:
                    # Bullish candle near 21 EMA
                    stop_loss = min(ema50, last_candle['low'] * 0.995)
                    
                    return self._create_signal(
                        signal_type=SignalType.LONG,
                        state=state,
                        confidence=0.70,
                        reason=f"EMA Pullback Long: Bounce from 21 EMA ({ema21:.2f})",
                        stop_loss=stop_loss,
                    )
        
        # Bearish setup
        elif alignment == 'bearish':
            # Price should be near or touching 21 EMA from below
            if ema21_distance > self.ema_touch_threshold:
                return self._hold_signal(
                    state, 
                    f"Price not at 21 EMA: {ema21_distance:.2f}% away"
                )
            
            # Price should be between 21 and 9 EMA (pullback)
            if price > ema21 * 1.003:  # Allow slight overshoot
                return self._hold_signal(state, "Price broke above 21 EMA")
            
            if price < ema9:
                return self._hold_signal(state, "Price below 9 EMA - wait for pullback")
            
            # Look for bearish candle
            df = state.to_dataframe_5m()
            if len(df) >= 1:
                last_candle = df.iloc[-1]
                
                if last_candle['close'] < last_candle['open']:
                    # Bearish candle near 21 EMA
                    stop_loss = max(ema50, last_candle['high'] * 1.005)
                    
                    return self._create_signal(
                        signal_type=SignalType.SHORT,
                        state=state,
                        confidence=0.70,
                        reason=f"EMA Pullback Short: Rejection from 21 EMA ({ema21:.2f})",
                        stop_loss=stop_loss,
                    )
        
        return self._hold_signal(state, "No EMA pullback setup")
