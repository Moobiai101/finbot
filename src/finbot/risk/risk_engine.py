"""Risk management engine."""

from dataclasses import dataclass
from datetime import datetime, time
from typing import Optional
from loguru import logger

from finbot.config import get_settings
from finbot.strategies.base import Signal, SignalType
from finbot.broker.base import PositionInfo


@dataclass
class RiskCheck:
    """Result of a risk check."""
    passed: bool
    reason: str
    adjusted_quantity: Optional[int] = None


class RiskEngine:
    """
    Risk management engine.
    
    Validates trades against risk parameters:
    - Position sizing
    - Daily loss limits
    - Max positions
    - Time-based restrictions
    """
    
    def __init__(self, capital: Optional[float] = None):
        """Initialize risk engine."""
        self.settings = get_settings()
        self.capital = capital or self.settings.trading_capital
        
        # Daily tracking
        self.daily_pnl = 0.0
        self.trades_today = 0
        self.daily_loss_limit_hit = False
        
        # Position tracking
        self.open_positions: list[PositionInfo] = []
    
    def reset_daily(self) -> None:
        """Reset daily counters (call at start of day)."""
        self.daily_pnl = 0.0
        self.trades_today = 0
        self.daily_loss_limit_hit = False
        logger.info("Risk engine: Daily counters reset")
    
    def update_pnl(self, pnl: float) -> None:
        """Update daily P&L."""
        self.daily_pnl += pnl
        
        # Check daily loss limit
        max_loss = self.settings.max_daily_loss_amount
        if self.daily_pnl <= -max_loss:
            self.daily_loss_limit_hit = True
            logger.warning(f"⚠️ Daily loss limit hit: ₹{self.daily_pnl:,.2f}")
    
    def can_trade(self) -> RiskCheck:
        """Check if we can take a new trade."""
        # Check daily loss limit
        if self.daily_loss_limit_hit:
            return RiskCheck(
                passed=False,
                reason=f"Daily loss limit hit (₹{self.settings.max_daily_loss_amount:,.0f})"
            )
        
        # Check max positions
        if len(self.open_positions) >= self.settings.max_positions:
            return RiskCheck(
                passed=False,
                reason=f"Max positions reached ({self.settings.max_positions})"
            )
        
        # Check trading time
        if not self._is_trading_time():
            return RiskCheck(
                passed=False,
                reason="Outside trading hours"
            )
        
        # Check entry cutoff
        if not self._before_entry_cutoff():
            return RiskCheck(
                passed=False,
                reason="Past entry cutoff time"
            )
        
        return RiskCheck(passed=True, reason="OK")
    
    def validate_signal(self, signal: Signal) -> RiskCheck:
        """Validate a trading signal against risk parameters."""
        # Basic can_trade check
        can_trade = self.can_trade()
        if not can_trade.passed:
            return can_trade
        
        # Check signal quality
        if not signal.is_actionable():
            return RiskCheck(
                passed=False,
                reason=f"Signal not actionable (confidence: {signal.confidence:.0%})"
            )
        
        # Check risk:reward
        if signal.risk_reward_ratio < 1.5:
            return RiskCheck(
                passed=False,
                reason=f"R:R too low ({signal.risk_reward_ratio:.1f}, need 1.5+)"
            )
        
        # Check stop loss is set
        if not signal.stop_loss:
            return RiskCheck(
                passed=False,
                reason="No stop loss defined"
            )
        
        # Calculate position size and validate
        quantity = self.calculate_position_size(signal)
        if quantity < 1:
            return RiskCheck(
                passed=False,
                reason="Position size too small"
            )
        
        return RiskCheck(
            passed=True,
            reason="OK",
            adjusted_quantity=quantity
        )
    
    def calculate_position_size(self, signal: Signal) -> int:
        """
        Calculate position size based on risk per trade.
        
        Uses fixed-risk position sizing:
        Position Size = (Capital * Risk%) / (Entry - Stop Loss)
        """
        if not signal.entry_price or not signal.stop_loss:
            return 0
        
        # Max risk per trade
        max_risk = self.capital * self.settings.max_risk_per_trade
        
        # Risk per share
        risk_per_share = abs(signal.entry_price - signal.stop_loss)
        
        if risk_per_share == 0:
            return 0
        
        # Calculate quantity
        quantity = int(max_risk / risk_per_share)
        
        # Check against max position value
        position_value = quantity * signal.entry_price
        max_position = self.settings.max_position_value
        
        if position_value > max_position:
            quantity = int(max_position / signal.entry_price)
        
        # Minimum 1 share
        return max(1, quantity)
    
    def check_stop_loss(
        self,
        position: PositionInfo,
        stop_loss: float,
    ) -> bool:
        """Check if stop loss is hit."""
        if position.side.value == "BUY":
            return position.current_price <= stop_loss
        else:
            return position.current_price >= stop_loss
    
    def check_target(
        self,
        position: PositionInfo,
        target: float,
    ) -> bool:
        """Check if target is hit."""
        if position.side.value == "BUY":
            return position.current_price >= target
        else:
            return position.current_price <= target
    
    def _is_trading_time(self) -> bool:
        """Check if current time is within trading hours."""
        now = datetime.now().time()
        
        market_open = time(9, 15)
        market_close = time(15, 30)
        
        return market_open <= now <= market_close
    
    def _before_entry_cutoff(self) -> bool:
        """Check if current time is before entry cutoff."""
        now = datetime.now().time()
        
        # Parse entry cutoff from settings (e.g., "14:30")
        cutoff_parts = self.settings.entry_cutoff.split(":")
        cutoff = time(int(cutoff_parts[0]), int(cutoff_parts[1]))
        
        return now <= cutoff
    
    def _is_square_off_time(self) -> bool:
        """Check if it's time to square off all positions."""
        now = datetime.now().time()
        
        # Parse square off time from settings
        sq_parts = self.settings.square_off_time.split(":")
        square_off = time(int(sq_parts[0]), int(sq_parts[1]))
        
        return now >= square_off
    
    def get_status(self) -> dict:
        """Get current risk status."""
        return {
            "capital": self.capital,
            "daily_pnl": self.daily_pnl,
            "daily_pnl_percent": (self.daily_pnl / self.capital) * 100,
            "trades_today": self.trades_today,
            "open_positions": len(self.open_positions),
            "max_positions": self.settings.max_positions,
            "daily_loss_limit_hit": self.daily_loss_limit_hit,
            "can_trade": self.can_trade().passed,
            "is_trading_time": self._is_trading_time(),
            "before_entry_cutoff": self._before_entry_cutoff(),
            "is_square_off_time": self._is_square_off_time(),
        }


# Singleton
_risk_engine: Optional[RiskEngine] = None


def get_risk_engine() -> RiskEngine:
    """Get or create risk engine singleton."""
    global _risk_engine
    if _risk_engine is None:
        _risk_engine = RiskEngine()
    return _risk_engine
