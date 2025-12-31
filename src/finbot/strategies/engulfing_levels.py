"""Engulfing at Key Levels Strategy - With Liquidity Sweep Confirmation.

Enhanced based on Smart Money Concepts:
- Don't just enter on ANY engulfing pattern at S/R
- WAIT for a liquidity sweep first (proof that stops were hunted)
- Then look for engulfing as the reversal confirmation
- This dramatically increases win rate

Key insight: Engulfing at S/R without a sweep = likely to fail (no liquidity)
Engulfing AFTER a sweep = institutions have accumulated/distributed
"""

from finbot.data.market_state import MarketState
from finbot.data.indicators import IndicatorEngine
from finbot.strategies.base import BaseStrategy, Signal, SignalType
from finbot.strategies.smc_utils import detect_liquidity_sweep, find_unfilled_fvg_near_price


class EngulfingLevelsStrategy(BaseStrategy):
    """
    Engulfing at Key Levels Strategy - Institutional Edition.
    
    Old retail approach (WRONG):
    - See engulfing at support → go long
    - Result: Gets stopped out when price sweeps through level
    
    New institutional approach:
    1. Wait for price to SWEEP the S/R level (take out stops)
    2. Then look for engulfing pattern
    3. Enter after the sweep with tight stop beyond sweep extreme
    4. RSI divergence adds confluence
    """
    
    def __init__(
        self,
        level_threshold: float = 0.5,  # Tighter: % distance from level
        volume_multiplier: float = 1.3,  # Stricter volume
        require_sweep: bool = True,  # Require liquidity sweep first
        enabled: bool = True,
    ):
        """
        Initialize Engulfing strategy.
        
        Args:
            level_threshold: Max distance from S/R level (%)
            volume_multiplier: Required volume vs average
            require_sweep: Whether to require a sweep before entering
        """
        super().__init__(enabled)
        self.level_threshold = level_threshold
        self.volume_multiplier = volume_multiplier
        self.require_sweep = require_sweep
    
    @property
    def name(self) -> str:
        return "ENGULFING_LEVELS"
    
    @property
    def description(self) -> str:
        return "Engulfing + Sweep - Trade reversals only after liquidity sweep"
    
    def _calculate_confidence(
        self, 
        rsi: float, 
        has_sweep: bool,
        has_fvg: bool,
        volume_ratio: float
    ) -> float:
        """
        Calculate dynamic confidence with multiple factors.
        """
        base = 0.55
        
        # Sweep confirmation (biggest factor)
        sweep_score = 0.12 if has_sweep else 0
        
        # RSI divergence
        if rsi and rsi < 30:
            rsi_score = 0.10  # Oversold = strong reversal
        elif rsi and rsi < 40:
            rsi_score = 0.06
        elif rsi and rsi > 70:
            rsi_score = 0.10  # Overbought = strong reversal
        elif rsi and rsi > 60:
            rsi_score = 0.06
        else:
            rsi_score = 0.02
        
        # FVG confluence
        fvg_score = 0.08 if has_fvg else 0
        
        # Volume
        if volume_ratio >= 1.5:
            vol_score = 0.05
        else:
            vol_score = 0.02
        
        return min(0.85, max(0.50, base + sweep_score + rsi_score + fvg_score + vol_score))
    
    def evaluate(self, state: MarketState) -> Signal:
        """Evaluate for engulfing setup at key levels with sweep confirmation."""
        if not self.enabled:
            return self._hold_signal(state, "Strategy disabled")
        
        df = state.to_dataframe_5m()
        if len(df) < 10:
            return self._hold_signal(state, "Not enough candle data")
        
        # Check for engulfing pattern
        engulfing = IndicatorEngine.detect_engulfing(df)
        
        if not engulfing:
            return self._hold_signal(state, "No engulfing pattern")
        
        price = state.current_price
        
        # Check volume
        if state.volume_ratio < self.volume_multiplier:
            return self._hold_signal(
                state,
                f"Volume too low: {state.volume_ratio:.1f}x"
            )
        
        # Check for liquidity sweep
        sweep = detect_liquidity_sweep(df, lookback=15)
        has_sweep = sweep is not None and sweep.recovered
        
        # If sweep required but not found, skip
        if self.require_sweep and not has_sweep:
            return self._hold_signal(state, "Engulfing without sweep - waiting for confirmation")
        
        # Check for FVG confluence
        fvg = find_unfilled_fvg_near_price(df, price, threshold_percent=0.5)
        has_fvg = fvg is not None
        
        rsi = state.indicators.rsi_14
        
        # Bullish engulfing setup
        if engulfing == 'bullish':
            near_support = state.is_near_support(self.level_threshold)
            
            if not near_support and not has_sweep:
                return self._hold_signal(state, "Bullish engulfing but not at support or sweep")
            
            confidence = self._calculate_confidence(rsi, has_sweep, has_fvg, state.volume_ratio)
            
            # Stop loss: below sweep low or support
            if has_sweep:
                stop_loss = sweep.sweep_low * 0.995
            else:
                support = state.get_nearest_support()
                stop_loss = support * 0.995 if support else price * 0.985
            
            # Target next resistance
            resistance = state.get_nearest_resistance()
            target = resistance if resistance else price * 1.02
            
            # Build reason string
            reason_parts = ["Bullish Engulfing"]
            if has_sweep:
                reason_parts.append("post-sweep")
            if has_fvg:
                reason_parts.append("at FVG")
            if rsi and rsi < 35:
                reason_parts.append(f"RSI:{rsi:.0f}")
            
            return self._create_signal(
                signal_type=SignalType.LONG,
                state=state,
                confidence=confidence,
                reason=" + ".join(reason_parts),
                stop_loss=stop_loss,
                target=target,
            )
        
        # Bearish engulfing setup
        elif engulfing == 'bearish':
            near_resistance = state.is_near_resistance(self.level_threshold)
            
            if not near_resistance and not has_sweep:
                return self._hold_signal(state, "Bearish engulfing but not at resistance or sweep")
            
            confidence = self._calculate_confidence(rsi, has_sweep, has_fvg, state.volume_ratio)
            
            # Stop loss: above sweep high or resistance
            if has_sweep:
                stop_loss = sweep.sweep_high * 1.005
            else:
                resistance = state.get_nearest_resistance()
                stop_loss = resistance * 1.005 if resistance else price * 1.015
            
            # Target next support
            support = state.get_nearest_support()
            target = support if support else price * 0.98
            
            # Build reason string
            reason_parts = ["Bearish Engulfing"]
            if has_sweep:
                reason_parts.append("post-sweep")
            if has_fvg:
                reason_parts.append("at FVG")
            if rsi and rsi > 65:
                reason_parts.append(f"RSI:{rsi:.0f}")
            
            return self._create_signal(
                signal_type=SignalType.SHORT,
                state=state,
                confidence=confidence,
                reason=" + ".join(reason_parts),
                stop_loss=stop_loss,
                target=target,
            )
        
        return self._hold_signal(state, "No setup")
