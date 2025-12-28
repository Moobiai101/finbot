"""Technical indicators calculation module using pandas-ta."""

from dataclasses import dataclass
from typing import Optional
import pandas as pd
import numpy as np

try:
    import pandas_ta as ta
    HAS_PANDAS_TA = True
except ImportError:
    HAS_PANDAS_TA = False


@dataclass
class IndicatorValues:
    """Container for calculated indicator values."""
    # Moving Averages
    ema_9: Optional[float] = None
    ema_21: Optional[float] = None
    ema_50: Optional[float] = None
    sma_20: Optional[float] = None
    sma_200: Optional[float] = None
    
    # VWAP
    vwap: Optional[float] = None
    
    # RSI
    rsi_14: Optional[float] = None
    
    # ATR
    atr_14: Optional[float] = None
    
    # MACD
    macd: Optional[float] = None
    macd_signal: Optional[float] = None
    macd_histogram: Optional[float] = None
    
    # Bollinger Bands
    bb_upper: Optional[float] = None
    bb_middle: Optional[float] = None
    bb_lower: Optional[float] = None
    
    # Supertrend
    supertrend: Optional[float] = None
    supertrend_direction: Optional[int] = None  # 1 = bullish, -1 = bearish
    
    # ADX
    adx: Optional[float] = None
    plus_di: Optional[float] = None
    minus_di: Optional[float] = None


