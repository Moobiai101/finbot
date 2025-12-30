"""Break and Retest Strategy.

Market structure based strategy used by institutional traders:
- Identify level breaks (support becomes resistance, vice versa)
- Wait for price to retest the broken level
- Enter on rejection from the level
- Target next major level
"""

from finbot.data.market_state import MarketState
from finbot.strategies.base import BaseStrategy, Signal, SignalType


class BreakRetestStrategy(BaseStrategy):
    """
    Break and Retest Strategy.
    
    Setup conditions:
    1. Key level is broken (support/resistance)
    2. Price retests the broken level
    3. Rejection candle forms at the level
    4. Volume confirms the move
    """
    
    def __init__(
        self,
        retest_threshold: float = 0.6,  # % distance from broken level (was 0.4%)
        volume_multiplier: float = 1.15,  # Reduced from 1.2 (more signals)
        enabled: bool = True,
    ):
        """
        Initialize Break Retest strategy.
        
        Args:
            retest_threshold: Max distance from level for retest (%)
            volume_multiplier: Required volume vs average
        """
        super().__init__(enabled)
        self.retest_threshold = retest_threshold
        self.volume_multiplier = volume_multiplier
        
        # Track broken levels
        self._broken_resistances: list[float] = []
        self._broken_supports: list[float] = []
    
    @property
    def name(self) -> str:
        return "BREAK_RETEST"
    
    @property
    def description(self) -> str:
        return "Break & Retest - Trade retests of broken support/resistance"
    
    def _calculate_confidence(self, volume_ratio: float, level_distance: float) -> float:
        """
        Calculate dynamic confidence based on retest quality.
        
        Base: 0.58, Max: 0.80
        """
        base = 0.58
        
        # Volume confirmation
        if volume_ratio >= 1.5:
            volume_score = 0.12
        elif volume_ratio >= 1.3:
            volume_score = 0.08
        else:
            volume_score = 0.04
        
        # Level proximity (closer = better)
        if level_distance <= 0.2:
            proximity_score = 0.10
        elif level_distance <= 0.4:
            proximity_score = 0.06
        else:
            proximity_score = 0.03
        
        return min(0.80, max(0.55, base + volume_score + proximity_score))
    
    def evaluate(self, state: MarketState) -> Signal:
        """Evaluate for break and retest setup."""
        if not self.enabled:
            return self._hold_signal(state, "Strategy disabled")
        
        price = state.current_price
        
        # Check for broken resistance becoming support (bullish)
        # Price above previous resistance, now retesting it
        for resistance in state.resistance_levels:
            if price < resistance:
                continue
            
            # Resistance is broken (price above it)
            distance = (price - resistance) / resistance * 100
            
            if distance <= self.retest_threshold:
                # Price is retesting the broken resistance
                
                # Look for bullish rejection
                df = state.to_dataframe_5m()
                if len(df) >= 2:
                    last_candle = df.iloc[-1]
                    
                    # Bullish candle with low near the level
                    if last_candle['close'] > last_candle['open']:
                        level_touch = abs(last_candle['low'] - resistance) / resistance * 100
                        
                        if level_touch <= self.retest_threshold:
                            # Check volume (more lenient)
                            if state.volume_ratio >= self.volume_multiplier:
                                confidence = self._calculate_confidence(state.volume_ratio, distance)
                                stop_loss = resistance * 0.99
                                target = state.get_nearest_resistance()
                                if not target or target <= price:
                                    target = price * 1.02
                                
                                return self._create_signal(
                                    signal_type=SignalType.LONG,
                                    state=state,
                                    confidence=confidence,
                                    reason=f"Break Retest Long: {resistance:.2f} now support, Vol:{state.volume_ratio:.1f}x",
                                    stop_loss=stop_loss,
                                    target=target,
                                )
        
        # Check for broken support becoming resistance (bearish)
        # Price below previous support, now retesting it
        for support in state.support_levels:
            if price > support:
                continue
            
            # Support is broken (price below it)
            distance = (support - price) / support * 100
            
            if distance <= self.retest_threshold:
                # Price is retesting the broken support
                
                # Look for bearish rejection
                df = state.to_dataframe_5m()
                if len(df) >= 2:
                    last_candle = df.iloc[-1]
                    
                    # Bearish candle with high near the level
                    if last_candle['close'] < last_candle['open']:
                        level_touch = abs(last_candle['high'] - support) / support * 100
                        
                        if level_touch <= self.retest_threshold:
                            # Check volume (more lenient)
                            if state.volume_ratio >= self.volume_multiplier:
                                confidence = self._calculate_confidence(state.volume_ratio, distance)
                                stop_loss = support * 1.01
                                target = state.get_nearest_support()
                                if not target or target >= price:
                                    target = price * 0.98
                                
                                return self._create_signal(
                                    signal_type=SignalType.SHORT,
                                    state=state,
                                    confidence=confidence,
                                    reason=f"Break Retest Short: {support:.2f} now resistance, Vol:{state.volume_ratio:.1f}x",
                                    stop_loss=stop_loss,
                                    target=target,
                                )
        
        return self._hold_signal(state, "No break and retest setup")

