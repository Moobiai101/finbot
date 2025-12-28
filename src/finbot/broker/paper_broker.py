"""Paper trading broker for simulation mode."""

import uuid
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, field

from loguru import logger

from finbot.config import get_settings
from finbot.broker.base import BaseBroker, Side, TradeResult, PositionInfo
from finbot.broker.angel_client import get_angel_client, AngelOneClient


@dataclass
class PaperPosition:
    """Paper trading position."""
    id: str
    symbol: str
    token: str
    exchange: str
    side: Side
    quantity: int
    entry_price: float
    entry_time: datetime
    stop_loss: Optional[float] = None
    target: Optional[float] = None


@dataclass
class PaperTrade:
    """Paper trade record."""
    id: str
    symbol: str
    token: str
    exchange: str
    side: Side
    quantity: int
    entry_price: float
    exit_price: Optional[float]
    pnl: Optional[float]
    entry_time: datetime
    exit_time: Optional[datetime]
    exit_reason: Optional[str]


class PaperBroker(BaseBroker):
    """
    Paper trading broker for simulation.
    
    Uses real market data from Angel One but simulates order execution.
    Tracks virtual P&L and positions.
    """
    
    # Simulated slippage (0.1% = 10 bps)
    SLIPPAGE_PERCENT = 0.001
    
    # Simulated brokerage per trade
    BROKERAGE_PER_TRADE = 20.0
    
    def __init__(self, capital: Optional[float] = None):
        """Initialize paper broker."""
        self.settings = get_settings()
        self.initial_capital = capital or self.settings.trading_capital
        self.available_capital = self.initial_capital
        
        # State
        self.positions: dict[str, PaperPosition] = {}
        self.trades: list[PaperTrade] = []
        self.total_pnl = 0.0
        self.total_brokerage = 0.0
        
        # Real broker for market data
        self._angel_client: Optional[AngelOneClient] = None
        self._is_connected = False
        
        logger.info(f"Paper broker initialized with ₹{self.initial_capital:,.2f}")
    
    async def login(self) -> bool:
        """Connect to Angel One for market data only."""
        try:
            self._angel_client = get_angel_client()
            # Try to restore session first, else login
            if not await self._angel_client.try_restore_session():
                await self._angel_client.login()
                
            self._is_connected = True
            logger.info("Paper broker connected to market data")
            return True
        except Exception as e:
            logger.warning(f"Paper broker running without live data: {e}")
            self._is_connected = False
            return False
    
    def logout(self) -> bool:
        """Disconnect from market data."""
        if self._angel_client:
            self._angel_client.logout()
        self._is_connected = False
        return True
    
    def get_ltp(self, symbol: str, token: str, exchange: str) -> Optional[float]:
        """Get LTP from Angel One."""
        if self._angel_client and self._is_connected:
            return self._angel_client.get_ltp(exchange, symbol, token)
        return None
    
    def place_order(
        self,
        symbol: str,
        token: str,
        exchange: str,
        side: Side,
        quantity: int,
        price: float = 0,
        order_type: str = "MARKET",
    ) -> TradeResult:
        """
        Simulate order placement.
        
        For market orders, uses current LTP with slippage.
        For limit orders, fills at the specified price (simplified).
        """
        try:
            # Get current price
            if order_type == "MARKET" or price == 0:
                current_price = self.get_ltp(symbol, token, exchange)
                if current_price is None:
                    return TradeResult(
                        success=False,
                        message="Failed to get current price",
                    )
                
                # Apply slippage
                if side == Side.BUY:
                    fill_price = current_price * (1 + self.SLIPPAGE_PERCENT)
                else:
                    fill_price = current_price * (1 - self.SLIPPAGE_PERCENT)
            else:
                fill_price = price
            
            # Calculate order value
            order_value = fill_price * quantity
            
            # Check if this is closing an existing position
            position_key = f"{exchange}:{symbol}"
            
            if position_key in self.positions:
                # Closing/reducing position
                position = self.positions[position_key]
                
                if position.side != side:
                    # Closing position
                    close_qty = min(quantity, position.quantity)
                    
                    # Calculate P&L
                    if position.side == Side.BUY:
                        pnl = (fill_price - position.entry_price) * close_qty
                    else:
                        pnl = (position.entry_price - fill_price) * close_qty
                    
                    # Deduct brokerage
                    pnl -= self.BROKERAGE_PER_TRADE
                    self.total_brokerage += self.BROKERAGE_PER_TRADE
                    
                    # Update capital
                    self.available_capital += pnl
                    self.total_pnl += pnl
                    
                    # Record trade
                    trade = PaperTrade(
                        id=str(uuid.uuid4()),
                        symbol=symbol,
                        token=token,
                        exchange=exchange,
                        side=position.side,
                        quantity=close_qty,
                        entry_price=position.entry_price,
                        exit_price=fill_price,
                        pnl=pnl,
                        entry_time=position.entry_time,
                        exit_time=datetime.now(),
                        exit_reason="manual_close",
                    )
                    self.trades.append(trade)
                    
                    # Update or remove position
                    if close_qty >= position.quantity:
                        del self.positions[position_key]
                    else:
                        position.quantity -= close_qty
                    
                    logger.info(
                        f"📉 Closed {close_qty} {symbol} @ ₹{fill_price:.2f} | "
                        f"P&L: ₹{pnl:+,.2f}"
                    )
                    
                    return TradeResult(
                        success=True,
                        order_id=trade.id,
                        fill_price=fill_price,
                        quantity=close_qty,
                        message=f"Position closed. P&L: ₹{pnl:+,.2f}",
                    )
            
            # Opening new position
            # Check margin
            margin_required = order_value / self.settings.effective_leverage
            
            if margin_required > self.available_capital:
                return TradeResult(
                    success=False,
                    message=f"Insufficient margin. Required: ₹{margin_required:,.2f}, Available: ₹{self.available_capital:,.2f}",
                )
            
            # Block margin
            self.available_capital -= margin_required
            self.total_brokerage += self.BROKERAGE_PER_TRADE
            
            # Create position
            order_id = str(uuid.uuid4())
            position = PaperPosition(
                id=order_id,
                symbol=symbol,
                token=token,
                exchange=exchange,
                side=side,
                quantity=quantity,
                entry_price=fill_price,
                entry_time=datetime.now(),
            )
            
            self.positions[position_key] = position
            
            logger.info(
                f"📈 Paper {side.value} {quantity} {symbol} @ ₹{fill_price:.2f} | "
                f"Value: ₹{order_value:,.2f}"
            )
            
            return TradeResult(
                success=True,
                order_id=order_id,
                fill_price=fill_price,
                quantity=quantity,
                message="Order filled",
            )
            
        except Exception as e:
            logger.error(f"Paper order error: {e}")
            return TradeResult(
                success=False,
                message=str(e),
            )
    
    def get_positions(self) -> list[PositionInfo]:
        """Get current paper positions with live P&L."""
        positions = []
        
        for key, pos in self.positions.items():
            current_price = self.get_ltp(pos.symbol, pos.token, pos.exchange)
            
            if current_price is None:
                current_price = pos.entry_price
            
            if pos.side == Side.BUY:
                pnl = (current_price - pos.entry_price) * pos.quantity
            else:
                pnl = (pos.entry_price - current_price) * pos.quantity
            
            pnl_percent = ((current_price - pos.entry_price) / pos.entry_price) * 100
            if pos.side == Side.SELL:
                pnl_percent = -pnl_percent
            
            positions.append(PositionInfo(
                symbol=pos.symbol,
                token=pos.token,
                side=pos.side,
                quantity=pos.quantity,
                entry_price=pos.entry_price,
                current_price=current_price,
                pnl=pnl,
                pnl_percent=pnl_percent,
            ))
        
        return positions
    
    def square_off_all(self) -> list[TradeResult]:
        """Close all open positions (end of day)."""
        results = []
        
        for key, pos in list(self.positions.items()):
            # Opposite side to close
            close_side = Side.SELL if pos.side == Side.BUY else Side.BUY
            
            result = self.place_order(
                symbol=pos.symbol,
                token=pos.token,
                exchange=pos.exchange,
                side=close_side,
                quantity=pos.quantity,
            )
            results.append(result)
        
        logger.info(f"Squared off {len(results)} positions")
        return results
    
    def get_available_margin(self) -> float:
        """Get available margin."""
        return self.available_capital
    
    def get_summary(self) -> dict:
        """Get trading summary."""
        return {
            "initial_capital": self.initial_capital,
            "current_capital": self.available_capital + self._get_position_value(),
            "available_margin": self.available_capital,
            "total_pnl": self.total_pnl,
            "total_brokerage": self.total_brokerage,
            "net_pnl": self.total_pnl - self.total_brokerage,
            "open_positions": len(self.positions),
            "total_trades": len(self.trades),
            "win_rate": self._calculate_win_rate(),
        }
    
    def _get_position_value(self) -> float:
        """Get total value of open positions."""
        total = 0.0
        for pos in self.get_positions():
            total += (pos.current_price * pos.quantity) / self.settings.effective_leverage
        return total
    
    def _calculate_win_rate(self) -> float:
        """Calculate win rate from closed trades."""
        if not self.trades:
            return 0.0
        
        wins = sum(1 for t in self.trades if (t.pnl or 0) > 0)
        return (wins / len(self.trades)) * 100


# Singleton
_paper_broker: Optional[PaperBroker] = None


def get_paper_broker() -> PaperBroker:
    """Get or create paper broker singleton."""
    global _paper_broker
    if _paper_broker is None:
        _paper_broker = PaperBroker()
    return _paper_broker
