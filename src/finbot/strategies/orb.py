"""Opening Range Breakout (ORB) Strategy.

One of the most popular intraday strategies (used by Crabel Capital):
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
        volume_multiplier: float = 1.3,  # Reduced from 1.5 (hedge fund: 1.3-1.5x)
        min_range_percent: float = 0.2,  # Reduced from 0.3 (more opportunities)
        max_range_percent: float = 1.5,  # Reduced from 2.0 (avoid wide volatile ranges)
        enabled: bool = True,
    ):
        """
        Initialize ORB strategy.
        
        Args:
            range_minutes: Minutes to form opening range (default 15)
            volume_multiplier: Required volume vs average (default 1.3x)
            min_range_percent: Minimum range size (default 0.2%)
            max_range_percent: Maximum range size (default 1.5%)
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
    
    def _calculate_confidence(self, range_percent: float, volume_ratio: float) -> float:
        """
        Calculate dynamic confidence based on breakout quality.
        
        Base: 0.60, Max: 0.85
        """
        base = 0.60
        
        # Range quality: 0.5-1.0% is ideal (not too small, not too large)
        if 0.5 <= range_percent <= 1.0:
            range_score = 0.12
        elif 0.3 <= range_percent <= 1.3:
            range_score = 0.08
        else:
            range_score = 0.04
        
        # Volume confirmation: higher volume = stronger breakout
        if volume_ratio >= 2.0:
            volume_score = 0.12
        elif volume_ratio >= 1.5:
            volume_score = 0.08
        else:
            volume_score = 0.04
        
        return min(0.85, max(0.55, base + range_score + volume_score))
    
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
        
        # Check volume (more lenient check)
        if state.volume_ratio < self.volume_multiplier:
            return self._hold_signal(
                state, 
                f"Volume too low: {state.volume_ratio:.1f}x (need {self.volume_multiplier}x)"
            )
        
        # Calculate dynamic confidence
        confidence = self._calculate_confidence(range_percent, state.volume_ratio)
        
        # Calculate levels
        if breakout == 'long':
            stop_loss = orb.low
            target = state.current_price + (orb_range * 1.5)
            reason = f"ORB Long: Broke {orb.high:.2f}, Range:{range_percent:.1f}%, Vol:{state.volume_ratio:.1f}x"
            
            return self._create_signal(
                signal_type=SignalType.LONG,
                state=state,
                confidence=confidence,
                reason=reason,
                stop_loss=stop_loss,
                target=target,
            )
        
        else:  # short
            stop_loss = orb.high
            target = state.current_price - (orb_range * 1.5)
            reason = f"ORB Short: Broke {orb.low:.2f}, Range:{range_percent:.1f}%, Vol:{state.volume_ratio:.1f}x"
            
            return self._create_signal(
                signal_type=SignalType.SHORT,
                state=state,
                confidence=confidence,
                reason=reason,
                stop_loss=stop_loss,
                target=target,
            )

