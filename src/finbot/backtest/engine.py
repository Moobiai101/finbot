"""
Backtest Logic Engine.

Orchestrates the historical simulation.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import pandas as pd
from loguru import logger
from tqdm import tqdm

from finbot.backtest.universe import get_universe, NIFTY_30_WEIGHTED
from finbot.backtest.data_loader import get_data_loader
from finbot.data.market_state import MarketState, Candle, OpeningRange
from finbot.data.indicators import IndicatorEngine, IndicatorValues
from finbot.strategies.registry import get_strategy_registry, BaseStrategy
from finbot.strategies.base import Signal, SignalType

@dataclass
class Trade:
    strategy: str
    symbol: str
    entry_time: datetime
    entry_price: float
    quantity: int
    side: str # LONG/SHORT
    stop_loss: float
    target: float
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_reason: str = ""
    pnl: float = 0.0

@dataclass
class PortfolioState:
    name: str
    initial_capital: float
    current_capital: float
    trades: list[Trade] = field(default_factory=list)
    active_trades: dict[str, Trade] = field(default_factory=dict) # Key: symbol
    equity_curve: list[dict] = field(default_factory=list) # Time series of capital

    def update_equity(self, timestamp: datetime):
        # Calculate unrealized PnL? For simplicity, we track realized + cash.
        # Advanced: Mark to market.
        equity = self.current_capital
        # Add unrealized PnL of active trades? To save time, we only update equity on close or EOD.
        # Just recording realized balance for now.
        self.equity_curve.append({"time": timestamp, "equity": equity})

class BacktestEngine:
    def __init__(self, start_date: datetime, end_date: datetime, capital: float = 100000):
        self.start_date = start_date
        self.end_date = end_date
        self.capital = capital
        
        self.loader = get_data_loader()
        self.registry = get_strategy_registry()
        self.universe = get_universe()
        
        # Portfolios: One for each strategy + 'Combined' + 'Best'
        self.portfolios: dict[str, PortfolioState] = {}
        
        # Initialize portfolios
        strategies = self.registry.get_enabled_strategies()
        for s in strategies:
            self.portfolios[s.name] = PortfolioState(s.name, capital, capital)
        
        self.portfolios["COMBINED"] = PortfolioState("COMBINED", capital, capital)
    
    def run(self):
        """Run the backtest simulation."""
        logger.info(f"🚀 Starting Backtest: {self.start_date.date()} to {self.end_date.date()}")
        
        # 1. Resolve Universe Tokens (if needed, or just use symbols)
        # For historical data, we mostly need Symbol + Exchange. Token is needed if API demands it.
        self.universe.resolve_tokens()
        
        # 2. Iterate each Symbol (Series-Parallel approach)
        # We simulate one symbol's full history, then next.
        # True portfolio simulation requires interleaving time across ALL symbols (Complex).
        # "Simplified Portfolio": We assume independent allocation per symbol.
        # BUT for "Parallel Portfolios" requirement (comparing strategies), running symbol-by-symbol is fine
        # as long as we track the "Strategy's Performance on Symbol X" and aggregate later.
        
        # However, to simulate "Maximum Capital" constraints, we usually need time-interleaved.
        # For this version (v1), we will run Symbol-by-Symbol and sum up P&L.
        # This assumes infinite capital or allocated capital/symbol. 
        # Let's assume Fixed Capital per Trade (e.g. 10k) to verify strategy edge.
        
        results = {}
        
        for stock in tqdm(NIFTY_30_WEIGHTED, desc="Backtesting Symbols"):
            if not stock.token:
                continue
                
            # Fetch Data
            df = self.loader.fetch_data(
                stock.symbol, stock.token, self.start_date, self.end_date
            )
            
            if df.empty:
                continue
            
            # Pre-calculate Indicators
            df = IndicatorEngine.add_all_indicators(df)
            
            # Run Simulation for this symbol
            self._simulate_symbol(stock, df)
            
        logger.info("✅ Backtest Complete.")
        return self.portfolios

    def _simulate_symbol(self, stock, df: pd.DataFrame):
        """Simulate time for a single symbol."""
        
        # We maintain state for this symbol across all strategies
        # (Actually strategies are stateless usually, but 'registry evaluated' is what matters)
        
        # Loop through candles
        records = df.to_dict('records') # List of rows
        timestamps = df.index.to_list()
        
        # Keep track of local active trades per strategy to avoid re-entry
        # Re-using global portfolios is tricky if we do symbol-by-symbol without sorting by time.
        # CORRECT APPROACH for Symbol-by-Symbol:
        # We are effectively testing "How would Strategy X perform on Symbol Y".
        # We add the trades to the Strategy's portfolio.
        
        # Opening Ranges storage
        opening_range: Optional[OpeningRange] = None
        current_date = None
        
        for i, row in enumerate(records):
            timestamp = timestamps[i]
            
            # Reset daily state
            if current_date != timestamp.date():
                current_date = timestamp.date()
                opening_range = None
            
            # Build MarketState
            state = self._build_state(stock, df, i, row, timestamp, opening_range)
            
            # Update Opening Range
            if 0 <= (timestamp.hour * 60 + timestamp.minute) - (9 * 60 + 15) <= 15:
                 # 9:15 to 9:30
                 if opening_range is None:
                     opening_range = OpeningRange(row['high'], row['low'], timestamp)
                 else:
                     opening_range.high = max(opening_range.high, row['high'])
                     opening_range.low = min(opening_range.low, row['low'])
            
            # State Update with ORB
            if opening_range:
                state.opening_range = opening_range

            # Manage Existing Trades (Check Exits)
            self._manage_trades(stock.symbol, row, timestamp)
            
            # Check Entries (if no position)
            # Eval strategies
            signals = self.registry.evaluate_all(state)
            
            for signal in signals:
                if not signal.is_actionable():
                    continue
                
                # Apply to specific strategy portfolio
                self._process_signal(self.portfolios.get(signal.strategy_name), signal, row)
                
                # Apply to 'COMBINED' (Naive: Take all signals?)
                # self._process_signal(self.portfolios["COMBINED"], signal, row)

    def _build_state(self, stock, df, i, row, timestamp, opening_range):
        # Extract IndicatorValues from row
        indicators = IndicatorValues(
            ema_9=row.get('ema_9'),
            ema_21=row.get('ema_21'),
            ema_50=row.get('ema_50'),
            rsi_14=row.get('rsi_14'),
            vwap=row.get('vwap'),
            atr_14=row.get('atr_14')
            # ... add others as needed
        )
        
        # Candles slice (expensive to copy list every time, but needed for pattern detection)
        # Limit to last 50
        slice_start = max(0, i-50)
        recent_candles = [
            Candle(
                timestamp=df.index[j],
                open=df.iloc[j]['open'],
                high=df.iloc[j]['high'],
                low=df.iloc[j]['low'],
                close=df.iloc[j]['close'],
                volume=df.iloc[j]['volume']
            ) for j in range(slice_start, i+1)
        ]

        state = MarketState(
            symbol=stock.symbol,
            token=stock.token,
            exchange=stock.exchange,
            current_price=row['close'],
            current_time=timestamp,
            candles_5m=recent_candles,
            indicators=indicators,
            opening_range=opening_range
            # Prev day high/low would need lookup, skipping for v1 Speed
        )
        return state

    def _manage_trades(self, symbol, row, timestamp):
        """Check exits for all active trades in all portfolios."""
        high = row['high']
        low = row['low']
        
        for name, pf in self.portfolios.items():
            if symbol in pf.active_trades:
                trade = pf.active_trades[symbol]
                
                exit_price = None
                reason = ""
                
                # Logic: Check exits
                if trade.side == "LONG":
                     if low <= trade.stop_loss:
                         exit_price = trade.stop_loss
                         reason = "Stop Loss"
                     elif high >= trade.target:
                         exit_price = trade.target
                         reason = "Target"
                else: # SHORT
                     if high >= trade.stop_loss:
                         exit_price = trade.stop_loss
                         reason = "Stop Loss"
                     elif low <= trade.target:
                         exit_price = trade.target
                         reason = "Target"
                         
                # End of Day Squareoff (approx 3:15 PM)
                if timestamp.hour == 15 and timestamp.minute >= 15:
                    exit_price = row['close']
                    reason = "EOD Squareoff"

                if exit_price:
                    self._close_trade(pf, symbol, exit_price, timestamp, reason)

    def _process_signal(self, pf: PortfolioState, signal: Signal, row):
        if not pf: return
        
        # Only take trade if no active trade for this symbol
        if signal.symbol in pf.active_trades:
            return
            
        # Capital Check (Fixed bet size: 10,000 INR per trade)
        bet_size = 10000
        qty = int(bet_size / row['close'])
        if qty < 1: return
        
        side = "LONG" if signal.signal_type == SignalType.LONG else "SHORT"
        
        trade = Trade(
            strategy=signal.strategy_name,
            symbol=signal.symbol,
            entry_time=signal.timestamp,
            entry_price=row['close'],
            quantity=qty,
            side=side,
            stop_loss=signal.stop_loss,
            target=signal.target
        )
        
        pf.active_trades[signal.symbol] = trade
        # logger.debug(f"{pf.name}: Entered {side} {signal.symbol} at {row['close']}")

    def _close_trade(self, pf: PortfolioState, symbol: str, price: float, time: datetime, reason: str):
        trade = pf.active_trades.pop(symbol)
        trade.exit_price = price
        trade.exit_time = time
        trade.exit_reason = reason
        
        # Calc PnL
        if trade.side == "LONG":
            trade.pnl = (trade.exit_price - trade.entry_price) * trade.quantity
        else:
            trade.pnl = (trade.entry_price - trade.exit_price) * trade.quantity
            
        pf.current_capital += trade.pnl
        pf.trades.append(trade)
        # logger.debug(f"{pf.name}: Closed {symbol} PnL: {trade.pnl:.2f} ({reason})")
