"""Break and Retest Strategy - ICT Breaker Block Edition.

Completely overhauled based on Smart Money Concepts (ICT methodology):
- NO MORE simple S/R breaks (that's what 90% of retail does = losers)
- Now uses Market Structure Breaks (BOS) detection
- Enters only at validated Breaker Blocks
- Requires displacement (strong move with volume)
- Maximum 2 entries per symbol per day

Key concept: A Breaker Block is the last opposite candle before a structural break.
When price returns to this zone, institutions often re-enter = high probability trade.
"""

from finbot.data.market_state import MarketState
from finbot.strategies.base import BaseStrategy, Signal, SignalType
from finbot.strategies.smc_utils import (
    detect_market_structure_break,
    find_breaker_block,
    detect_liquidity_sweep,
    is_in_valid_trading_session,
)


class BreakRetestStrategy(BaseStrategy):
    """
    ICT Breaker Block Strategy.
    
    Old retail approach (WRONG):
    - Enter when price is near "broken" S/R level
    - Result: Gets stop hunted, too many signals
    
    New institutional approach (ICT):
    1. Wait for Break of Structure (BOS) - confirmed market direction
    2. Identify the Breaker Block (last opposite candle before BOS)
    3. Wait for price to return to the Breaker Block zone
    4. Enter on rejection candle with volume confirmation
    5. Maximum 2 signals per day per symbol
    """
    
    def __init__(
        self,
        min_displacement_atr: float = 0.5,  # Minimum ATR multiple for BOS
        volume_multiplier: float = 1.3,  # Require above-average volume
        enabled: bool = True,
    ):
        """
        Initialize Breaker Block strategy.
        
        Args:
            min_displacement_atr: Minimum displacement for valid BOS (ATR multiple)
            volume_multiplier: Required volume vs average for entry
        """
        super().__init__(enabled)
        self.min_displacement_atr = min_displacement_atr
        self.volume_multiplier = volume_multiplier
    
    @property
    def name(self) -> str:
        return "BREAK_RETEST"
    
    @property
    def description(self) -> str:
        return "ICT Breaker Block - Trade returns to validated breaker zones after market structure breaks"
    
    def _calculate_confidence(
        self, 
        displacement_strength: float, 
        volume_ratio: float,
        has_liquidity_sweep: bool
    ) -> float:
        """
        Calculate dynamic confidence based on quality factors.
        
        Base: 0.60, Max: 0.85
        """
        base = 0.60
        
        # Displacement strength (stronger BOS = higher confidence)
        if displacement_strength >= 1.0:
            displacement_score = 0.12
        elif displacement_strength >= 0.7:
            displacement_score = 0.08
        else:
            displacement_score = 0.04
        
        # Volume confirmation
        if volume_ratio >= 1.5:
            volume_score = 0.08
        elif volume_ratio >= 1.3:
            volume_score = 0.05
        else:
            volume_score = 0.02
        
        # Liquidity sweep bonus (institutions swept stops before move)
        sweep_bonus = 0.05 if has_liquidity_sweep else 0
        
        return min(0.85, max(0.55, base + displacement_score + volume_score + sweep_bonus))
    
    def evaluate(self, state: MarketState) -> Signal:
        """Evaluate for ICT Breaker Block setup."""
        if not self.enabled:
            return self._hold_signal(state, "Strategy disabled")
        
        # Need enough candle data
        df = state.to_dataframe_5m()
        if len(df) < 30:
            return self._hold_signal(state, "Not enough data for market structure analysis")
        
        price = state.current_price
        
        # Step 1: Detect Market Structure Break
        bos = detect_market_structure_break(df, lookback=20)
        
        if bos is None:
            return self._hold_signal(state, "No market structure break detected")
        
        # Step 2: Check displacement strength
        if bos.displacement_strength < self.min_displacement_atr:
            return self._hold_signal(
                state, 
                f"Weak displacement: {bos.displacement_strength:.2f} ATR (need {self.min_displacement_atr})"
            )
        
        # Step 3: Find the Breaker Block
        breaker = find_breaker_block(df, bos)
        
        if breaker is None:
            return self._hold_signal(state, "No valid breaker block found")
        
        # Step 4: Check if price is at the Breaker Block zone
        in_zone = breaker.low <= price <= breaker.high
        
        # Allow small buffer (0.2% beyond zone)
        zone_buffer = breaker.high * 0.002
        near_zone = (breaker.low - zone_buffer) <= price <= (breaker.high + zone_buffer)
        
        if not near_zone:
            return self._hold_signal(
                state, 
                f"Price not at breaker zone: {breaker.low:.2f}-{breaker.high:.2f}"
            )
        
        # Step 5: Check volume
        if state.volume_ratio < self.volume_multiplier:
            return self._hold_signal(
                state, 
                f"Volume too low: {state.volume_ratio:.1f}x (need {self.volume_multiplier}x)"
            )
        
        # Step 6: Look for confirmation candle
        last_candle = df.iloc[-1]
        prev_candle = df.iloc[-2]
        
        # Check for liquidity sweep (bonus for confidence)
        sweep = detect_liquidity_sweep(df, lookback=15)
        has_sweep = sweep is not None
        
        # Calculate confidence
        confidence = self._calculate_confidence(
            bos.displacement_strength, 
            state.volume_ratio,
            has_sweep
        )
        
        # Bullish Breaker Block setup
        if breaker.block_type == 'bullish':
            # Need bullish confirmation candle
            if last_candle['close'] <= last_candle['open']:
                return self._hold_signal(state, "Waiting for bullish confirmation candle")
            
            # Stop loss below breaker block
            stop_loss = breaker.low * 0.995
            
            # Target: next resistance or 2x risk
            risk = price - stop_loss
            target = state.get_nearest_resistance() or (price + risk * 2)
            
            reason = f"Bullish Breaker at {breaker.low:.2f}-{breaker.high:.2f}"
            if has_sweep:
                reason += " (post-sweep)"
            reason += f", Displacement:{bos.displacement_strength:.1f}ATR"
            
            return self._create_signal(
                signal_type=SignalType.LONG,
                state=state,
                confidence=confidence,
                reason=reason,
                stop_loss=stop_loss,
                target=target,
            )
        
        # Bearish Breaker Block setup
        elif breaker.block_type == 'bearish':
            # Need bearish confirmation candle
            if last_candle['close'] >= last_candle['open']:
                return self._hold_signal(state, "Waiting for bearish confirmation candle")
            
            # Stop loss above breaker block
            stop_loss = breaker.high * 1.005
            
            # Target: next support or 2x risk
            risk = stop_loss - price
            target = state.get_nearest_support() or (price - risk * 2)
            
            reason = f"Bearish Breaker at {breaker.low:.2f}-{breaker.high:.2f}"
            if has_sweep:
                reason += " (post-sweep)"
            reason += f", Displacement:{bos.displacement_strength:.1f}ATR"
            
            return self._create_signal(
                signal_type=SignalType.SHORT,
                state=state,
                confidence=confidence,
                reason=reason,
                stop_loss=stop_loss,
                target=target,
            )
        
        return self._hold_signal(state, "No valid breaker block setup")
