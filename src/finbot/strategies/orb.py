"""Opening Range Breakout (ORB) Strategy - With Liquidity Sweep Detection.

Enhanced based on Smart Money Concepts:
- WAIT for liquidity sweep before entering (don't chase breakouts)
- Enter on failed breakout (sweep and return) for higher probability
- Standard breakout only if very strong displacement

The key insight: Most ORB breakouts are stop hunts by institutions.
Smart money WAITS for the sweep, then enters opposite direction.
"""

from datetime import datetime, time
from finbot.data.market_state import MarketState, OpeningRange
from finbot.strategies.base import BaseStrategy, Signal, SignalType
from finbot.strategies.smc_utils import detect_liquidity_sweep


class ORBStrategy(BaseStrategy):
    """
    Opening Range Breakout Strategy - Institutional Edition.
    
    Two entry modes:
    1. SWEEP MODE (preferred): Wait for price to sweep ORB level and reverse
       - Higher win rate, fewer trades
       - Trades failed breakouts (where retail gets trapped)
    
    2. BREAKOUT MODE (strict): Only on very strong displacement
       - Requires 1.5x ATR move with heavy volume
       - Most "breakouts" are traps, so filter heavily
    """
    
    def __init__(
        self,
        range_minutes: int = 15,
        volume_multiplier: float = 1.5,  # Stricter than before
        min_range_percent: float = 0.3,
        max_range_percent: float = 1.2,  # Tighter max (wide ranges = more noise)
        enabled: bool = True,
    ):
        """
        Initialize ORB strategy.
        
        Args:
            range_minutes: Minutes to form opening range (default 15)
            volume_multiplier: Required volume vs average (now 1.5x)
            min_range_percent: Minimum range size (default 0.3%)
            max_range_percent: Maximum range size (default 1.2%)
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
        return "ORB with Sweep Detection - Trade failed breakouts and confirmed moves"
    
    def _calculate_confidence(
        self, 
        range_percent: float, 
        volume_ratio: float,
        is_sweep_trade: bool
    ) -> float:
        """
        Calculate dynamic confidence based on breakout quality.
        
        Sweep trades get higher base confidence (trap trades work better).
        """
        # Sweep trades start higher (better setups)
        base = 0.65 if is_sweep_trade else 0.58
        
        # Range quality: 0.5-0.9% is ideal
        if 0.5 <= range_percent <= 0.9:
            range_score = 0.10
        elif 0.3 <= range_percent <= 1.0:
            range_score = 0.06
        else:
            range_score = 0.02
        
        # Volume confirmation
        if volume_ratio >= 2.0:
            volume_score = 0.10
        elif volume_ratio >= 1.5:
            volume_score = 0.06
        else:
            volume_score = 0.03
        
        return min(0.85, max(0.55, base + range_score + volume_score))
    
    def evaluate(self, state: MarketState) -> Signal:
        """Evaluate for ORB setup with sweep detection."""
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
        
        price = state.current_price
        df = state.to_dataframe_5m()
        
        if len(df) < 5:
            return self._hold_signal(state, "Not enough candles")
        
        # ===== MODE 1: SWEEP DETECTION (Preferred) =====
        # Look for price that swept ORB level and reversed
        sweep = detect_liquidity_sweep(df, lookback=10)
        
        if sweep and sweep.recovered:
            # Bullish sweep: swept lows (took out stops) and reversed up
            if sweep.sweep_type == 'bullish' and sweep.level <= orb.low * 1.002:
                if state.volume_ratio >= self.volume_multiplier:
                    confidence = self._calculate_confidence(range_percent, state.volume_ratio, is_sweep_trade=True)
                    
                    stop_loss = sweep.sweep_low * 0.995
                    target = orb.high + (orb_range * 0.5)  # Target mid-way above range
                    
                    return self._create_signal(
                        signal_type=SignalType.LONG,
                        state=state,
                        confidence=confidence,
                        reason=f"ORB Sweep Long: Swept {orb.low:.2f}, reversed. Range:{range_percent:.1f}%",
                        stop_loss=stop_loss,
                        target=target,
                    )
            
            # Bearish sweep: swept highs and reversed down
            elif sweep.sweep_type == 'bearish' and sweep.level >= orb.high * 0.998:
                if state.volume_ratio >= self.volume_multiplier:
                    confidence = self._calculate_confidence(range_percent, state.volume_ratio, is_sweep_trade=True)
                    
                    stop_loss = sweep.sweep_high * 1.005
                    target = orb.low - (orb_range * 0.5)
                    
                    return self._create_signal(
                        signal_type=SignalType.SHORT,
                        state=state,
                        confidence=confidence,
                        reason=f"ORB Sweep Short: Swept {orb.high:.2f}, reversed. Range:{range_percent:.1f}%",
                        stop_loss=stop_loss,
                        target=target,
                    )
        
        # ===== MODE 2: STRONG BREAKOUT (Stricter criteria) =====
        # Only if no sweep, and we have VERY strong breakout with volume
        breakout = state.is_orb_breakout()
        
        if not breakout:
            return self._hold_signal(state, "No breakout or sweep detected")
        
        # Much stricter volume requirement for standard breakouts
        if state.volume_ratio < self.volume_multiplier * 1.2:
            return self._hold_signal(
                state, 
                f"Breakout volume weak: {state.volume_ratio:.1f}x (need {self.volume_multiplier * 1.2:.1f}x)"
            )
        
        # Need the candle to have good body (not just a wick)
        last_candle = df.iloc[-1]
        body_size = abs(last_candle['close'] - last_candle['open'])
        total_size = last_candle['high'] - last_candle['low']
        
        if total_size > 0 and body_size / total_size < 0.5:
            return self._hold_signal(state, "Breakout candle has weak body (possible reversal)")
        
        confidence = self._calculate_confidence(range_percent, state.volume_ratio, is_sweep_trade=False)
        
        if breakout == 'long':
            stop_loss = orb.low
            target = price + (orb_range * 1.5)
            
            return self._create_signal(
                signal_type=SignalType.LONG,
                state=state,
                confidence=confidence,
                reason=f"ORB Breakout Long: Above {orb.high:.2f}, Strong Vol:{state.volume_ratio:.1f}x",
                stop_loss=stop_loss,
                target=target,
            )
        
        else:  # short
            stop_loss = orb.high
            target = price - (orb_range * 1.5)
            
            return self._create_signal(
                signal_type=SignalType.SHORT,
                state=state,
                confidence=confidence,
                reason=f"ORB Breakout Short: Below {orb.low:.2f}, Strong Vol:{state.volume_ratio:.1f}x",
                stop_loss=stop_loss,
                target=target,
            )
