"""Opening Range Breakout (ORB) Strategy.

One of the most popular intraday strategies:
- Wait for 9:15-9:30 to form the opening range
- Enter when price breaks above/below the range with volume
- Stop loss at opposite side of range
- Target 1.5-2x the range size
"""

from datetime import datetime, time
from finbot.data.market_state import MarketState, OpeningRange
from finbot.strategies.base import BaseStrategy, Signal, SignalType


class ORBStrategy(BaseStrategy):
    """
    Opening Range Breakout Strategy.
    
    Setup conditions:
    1. Market forms opening range (9:15-9:30)
    2. Price breaks above/below range
    3. Volume is above average
    4. Confirmation candle closes outside range
    """
    
    def __init__(
        self,
        range_minutes: int = 15,
        volume_multiplier: float = 1.5,
        min_range_percent: float = 0.3,
        max_range_percent: float = 2.0,
        enabled: bool = True,
    ):
        """
        Initialize ORB strategy.
        
        Args:
            range_minutes: Minutes to form opening range (default 15)
            volume_multiplier: Required volume vs average (default 1.5x)
            min_range_percent: Minimum range size (default 0.3%)
            max_range_percent: Maximum range size (default 2.0%)
        """
        super().__init__(enabled)
        self.range_minutes = range_minutes
        self.volume_multiplier = volume_multiplier
        self.min_range_percent = min_range_percent
        self.max_range_percent = max_range_percent
    
    @property
    def name(self) -> str:
        return "ORB"
    
    @property
    def description(self) -> str:
        return "Opening Range Breakout - Trade breakouts of the first 15-min range"
    
    def evaluate(self, state: MarketState) -> Signal:
        """Evaluate for ORB setup."""
        if not self.enabled:
            return self._hold_signal(state, "Strategy disabled")
        
        # Check if we have opening range
        if not state.opening_range:
            return self._hold_signal(state, "Opening range not formed yet")
        
        orb = state.opening_range
        orb_range = orb.high - orb.low
        range_percent = (orb_range / orb.low) * 100
        
        # Check range size
        if range_percent < self.min_range_percent:
            return self._hold_signal(state, f"Range too small: {range_percent:.2f}%")
        
        if range_percent > self.max_range_percent:
            return self._hold_signal(state, f"Range too large: {range_percent:.2f}%")
        
        # Check for breakout
        breakout = state.is_orb_breakout()
        
        if not breakout:
            return self._hold_signal(state, "No breakout yet")
        
        # Check volume
        if state.volume_ratio < self.volume_multiplier:
            return self._hold_signal(
                state, 
                f"Volume too low: {state.volume_ratio:.1f}x (need {self.volume_multiplier}x)"
            )
        
        # Calculate levels
        if breakout == 'long':
            stop_loss = orb.low
            target = state.current_price + (orb_range * 1.5)
            reason = f"ORB Long: Broke {orb.high:.2f}, SL {stop_loss:.2f}"
            
            return self._create_signal(
                signal_type=SignalType.LONG,
                state=state,
                confidence=0.75,
                reason=reason,
                stop_loss=stop_loss,
                target=target,
            )
        
        else:  # short
            stop_loss = orb.high
            target = state.current_price - (orb_range * 1.5)
            reason = f"ORB Short: Broke {orb.low:.2f}, SL {stop_loss:.2f}"
            
            return self._create_signal(
                signal_type=SignalType.SHORT,
                state=state,
                confidence=0.75,
                reason=reason,
                stop_loss=stop_loss,
                target=target,
            )
