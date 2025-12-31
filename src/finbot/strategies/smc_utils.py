"""Smart Money Concepts (SMC) Utility Functions.

Based on ICT (Inner Circle Trader) methodology:
- Liquidity sweep detection (stop hunts)
- Fair Value Gap identification
- Order Block detection
- Market Structure Break identification

These are the concepts that 90% of retail traders don't understand,
but institutions use to trap retail positions before making real moves.
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import Optional
from datetime import datetime, timedelta


@dataclass
class LiquiditySweep:
    """Represents a liquidity sweep (stop hunt)."""
    timestamp: datetime
    sweep_type: str  # 'bullish' (swept lows) or 'bearish' (swept highs)
    level: float  # The level that was swept
    sweep_high: float  # Highest point of the sweep
    sweep_low: float  # Lowest point of the sweep
    recovered: bool  # Did price recover back past the level?


@dataclass
class FairValueGap:
    """Represents a Fair Value Gap (price imbalance)."""
    timestamp: datetime
    gap_type: str  # 'bullish' or 'bearish'
    high: float  # Top of the gap
    low: float  # Bottom of the gap
    filled: bool = False  # Has the gap been filled?


@dataclass
class OrderBlock:
    """Represents an Order Block (institutional entry zone)."""
    timestamp: datetime
    block_type: str  # 'bullish' or 'bearish'
    high: float
    low: float
    mitigated: bool = False  # Has price returned to this zone?


@dataclass
class MarketStructureBreak:
    """Represents a Break of Structure (BOS)."""
    timestamp: datetime
    break_type: str  # 'bullish' (broke high) or 'bearish' (broke low)
    broken_level: float
    displacement_strength: float  # How strong was the move (ATR multiple)


def detect_liquidity_sweep(df: pd.DataFrame, lookback: int = 20) -> Optional[LiquiditySweep]:
    """
    Detect if a liquidity sweep (stop hunt) just occurred.
    
    A liquidity sweep happens when:
    1. Price breaks beyond a swing high/low (where retail stops cluster)
    2. Price quickly reverses back past the level
    3. This traps breakout traders and triggers stops
    
    Args:
        df: DataFrame with OHLC data (at least 'lookback' rows)
        lookback: Number of candles to look back for swing highs/lows
    
    Returns:
        LiquiditySweep if detected, None otherwise
    """
    if len(df) < lookback + 3:
        return None
    
    # Get recent candles
    recent = df.iloc[-(lookback + 3):]
    last_candle = df.iloc[-1]
    prev_candle = df.iloc[-2]
    
    # Find swing highs and lows (liquidity pools)
    swing_high = recent['high'].iloc[:-3].max()
    swing_high_idx = recent['high'].iloc[:-3].idxmax()
    swing_low = recent['low'].iloc[:-3].min()
    swing_low_idx = recent['low'].iloc[:-3].idxmin()
    
    # Check for bearish sweep (swept highs, now reversing down)
    # Price went above swing high but closed back below
    if prev_candle['high'] > swing_high and last_candle['close'] < swing_high:
        if last_candle['close'] < last_candle['open']:  # Bearish confirmation
            return LiquiditySweep(
                timestamp=last_candle.name if hasattr(last_candle.name, 'hour') else datetime.now(),
                sweep_type='bearish',
                level=swing_high,
                sweep_high=prev_candle['high'],
                sweep_low=last_candle['low'],
                recovered=True
            )
    
    # Check for bullish sweep (swept lows, now reversing up)
    # Price went below swing low but closed back above
    if prev_candle['low'] < swing_low and last_candle['close'] > swing_low:
        if last_candle['close'] > last_candle['open']:  # Bullish confirmation
            return LiquiditySweep(
                timestamp=last_candle.name if hasattr(last_candle.name, 'hour') else datetime.now(),
                sweep_type='bullish',
                level=swing_low,
                sweep_high=last_candle['high'],
                sweep_low=prev_candle['low'],
                recovered=True
            )
    
    return None


def find_fair_value_gaps(df: pd.DataFrame, min_gap_percent: float = 0.15) -> list[FairValueGap]:
    """
    Find Fair Value Gaps (FVGs) in price action.
    
    FVG = 3-candle pattern where candle 1's wick doesn't overlap candle 3's wick.
    This represents an imbalance (price moved too fast) that tends to get filled.
    
    Args:
        df: DataFrame with OHLC data
        min_gap_percent: Minimum gap size as % of price
    
    Returns:
        List of FairValueGap objects
    """
    gaps = []
    
    if len(df) < 3:
        return gaps
    
    for i in range(2, len(df)):
        candle1 = df.iloc[i-2]
        candle2 = df.iloc[i-1]
        candle3 = df.iloc[i]
        
        # Bullish FVG: Gap UP (candle1 high < candle3 low)
        if candle1['high'] < candle3['low']:
            gap_size = (candle3['low'] - candle1['high']) / candle2['close'] * 100
            if gap_size >= min_gap_percent:
                gaps.append(FairValueGap(
                    timestamp=candle2.name if hasattr(candle2.name, 'hour') else datetime.now(),
                    gap_type='bullish',
                    high=candle3['low'],
                    low=candle1['high'],
                    filled=False
                ))
        
        # Bearish FVG: Gap DOWN (candle1 low > candle3 high)
        if candle1['low'] > candle3['high']:
            gap_size = (candle1['low'] - candle3['high']) / candle2['close'] * 100
            if gap_size >= min_gap_percent:
                gaps.append(FairValueGap(
                    timestamp=candle2.name if hasattr(candle2.name, 'hour') else datetime.now(),
                    gap_type='bearish',
                    high=candle1['low'],
                    low=candle3['high'],
                    filled=False
                ))
    
    # Mark gaps that have been filled by subsequent price action
    current_price = df.iloc[-1]['close']
    for gap in gaps:
        if gap.gap_type == 'bullish':
            # Bullish gap filled if price came back down into it
            if current_price <= gap.high:
                gap.filled = True
        else:
            # Bearish gap filled if price came back up into it
            if current_price >= gap.low:
                gap.filled = True
    
    return gaps


def find_unfilled_fvg_near_price(
    df: pd.DataFrame, 
    current_price: float, 
    threshold_percent: float = 0.5
) -> Optional[FairValueGap]:
    """
    Find an unfilled Fair Value Gap near the current price.
    
    Used for confluence - entering at VWAP/EMA that also has an unfilled FVG.
    
    Args:
        df: DataFrame with OHLC data
        current_price: Current price to check proximity
        threshold_percent: Max distance from price to FVG (%)
    
    Returns:
        Nearest unfilled FVG if within threshold, None otherwise
    """
    gaps = find_fair_value_gaps(df)
    unfilled = [g for g in gaps if not g.filled]
    
    nearest = None
    min_distance = float('inf')
    
    for gap in unfilled:
        # Distance to gap zone
        if gap.gap_type == 'bullish':
            gap_center = (gap.high + gap.low) / 2
        else:
            gap_center = (gap.high + gap.low) / 2
        
        distance = abs(current_price - gap_center) / current_price * 100
        
        if distance < threshold_percent and distance < min_distance:
            min_distance = distance
            nearest = gap
    
    return nearest


def identify_order_blocks(df: pd.DataFrame, lookback: int = 30) -> list[OrderBlock]:
    """
    Identify Order Blocks - zones where institutions placed orders.
    
    Bullish Order Block = Last DOWN candle before a strong UP move
    Bearish Order Block = Last UP candle before a strong DOWN move
    
    These zones often get retested and provide entry opportunities.
    
    Args:
        df: DataFrame with OHLC data
        lookback: Number of candles to analyze
    
    Returns:
        List of OrderBlock objects
    """
    blocks = []
    
    if len(df) < lookback:
        return blocks
    
    recent = df.iloc[-lookback:]
    
    # Calculate what constitutes a "strong move" (1.5x ATR)
    atr = (recent['high'] - recent['low']).rolling(14).mean().iloc[-1]
    strong_move_threshold = atr * 1.5
    
    for i in range(1, len(recent) - 2):
        candle = recent.iloc[i]
        next_candle = recent.iloc[i + 1]
        next_next = recent.iloc[i + 2]
        
        candle_body = abs(candle['close'] - candle['open'])
        next_move = next_next['close'] - candle['close']
        
        # Bullish Order Block: bearish candle followed by strong bullish move
        if candle['close'] < candle['open']:  # Bearish candle
            if next_move > strong_move_threshold:  # Strong up move after
                blocks.append(OrderBlock(
                    timestamp=candle.name if hasattr(candle.name, 'hour') else datetime.now(),
                    block_type='bullish',
                    high=candle['high'],
                    low=candle['low'],
                    mitigated=False
                ))
        
        # Bearish Order Block: bullish candle followed by strong bearish move
        if candle['close'] > candle['open']:  # Bullish candle
            if next_move < -strong_move_threshold:  # Strong down move after
                blocks.append(OrderBlock(
                    timestamp=candle.name if hasattr(candle.name, 'hour') else datetime.now(),
                    block_type='bearish',
                    high=candle['high'],
                    low=candle['low'],
                    mitigated=False
                ))
    
    # Mark blocks that have been mitigated (price returned to them)
    current_price = df.iloc[-1]['close']
    for block in blocks:
        if block.block_type == 'bullish':
            if current_price <= block.high and current_price >= block.low:
                block.mitigated = True
        else:
            if current_price <= block.high and current_price >= block.low:
                block.mitigated = True
    
    return blocks


def detect_market_structure_break(df: pd.DataFrame, lookback: int = 20) -> Optional[MarketStructureBreak]:
    """
    Detect a Break of Structure (BOS) - key concept in SMC.
    
    Bullish BOS = Price breaks above a swing high (higher high)
    Bearish BOS = Price breaks below a swing low (lower low)
    
    BOS signals potential trend continuation or reversal.
    
    Args:
        df: DataFrame with OHLC data
        lookback: Number of candles to analyze for swing points
    
    Returns:
        MarketStructureBreak if detected, None otherwise
    """
    if len(df) < lookback:
        return None
    
    recent = df.iloc[-lookback:]
    last_candle = df.iloc[-1]
    
    # Find swing high/low (excluding last 3 candles)
    swing_data = recent.iloc[:-3]
    swing_high = swing_data['high'].max()
    swing_low = swing_data['low'].min()
    
    # Calculate ATR for displacement strength
    atr = (recent['high'] - recent['low']).rolling(14).mean().iloc[-1]
    
    # Bullish BOS: current close breaks above swing high
    if last_candle['close'] > swing_high:
        displacement = (last_candle['close'] - swing_high) / atr if atr > 0 else 0
        if displacement >= 0.5:  # At least 0.5 ATR displacement
            return MarketStructureBreak(
                timestamp=last_candle.name if hasattr(last_candle.name, 'hour') else datetime.now(),
                break_type='bullish',
                broken_level=swing_high,
                displacement_strength=displacement
            )
    
    # Bearish BOS: current close breaks below swing low
    if last_candle['close'] < swing_low:
        displacement = (swing_low - last_candle['close']) / atr if atr > 0 else 0
        if displacement >= 0.5:  # At least 0.5 ATR displacement
            return MarketStructureBreak(
                timestamp=last_candle.name if hasattr(last_candle.name, 'hour') else datetime.now(),
                break_type='bearish',
                broken_level=swing_low,
                displacement_strength=displacement
            )
    
    return None


def find_breaker_block(df: pd.DataFrame, bos: MarketStructureBreak) -> Optional[OrderBlock]:
    """
    Find the Breaker Block after a Break of Structure.
    
    A Breaker Block is the last order block before a BOS that gets violated.
    When price returns to this zone, it often provides a high-probability entry.
    
    Used to replace the old BREAK_RETEST logic.
    
    Args:
        df: DataFrame with OHLC data
        bos: The Break of Structure that was detected
    
    Returns:
        OrderBlock that serves as the breaker block, None if not found
    """
    if bos is None:
        return None
    
    # Find order blocks
    blocks = identify_order_blocks(df, lookback=30)
    
    # For bullish BOS, find the last bearish order block before the break
    if bos.break_type == 'bullish':
        bearish_blocks = [b for b in blocks if b.block_type == 'bearish']
        if bearish_blocks:
            # Return the most recent one (becomes bullish breaker)
            return OrderBlock(
                timestamp=bearish_blocks[-1].timestamp,
                block_type='bullish',  # Flips to bullish after BOS
                high=bearish_blocks[-1].high,
                low=bearish_blocks[-1].low,
                mitigated=False
            )
    
    # For bearish BOS, find the last bullish order block before the break
    elif bos.break_type == 'bearish':
        bullish_blocks = [b for b in blocks if b.block_type == 'bullish']
        if bullish_blocks:
            # Return the most recent one (becomes bearish breaker)
            return OrderBlock(
                timestamp=bullish_blocks[-1].timestamp,
                block_type='bearish',  # Flips to bearish after BOS
                high=bullish_blocks[-1].high,
                low=bullish_blocks[-1].low,
                mitigated=False
            )
    
    return None


def is_in_valid_trading_session(current_time: datetime) -> bool:
    """
    Check if current time is in a valid trading window.
    
    Avoid:
    - First 15 minutes (9:15-9:30): High volatility, stop hunting
    - Last 30 minutes (15:00-15:30): Squareoff pressure
    
    Args:
        current_time: Current market time
    
    Returns:
        True if in valid session, False otherwise
    """
    from datetime import time
    
    market_time = current_time.time()
    
    # Avoid first 15 minutes (9:15-9:30)
    if market_time < time(9, 30):
        return False
    
    # Avoid last 30 minutes (15:00-15:30)
    if market_time >= time(15, 0):
        return False
    
    return True
