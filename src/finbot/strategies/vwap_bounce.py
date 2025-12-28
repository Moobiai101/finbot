"""VWAP Bounce Strategy.

Mean reversion strategy for trending markets:
- Price pulls back to VWAP
- RSI not extreme
- Trend is intact (EMA alignment)
- Rejection candle forms at VWAP
"""

from finbot.data.market_state import MarketState
from finbot.strategies.base import BaseStrategy, Signal, SignalType


class VWAPBounceStrategy(BaseStrategy):
    """
    VWAP Bounce Strategy.
    
    Setup conditions:
    1. Price is in a trend (EMA aligned)
    2. Price pulls back to VWAP
    3. RSI is not oversold/overbought (30-70)
    4. Rejection candle at VWAP
    """
    
    def __init__(
        self,
        vwap_threshold: float = 0.3,  # % distance from VWAP
        min_rsi: float = 30,
        max_rsi: float = 70,
        enabled: bool = True,
    ):
        """
        Initialize VWAP Bounce strategy.
        
        Args:
            vwap_threshold: Max distance from VWAP to trigger (%)
            min_rsi: Minimum RSI (avoid oversold shorts)
            max_rsi: Maximum RSI (avoid overbought longs)
        """
        super().__init__(enabled)
        self.vwap_threshold = vwap_threshold
        self.min_rsi = min_rsi
        self.max_rsi = max_rsi
    
    @property
    def name(self) -> str:
        return "VWAP_BOUNCE"
    
    @property
    def description(self) -> str:
        return "VWAP Bounce - Trade pullbacks to VWAP in trending markets"
    
    def evaluate(self, state: MarketState) -> Signal:
        """Evaluate for VWAP bounce setup."""
        if not self.enabled:
            return self._hold_signal(state, "Strategy disabled")
        
        # Need VWAP
        if not state.indicators.vwap:
            return self._hold_signal(state, "VWAP not available")
        
        vwap = state.indicators.vwap
        price = state.current_price
        
        # Calculate distance from VWAP
        vwap_distance = abs(price - vwap) / vwap * 100
        
        # Check if near VWAP
        if vwap_distance > self.vwap_threshold:
            return self._hold_signal(
                state, 
                f"Too far from VWAP: {vwap_distance:.2f}%"
            )
        
        # Check trend (EMA alignment)
        ema_alignment = state.ema_alignment()
        
        if ema_alignment == 'mixed':
            return self._hold_signal(state, "No clear trend (EMAs mixed)")
        
        # Check RSI
        rsi = state.indicators.rsi_14
        if rsi is None:
            return self._hold_signal(state, "RSI not available")
        
        # Long setup
        if ema_alignment == 'bullish':
            # Price should be at or below VWAP
            if price > vwap:
                return self._hold_signal(state, "Price above VWAP - wait for pullback")
            
            # RSI check
            if rsi < self.min_rsi:
                return self._hold_signal(state, f"RSI too low: {rsi:.1f}")
            
            # Look for bullish rejection
            df = state.to_dataframe_5m()
            if len(df) >= 2:
                last_candle = df.iloc[-1]
                prev_candle = df.iloc[-2]
                
                # Current candle is bullish and closed above previous low
                if last_candle['close'] > last_candle['open'] and \
                   last_candle['low'] >= prev_candle['low'] * 0.998:
                    
                    stop_loss = min(last_candle['low'], vwap * 0.995)
                    target = state.prev_day_high if state.prev_day_high else price * 1.02
                    
                    return self._create_signal(
                        signal_type=SignalType.LONG,
                        state=state,
                        confidence=0.70,
                        reason=f"VWAP Bounce Long: Rejection at {vwap:.2f}",
                        stop_loss=stop_loss,
                        target=target,
                    )
        
        # Short setup
        elif ema_alignment == 'bearish':
            # Price should be at or above VWAP
            if price < vwap:
                return self._hold_signal(state, "Price below VWAP - wait for pullback")
            
            # RSI check
            if rsi > self.max_rsi:
                return self._hold_signal(state, f"RSI too high: {rsi:.1f}")
            
            # Look for bearish rejection
            df = state.to_dataframe_5m()
            if len(df) >= 2:
                last_candle = df.iloc[-1]
                prev_candle = df.iloc[-2]
                
                # Current candle is bearish and closed below previous high
                if last_candle['close'] < last_candle['open'] and \
                   last_candle['high'] <= prev_candle['high'] * 1.002:
                    
                    stop_loss = max(last_candle['high'], vwap * 1.005)
                    target = state.prev_day_low if state.prev_day_low else price * 0.98
                    
                    return self._create_signal(
                        signal_type=SignalType.SHORT,
                        state=state,
                        confidence=0.70,
                        reason=f"VWAP Bounce Short: Rejection at {vwap:.2f}",
                        stop_loss=stop_loss,
                        target=target,
                    )
        
        return self._hold_signal(state, "No VWAP bounce setup")
