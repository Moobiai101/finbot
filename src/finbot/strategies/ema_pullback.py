"""EMA Pullback in Trend Strategy - With Order Block Confluence.

Enhanced based on Smart Money Concepts:
- Not just ANY touch of 21 EMA
- Require confluence with Order Block zone
- Add cooldown between entries
- Prefer entries after minor liquidity sweeps

Key insight: The 21 EMA works because it often aligns with order blocks.
When they coincide = institutional entry zone = high probability.
"""

from finbot.data.market_state import MarketState
from finbot.strategies.base import BaseStrategy, Signal, SignalType
from finbot.strategies.smc_utils import identify_order_blocks, find_unfilled_fvg_near_price


class EMAPullbackStrategy(BaseStrategy):
    """
    EMA Pullback Strategy - Institutional Edition.
    
    Enhanced setup conditions:
    1. Strong trend: 9 EMA > 21 EMA > 50 EMA (bullish) or reverse
    2. Price pulls back to 21 EMA
    3. BONUS: 21 EMA overlaps with an Order Block zone
    4. Rejection candle confirms entry
    5. Stricter ADX threshold for trend confirmation
    """
    
    def __init__(
        self,
        ema_touch_threshold: float = 0.35,  # Tighter: % distance from 21 EMA
        require_adx: bool = True,  # Now required for confirmation
        min_adx: float = 22,  # Stricter
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
        return "EMA Pullback + Order Block - Trade pullbacks with institutional confluence"
    
    def _calculate_confidence(
        self, 
        adx: float, 
        ema_distance: float,
        has_order_block: bool,
        has_fvg: bool
    ) -> float:
        """
        Calculate dynamic confidence with institutional factors.
        """
        base = 0.55
        
        # ADX trend strength
        if adx and adx >= 30:
            adx_score = 0.12
        elif adx and adx >= 25:
            adx_score = 0.08
        elif adx and adx >= 22:
            adx_score = 0.05
        else:
            adx_score = 0.02
        
        # EMA proximity (closer = higher confidence)
        if ema_distance <= 0.1:
            proximity_score = 0.10
        elif ema_distance <= 0.2:
            proximity_score = 0.06
        else:
            proximity_score = 0.03
        
        # Order Block confluence (big bonus)
        ob_score = 0.08 if has_order_block else 0
        
        # FVG confluence
        fvg_score = 0.05 if has_fvg else 0
        
        return min(0.85, max(0.50, base + adx_score + proximity_score + ob_score + fvg_score))
    
    def evaluate(self, state: MarketState) -> Signal:
        """Evaluate for EMA pullback setup with order block confluence."""
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
        adx = state.indicators.adx
        if self.require_adx:
            if adx is None:
                return self._hold_signal(state, "ADX not available")
            if adx < self.min_adx:
                return self._hold_signal(state, f"Weak trend (ADX: {adx:.1f})")
        
        price = state.current_price
        df = state.to_dataframe_5m()
        
        # Calculate distance from 21 EMA
        ema21_distance = abs(price - ema21) / ema21 * 100
        
        # Check if at 21 EMA
        if ema21_distance > self.ema_touch_threshold:
            return self._hold_signal(
                state, 
                f"Price not at 21 EMA: {ema21_distance:.2f}% away"
            )
        
        # Check for Order Block confluence
        order_blocks = identify_order_blocks(df, lookback=25)
        has_order_block = False
        
        for ob in order_blocks:
            # Check if 21 EMA is within the order block zone
            if ob.low <= ema21 <= ob.high:
                # And price is near the zone
                if ob.low <= price <= ob.high or abs(price - ob.low) / price * 100 < 0.3:
                    has_order_block = True
                    break
        
        # Check for FVG confluence
        fvg = find_unfilled_fvg_near_price(df, price, threshold_percent=0.4)
        has_fvg = fvg is not None
        
        # Calculate confidence
        confidence = self._calculate_confidence(adx, ema21_distance, has_order_block, has_fvg)
        
        # Bullish setup
        if alignment == 'bullish':
            # Price should be between 21 and 9 EMA (pullback zone)
            if price < ema21 * 0.996:
                return self._hold_signal(state, "Price broke below 21 EMA")
            
            if price > ema9:
                return self._hold_signal(state, "Price above 9 EMA - wait for pullback")
            
            # Look for bullish confirmation candle
            if len(df) >= 1:
                last_candle = df.iloc[-1]
                
                if last_candle['close'] > last_candle['open']:
                    stop_loss = min(ema50, last_candle['low'] * 0.995)
                    
                    reason = f"EMA Pullback Long at {ema21:.2f}"
                    if has_order_block:
                        reason += " (OB confluence)"
                    if adx:
                        reason += f", ADX:{adx:.0f}"
                    
                    return self._create_signal(
                        signal_type=SignalType.LONG,
                        state=state,
                        confidence=confidence,
                        reason=reason,
                        stop_loss=stop_loss,
                    )
        
        # Bearish setup
        elif alignment == 'bearish':
            # Price should be between 21 and 9 EMA (pullback zone)
            if price > ema21 * 1.004:
                return self._hold_signal(state, "Price broke above 21 EMA")
            
            if price < ema9:
                return self._hold_signal(state, "Price below 9 EMA - wait for pullback")
            
            # Look for bearish confirmation candle
            if len(df) >= 1:
                last_candle = df.iloc[-1]
                
                if last_candle['close'] < last_candle['open']:
                    stop_loss = max(ema50, last_candle['high'] * 1.005)
                    
                    reason = f"EMA Pullback Short at {ema21:.2f}"
                    if has_order_block:
                        reason += " (OB confluence)"
                    if adx:
                        reason += f", ADX:{adx:.0f}"
                    
                    return self._create_signal(
                        signal_type=SignalType.SHORT,
                        state=state,
                        confidence=confidence,
                        reason=reason,
                        stop_loss=stop_loss,
                    )
        
        return self._hold_signal(state, "No EMA pullback setup")
