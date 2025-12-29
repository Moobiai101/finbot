"""Trading executor - orchestrates the complete trading pipeline."""

from datetime import datetime, time, timedelta
from typing import Optional
from dataclasses import dataclass, field
import pandas as pd
from loguru import logger

from finbot.config import get_settings, TradingMode
from finbot.broker.base import BaseBroker, Side, TradeResult
from finbot.broker.angel_client import get_angel_client, AngelOneClient
from finbot.broker.paper_broker import get_paper_broker, PaperBroker
from finbot.data.market_state import MarketState, Candle, OpeningRange
from finbot.data.indicators import IndicatorEngine, IndicatorValues
from finbot.data.scanner import get_scanner, HotStock
from finbot.strategies.registry import get_strategy_registry, StrategyRegistry
from finbot.strategies.base import Signal, SignalType
from finbot.risk.risk_engine import get_risk_engine, RiskEngine


@dataclass
class TradeContext:
    """Context for an active trade."""
    signal: Signal
    entry_time: datetime
    quantity: int
    stop_loss: float
    target: float
    trailing_stop: Optional[float] = None
    highest_price: Optional[float] = None  # For trailing stop
    lowest_price: Optional[float] = None


class TradingExecutor:
    """
    Main trading orchestrator.
    
    Connects all components:
    - Broker (live or paper)
    - Strategy registry
    - Risk engine
    - Data pipeline
    
    Runs the trading loop:
    1. Pre-market prep (levels, scanner)
    2. Live trading (signal generation, execution)
    3. End of day (square off, reporting)
    """
    
    def __init__(self):
        """Initialize trading executor."""
        self.settings = get_settings()
        
        # Components
        self.angel_client: Optional[AngelOneClient] = None
        self.broker: Optional[BaseBroker] = None
        self.registry: StrategyRegistry = get_strategy_registry()
        self.risk_engine: RiskEngine = get_risk_engine()
        self.scanner = get_scanner()
        
        # State
        self.is_running = False
        self.active_trades: dict[str, TradeContext] = {}
        self.watchlist: list[HotStock] = []
        self.market_states: dict[str, MarketState] = {}
        
        # Opening ranges (built 9:15-9:30)
        self.opening_ranges: dict[str, OpeningRange] = {}
        
        logger.info("TradingExecutor initialized")
    
    async def initialize(self) -> bool:
        """Initialize broker and connect to market data."""
        try:
            # Initialize Angel One for market data
            self.angel_client = get_angel_client()
            
            # Try restore or login
            if not await self.angel_client.try_restore_session():
                await self.angel_client.login()
            logger.info("✅ Connected to Angel One")
            
            # Set up broker based on mode
            if self.settings.trading_mode == TradingMode.PAPER:
                self.broker = get_paper_broker()
                await self.broker.login()
                logger.info("📝 Running in PAPER trading mode")
            else:
                # For live mode, use Angel One directly
                logger.info("🔴 Running in LIVE trading mode")
            
            return True
            
        except Exception as e:
            logger.error(f"Initialization failed: {e}")
            return False
    
    def run_pre_market(self) -> None:
        """
        Pre-market preparation (run before 9:15).
        
        - Scan for hot stocks
        - Fetch previous day data
        - Calculate support/resistance levels
        - Set up watchlist
        """
        logger.info("🌅 Running pre-market preparation...")
        
        # Scan for hot stocks
        self.watchlist = self.scanner.scan_all(top_n=20)
        logger.info(f"Watchlist: {len(self.watchlist)} stocks")
        
        # Prepare market state for each stock
        for stock in self.watchlist:
            try:
                state = self._prepare_market_state(stock)
                if state:
                    self.market_states[f"{state.exchange}:{state.symbol}"] = state
            except Exception as e:
                logger.warning(f"Failed to prepare {stock.symbol}: {e}")
        
        logger.info(f"✅ Pre-market complete. {len(self.market_states)} stocks ready.")
    
    def run_trading_loop(self) -> None:
        """
        Main trading loop.
        
        Called repeatedly during market hours.
        """
        if not self._is_trading_time():
            return
        
        # Check for square off time
        if self._is_square_off_time():
            self._square_off_all()
            return
        
        # Update market states
        self._update_all_states()
        
        # Manage active trades
        self._manage_active_trades()
        
        # Look for new opportunities (if we can take more trades)
        if self.risk_engine.can_trade().passed:
            self._scan_for_signals()
    
    def _prepare_market_state(self, stock: HotStock) -> Optional[MarketState]:
        """Prepare initial market state for a stock."""
        try:
            # Get previous day data
            prev_day = self.angel_client.get_previous_day_data(
                symbol=stock.symbol,
                token=stock.token,
                exchange=stock.exchange,
            )
            
            # Get historical 5m candles
            end = datetime.now()
            start = end - timedelta(days=3)
            
            candles = self.angel_client.get_historical_data(
                symbol=stock.symbol,
                token=stock.token,
                exchange=stock.exchange,
                interval="5m",
                from_date=start,
                to_date=end,
            )
            
            # Calculate indicators
            if candles:
                df = pd.DataFrame([{
                    'timestamp': c.timestamp,
                    'open': c.open,
                    'high': c.high,
                    'low': c.low,
                    'close': c.close,
                    'volume': c.volume,
                } for c in candles])
                
                indicators = IndicatorEngine.calculate_all(df)
                supports, resistances = IndicatorEngine.find_support_resistance(df)
            else:
                indicators = IndicatorValues()
                supports, resistances = [], []
            
            # Create market state
            state = MarketState(
                symbol=stock.symbol,
                token=stock.token,
                exchange=stock.exchange,
                current_price=stock.ltp,
                current_time=datetime.now(),
                candles_5m=[Candle(
                    timestamp=c.timestamp,
                    open=c.open,
                    high=c.high,
                    low=c.low,
                    close=c.close,
                    volume=c.volume,
                ) for c in candles[-50:]] if candles else [],
                indicators=indicators,
                prev_day_high=prev_day.high if prev_day else None,
                prev_day_low=prev_day.low if prev_day else None,
                prev_day_close=prev_day.close if prev_day else None,
                support_levels=supports,
                resistance_levels=resistances,
                volume_ratio=1.0,
            )
            
            # Calculate pivot points if we have prev day data
            if prev_day:
                pivots = IndicatorEngine.calculate_pivot_points(
                    prev_day.high, prev_day.low, prev_day.close
                )
                state.pivot_pp = pivots['PP']
                state.pivot_r1 = pivots['R1']
                state.pivot_r2 = pivots['R2']
                state.pivot_s1 = pivots['S1']
                state.pivot_s2 = pivots['S2']
            
            return state
            
        except Exception as e:
            logger.error(f"Error preparing market state for {stock.symbol}: {e}")
            return None
    
    def _update_all_states(self) -> None:
        """Update market states with latest data."""
        for key, state in self.market_states.items():
            try:
                # Get current LTP
                ltp = self.angel_client.get_ltp(
                    state.exchange, state.symbol, state.token
                )
                
                if ltp:
                    state.current_price = ltp
                    state.last_updated = datetime.now()
                    
                    # Update opening range if in formation period
                    self._update_opening_range(state)
                    
            except Exception as e:
                logger.warning(f"Failed to update {key}: {e}")
    
    def _update_opening_range(self, state: MarketState) -> None:
        """Update opening range for ORB strategy."""
        now = datetime.now().time()
        
        # Opening range formation: 9:15 - 9:30
        if time(9, 15) <= now <= time(9, 30):
            key = f"{state.exchange}:{state.symbol}"
            
            if key not in self.opening_ranges:
                self.opening_ranges[key] = OpeningRange(
                    high=state.current_price,
                    low=state.current_price,
                    formed_at=datetime.now(),
                )
            else:
                orb = self.opening_ranges[key]
                orb.high = max(orb.high, state.current_price)
                orb.low = min(orb.low, state.current_price)
        
        # Set opening range on state after 9:30
        elif now > time(9, 30):
            key = f"{state.exchange}:{state.symbol}"
            if key in self.opening_ranges:
                state.opening_range = self.opening_ranges[key]
    
    def _scan_for_signals(self) -> None:
        """Scan all stocks for trading signals."""
        for key, state in self.market_states.items():
            # Skip if we already have a position
            if key in self.active_trades:
                continue
            
            # Get best signal
            signal = self.registry.get_best_signal(state)
            
            if signal and signal.is_actionable():
                self._execute_signal(signal, state)
    
    def _execute_signal(self, signal: Signal, state: MarketState) -> None:
        """Execute a trading signal."""
        # Validate with risk engine
        risk_check = self.risk_engine.validate_signal(signal)
        
        if not risk_check.passed:
            logger.info(f"Signal rejected: {risk_check.reason}")
            return
        
        quantity = risk_check.adjusted_quantity
        
        # Determine trade side
        side = Side.BUY if signal.signal_type == SignalType.LONG else Side.SELL
        
        # Execute via broker
        if self.settings.trading_mode == TradingMode.PAPER:
            result = self.broker.place_order(
                symbol=state.symbol,
                token=state.token,
                exchange=state.exchange,
                side=side,
                quantity=quantity,
            )
        else:
            # Live execution
            from finbot.broker.angel_client import TransactionType, ProductType
            order_id = self.angel_client.place_order(
                symbol=state.symbol,
                token=state.token,
                exchange=state.exchange,
                transaction_type=TransactionType.BUY if side == Side.BUY else TransactionType.SELL,
                quantity=quantity,
                product_type=ProductType.INTRADAY,
            )
            result = TradeResult(
                success=order_id is not None,
                order_id=order_id,
                fill_price=state.current_price,
                quantity=quantity,
            )
        
        if result.success:
            # Track active trade
            key = f"{state.exchange}:{state.symbol}"
            self.active_trades[key] = TradeContext(
                signal=signal,
                entry_time=datetime.now(),
                quantity=quantity,
                stop_loss=signal.stop_loss,
                target=signal.target,
            )
            
            self.risk_engine.trades_today += 1
            
            logger.info(
                f"✅ Trade executed: {signal.signal_type.value} {quantity} {state.symbol} "
                f"@ ₹{result.fill_price:.2f} | SL: ₹{signal.stop_loss:.2f} | T: ₹{signal.target:.2f}"
            )
    
    def _manage_active_trades(self) -> None:
        """Manage active trades (check SL/target)."""
        for key, trade in list(self.active_trades.items()):
            state = self.market_states.get(key)
            if not state:
                continue
            
            price = state.current_price
            
            # Check stop loss
            if trade.signal.signal_type == SignalType.LONG:
                if price <= trade.stop_loss:
                    self._close_trade(key, "Stop loss hit")
                elif price >= trade.target:
                    self._close_trade(key, "Target hit")
            else:  # SHORT
                if price >= trade.stop_loss:
                    self._close_trade(key, "Stop loss hit")
                elif price <= trade.target:
                    self._close_trade(key, "Target hit")
    
    def _close_trade(self, key: str, reason: str) -> None:
        """Close a trade."""
        trade = self.active_trades.get(key)
        if not trade:
            return
        
        state = self.market_states.get(key)
        if not state:
            return
        
        # Opposite side to close
        side = Side.SELL if trade.signal.signal_type == SignalType.LONG else Side.BUY
        
        if self.settings.trading_mode == TradingMode.PAPER:
            result = self.broker.place_order(
                symbol=state.symbol,
                token=state.token,
                exchange=state.exchange,
                side=side,
                quantity=trade.quantity,
            )
        else:
            from finbot.broker.angel_client import TransactionType, ProductType
            order_id = self.angel_client.place_order(
                symbol=state.symbol,
                token=state.token,
                exchange=state.exchange,
                transaction_type=TransactionType.SELL if side == Side.SELL else TransactionType.BUY,
                quantity=trade.quantity,
                product_type=ProductType.INTRADAY,
            )
            result = TradeResult(success=order_id is not None, order_id=order_id)
        
        if result.success:
            # Calculate P&L
            entry = trade.signal.entry_price
            exit_price = state.current_price
            
            if trade.signal.signal_type == SignalType.LONG:
                pnl = (exit_price - entry) * trade.quantity
            else:
                pnl = (entry - exit_price) * trade.quantity
            
            self.risk_engine.update_pnl(pnl)
            
            del self.active_trades[key]
            
            logger.info(
                f"📉 Trade closed: {state.symbol} | Reason: {reason} | "
                f"P&L: ₹{pnl:+,.2f}"
            )
    
    def _square_off_all(self) -> None:
        """Square off all positions at end of day."""
        logger.info("🔔 Square off time - closing all positions")
        
        for key in list(self.active_trades.keys()):
            self._close_trade(key, "End of day square off")
        
        if self.settings.trading_mode == TradingMode.PAPER:
            self.broker.square_off_all()
    
    def _is_trading_time(self) -> bool:
        """Check if current time is within trading hours."""
        now = datetime.now().time()
        return time(9, 15) <= now <= time(15, 30)
    
    def _is_square_off_time(self) -> bool:
        """Check if it's square off time."""
        now = datetime.now().time()
        sq_parts = self.settings.square_off_time.split(":")
        square_off = time(int(sq_parts[0]), int(sq_parts[1]))
        return now >= square_off
    
    def get_status(self) -> dict:
        """Get executor status."""
        # Read current mode from database for real-time sync with frontend
        from finbot.database import get_db
        try:
            import asyncio
            db = get_db()
            # Run async method - get or create event loop
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
            current_mode = loop.run_until_complete(db.get_trading_mode())
        except Exception:
            current_mode = self.settings.trading_mode.value
        
        return {
            "mode": current_mode,
            "is_running": self.is_running,
            "watchlist_count": len(self.watchlist),
            "active_trades": len(self.active_trades),
            "risk_status": self.risk_engine.get_status(),
            "strategies": self.registry.get_strategy_stats(),
        }


# Singleton
_executor: Optional[TradingExecutor] = None


def get_executor() -> TradingExecutor:
    """Get or create executor singleton."""
    global _executor
    if _executor is None:
        _executor = TradingExecutor()
    return _executor