class IndicatorEngine:
    """
    Calculate technical indicators from OHLCV data.
    
    Uses pandas-ta for calculations if available,
    fallback to manual calculations otherwise.
    """
    
    @staticmethod
    def add_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
        """
        Add all indicator columns to the dataframe (Vectorized).
        Used for backtesting to pre-calculate everything.
        """
        if df.empty:
            return df
            
        # Ensure lowercase
        df.columns = df.columns.str.lower()
        
        if HAS_PANDAS_TA:
            # EMA
            df['ema_9'] = ta.ema(df['close'], length=9)
            df['ema_21'] = ta.ema(df['close'], length=21)
            df['ema_50'] = ta.ema(df['close'], length=50)
            
            # SMA
            df['sma_20'] = ta.sma(df['close'], length=20)
            df['sma_200'] = ta.sma(df['close'], length=200)
            
            # RSI
            df['rsi_14'] = ta.rsi(df['close'], length=14)
            
            # ATR
            df['atr_14'] = ta.atr(df['high'], df['low'], df['close'], length=14)
            
            # VWAP
            if 'volume' in df.columns:
                df['vwap'] = ta.vwap(df['high'], df['low'], df['close'], df['volume'])
                
            # MACD
            macd = ta.macd(df['close'])
            if macd is not None:
                # pandas-ta returns columns named like MACD_12_26_9, MACDh_12_26_9, MACDs_12_26_9
                # We rename or just use iloc
                df['macd'] = macd.iloc[:, 0]
                df['macd_histogram'] = macd.iloc[:, 1]
                df['macd_signal'] = macd.iloc[:, 2]
                
            # Bollinger Bands
            bb = ta.bbands(df['close'], length=20)
            if bb is not None:
                df['bb_lower'] = bb.iloc[:, 0]
                df['bb_middle'] = bb.iloc[:, 1]
                df['bb_upper'] = bb.iloc[:, 2]
                
            # Supertrend
            st = ta.supertrend(df['high'], df['low'], df['close'], length=10, multiplier=3)
            if st is not None:
                df['supertrend'] = st.iloc[:, 0]
                df['supertrend_direction'] = st.iloc[:, 1]
                
            # ADX
            adx_res = ta.adx(df['high'], df['low'], df['close'], length=14)
            if adx_res is not None:
                df['adx'] = adx_res.iloc[:, 0]
                df['plus_di'] = adx_res.iloc[:, 1]
                df['minus_di'] = adx_res.iloc[:, 2]
                
        else:
            # Fallback Manual
             # EMA
            df['ema_9'] = IndicatorEngine.calculate_ema(df['close'], 9)
            df['ema_21'] = IndicatorEngine.calculate_ema(df['close'], 21)
            df['ema_50'] = IndicatorEngine.calculate_ema(df['close'], 50)
            
            # SMA
            df['sma_20'] = df['close'].rolling(20).mean()
            df['sma_200'] = df['close'].rolling(200).mean()
            
            # RSI
            df['rsi_14'] = IndicatorEngine.calculate_rsi(df['close'])
            
            # ATR
            df['atr_14'] = IndicatorEngine.calculate_atr(df['high'], df['low'], df['close'])
            
            # VWAP
            if 'volume' in df.columns:
                df['vwap'] = IndicatorEngine.calculate_vwap(df['high'], df['low'], df['close'], df['volume'])

        return df

    
    @staticmethod
    def calculate_all(df: pd.DataFrame) -> IndicatorValues:
        """
        Calculate all indicators for a dataframe.
        
        Args:
            df: DataFrame with columns [open, high, low, close, volume]
            
        Returns:
            IndicatorValues with latest values
        """
        if df.empty or len(df) < 20:
            return IndicatorValues()
        
        indicators = IndicatorValues()
        
        # Ensure column names are lowercase
        df.columns = df.columns.str.lower()
        
        if HAS_PANDAS_TA:
            indicators = IndicatorEngine._calculate_with_ta(df)
        else:
            indicators = IndicatorEngine._calculate_manual(df)
        
        return indicators
    
    @staticmethod
    def _calculate_with_ta(df: pd.DataFrame) -> IndicatorValues:
        """Calculate using pandas-ta library."""
        indicators = IndicatorValues()
        
        try:
            # EMAs
            ema9 = ta.ema(df['close'], length=9)
            ema21 = ta.ema(df['close'], length=21)
            ema50 = ta.ema(df['close'], length=50)
            
            indicators.ema_9 = float(ema9.iloc[-1]) if ema9 is not None and not ema9.empty else None
            indicators.ema_21 = float(ema21.iloc[-1]) if ema21 is not None and not ema21.empty else None
            indicators.ema_50 = float(ema50.iloc[-1]) if ema50 is not None and not ema50.empty else None
            
            # SMAs
            sma20 = ta.sma(df['close'], length=20)
            sma200 = ta.sma(df['close'], length=200) if len(df) >= 200 else None
            
            indicators.sma_20 = float(sma20.iloc[-1]) if sma20 is not None and not sma20.empty else None
            indicators.sma_200 = float(sma200.iloc[-1]) if sma200 is not None and not sma200.empty else None
            
            # RSI
            rsi = ta.rsi(df['close'], length=14)
            indicators.rsi_14 = float(rsi.iloc[-1]) if rsi is not None and not rsi.empty else None
            
            # ATR
            atr = ta.atr(df['high'], df['low'], df['close'], length=14)
            indicators.atr_14 = float(atr.iloc[-1]) if atr is not None and not atr.empty else None
            
            # VWAP (requires volume)
            if 'volume' in df.columns and df['volume'].sum() > 0:
                vwap = ta.vwap(df['high'], df['low'], df['close'], df['volume'])
                indicators.vwap = float(vwap.iloc[-1]) if vwap is not None and not vwap.empty else None
            
            # MACD
            macd_result = ta.macd(df['close'])
            if macd_result is not None and not macd_result.empty:
                indicators.macd = float(macd_result.iloc[-1, 0])
                indicators.macd_signal = float(macd_result.iloc[-1, 2])
                indicators.macd_histogram = float(macd_result.iloc[-1, 1])
            
            # Bollinger Bands
            bb = ta.bbands(df['close'], length=20)
            if bb is not None and not bb.empty:
                indicators.bb_lower = float(bb.iloc[-1, 0])
                indicators.bb_middle = float(bb.iloc[-1, 1])
                indicators.bb_upper = float(bb.iloc[-1, 2])
            
            # Supertrend
            st = ta.supertrend(df['high'], df['low'], df['close'], length=10, multiplier=3)
            if st is not None and not st.empty:
                indicators.supertrend = float(st.iloc[-1, 0])
                indicators.supertrend_direction = int(st.iloc[-1, 1])
            
            # ADX
            adx_result = ta.adx(df['high'], df['low'], df['close'], length=14)
            if adx_result is not None and not adx_result.empty:
                indicators.adx = float(adx_result.iloc[-1, 0])
                indicators.plus_di = float(adx_result.iloc[-1, 1])
                indicators.minus_di = float(adx_result.iloc[-1, 2])
                
        except Exception as e:
            print(f"Error calculating indicators with pandas-ta: {e}")
        
        return indicators
    
    @staticmethod
    def _calculate_manual(df: pd.DataFrame) -> IndicatorValues:
        """Calculate indicators manually (fallback)."""
        indicators = IndicatorValues()
        
        close = df['close']
        high = df['high']
        low = df['low']
        
        # EMA
        indicators.ema_9 = float(close.ewm(span=9, adjust=False).mean().iloc[-1])
        indicators.ema_21 = float(close.ewm(span=21, adjust=False).mean().iloc[-1])
        if len(df) >= 50:
            indicators.ema_50 = float(close.ewm(span=50, adjust=False).mean().iloc[-1])
        
        # SMA
        indicators.sma_20 = float(close.rolling(20).mean().iloc[-1])
        if len(df) >= 200:
            indicators.sma_200 = float(close.rolling(200).mean().iloc[-1])
        
        # RSI
        delta = close.diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        indicators.rsi_14 = float(rsi.iloc[-1]) if not pd.isna(rsi.iloc[-1]) else None
        
        # ATR
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(14).mean()
        indicators.atr_14 = float(atr.iloc[-1]) if not pd.isna(atr.iloc[-1]) else None
        
        # VWAP
        if 'volume' in df.columns and df['volume'].sum() > 0:
            typical_price = (high + low + close) / 3
            vwap = (typical_price * df['volume']).cumsum() / df['volume'].cumsum()
            indicators.vwap = float(vwap.iloc[-1]) if not pd.isna(vwap.iloc[-1]) else None
        
        return indicators
    
    @staticmethod
    def calculate_ema(series: pd.Series, period: int) -> pd.Series:
        """Calculate EMA for a series."""
        return series.ewm(span=period, adjust=False).mean()
    
    @staticmethod
    def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
        """Calculate RSI for a series."""
        delta = series.diff()
        gain = delta.where(delta > 0, 0).rolling(period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))
    
    @staticmethod
    def calculate_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
        """Calculate ATR."""
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.rolling(period).mean()
    
    @staticmethod
    def calculate_vwap(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series) -> pd.Series:
        """Calculate VWAP."""
        typical_price = (high + low + close) / 3
        return (typical_price * volume).cumsum() / volume.cumsum()
    
    @staticmethod
    def detect_engulfing(df: pd.DataFrame) -> Optional[str]:
        """
        Detect engulfing candlestick pattern.
        
        Returns:
            'bullish', 'bearish', or None
        """
        if len(df) < 2:
            return None
        
        current = df.iloc[-1]
        previous = df.iloc[-2]
        
        curr_body = current['close'] - current['open']
        prev_body = previous['close'] - previous['open']
        
        # Bullish engulfing
        if (prev_body < 0 and  # Previous was bearish
            curr_body > 0 and  # Current is bullish
            current['open'] <= previous['close'] and  # Open at or below prev close
            current['close'] >= previous['open']):  # Close at or above prev open
            return 'bullish'
        
        # Bearish engulfing
        if (prev_body > 0 and  # Previous was bullish
            curr_body < 0 and  # Current is bearish
            current['open'] >= previous['close'] and  # Open at or above prev close
            current['close'] <= previous['open']):  # Close at or below prev open
            return 'bearish'
        
        return None
    
    @staticmethod
    def detect_doji(df: pd.DataFrame, threshold: float = 0.1) -> bool:
        """Detect doji pattern (small body relative to range)."""
        if df.empty:
            return False
        
        current = df.iloc[-1]
        body = abs(current['close'] - current['open'])
        range_ = current['high'] - current['low']
        
        if range_ == 0:
            return False
        
        return (body / range_) < threshold
    
    @staticmethod
    def calculate_pivot_points(high: float, low: float, close: float) -> dict:
        """
        Calculate pivot points from previous day's OHLC.
        
        Returns:
            Dict with PP, R1, R2, R3, S1, S2, S3
        """
        pp = (high + low + close) / 3
        
        return {
            'PP': pp,
            'R1': (2 * pp) - low,
            'R2': pp + (high - low),
            'R3': high + 2 * (pp - low),
            'S1': (2 * pp) - high,
            'S2': pp - (high - low),
            'S3': low - 2 * (high - pp),
        }
    
    @staticmethod
    def find_support_resistance(df: pd.DataFrame, lookback: int = 20) -> tuple[list[float], list[float]]:
        """
        Find support and resistance levels using swing points.
        
        Returns:
            Tuple of (support_levels, resistance_levels)
        """
        if len(df) < lookback:
            return [], []
        
        df = df.tail(lookback * 3)  # Use more data for better levels
        
        highs = df['high'].values
        lows = df['low'].values
        
        resistances = []
        supports = []
        
        # Find swing highs (local maxima)
        for i in range(2, len(highs) - 2):
            if highs[i] > highs[i-1] and highs[i] > highs[i-2] and \
               highs[i] > highs[i+1] and highs[i] > highs[i+2]:
                resistances.append(highs[i])
        
        # Find swing lows (local minima)
        for i in range(2, len(lows) - 2):
            if lows[i] < lows[i-1] and lows[i] < lows[i-2] and \
               lows[i] < lows[i+1] and lows[i] < lows[i+2]:
                supports.append(lows[i])
        
        # Remove duplicates and sort
        resistances = sorted(set([round(r, 2) for r in resistances]), reverse=True)[:5]
        supports = sorted(set([round(s, 2) for s in supports]))[:5]
        
        return supports, resistances
