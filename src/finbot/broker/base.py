"""Base broker interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Any


class Side(str, Enum):
    """Trade side."""
    BUY = "BUY"
    SELL = "SELL"


@dataclass
class TradeResult:
    """Result of a trade execution."""
    success: bool
    order_id: Optional[str] = None
    fill_price: Optional[float] = None
    quantity: Optional[int] = None
    message: Optional[str] = None
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


@dataclass
class PositionInfo:
    """Position information."""
    symbol: str
    token: str
    side: Side
    quantity: int
    entry_price: float
    current_price: float
    pnl: float
    pnl_percent: float


class BaseBroker(ABC):
    """
    Abstract base class for broker implementations.
    
    Both AngelOneClient and PaperBroker implement this interface,
    allowing seamless switching between live and paper trading.
    """
    
    @abstractmethod
    def login(self) -> bool:
        """Authenticate with the broker."""
        pass
    
    @abstractmethod
    def logout(self) -> bool:
        """Disconnect from the broker."""
        pass
    
    @abstractmethod
    def get_ltp(self, symbol: str, token: str, exchange: str) -> Optional[float]:
        """Get last traded price."""
        pass
    
    @abstractmethod
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
        """Place an order."""
        pass
    
    @abstractmethod
    def get_positions(self) -> list[PositionInfo]:
        """Get current positions."""
        pass
    
    @abstractmethod
    def square_off_all(self) -> list[TradeResult]:
        """Close all open positions."""
        pass
    
    @abstractmethod
    def get_available_margin(self) -> float:
        """Get available margin/capital."""
        pass
