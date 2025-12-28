"""Trading strategies module exports."""

from finbot.strategies.base import (
    BaseStrategy,
    Signal,
    SignalType,
    SignalStrength,
)
from finbot.strategies.orb import ORBStrategy
from finbot.strategies.vwap_bounce import VWAPBounceStrategy
from finbot.strategies.engulfing_levels import EngulfingLevelsStrategy
from finbot.strategies.ema_pullback import EMAPullbackStrategy
from finbot.strategies.break_retest import BreakRetestStrategy
from finbot.strategies.registry import StrategyRegistry, get_strategy_registry

__all__ = [
    # Base
    "BaseStrategy",
    "Signal",
    "SignalType",
    "SignalStrength",
    # Strategies
    "ORBStrategy",
    "VWAPBounceStrategy",
    "EngulfingLevelsStrategy",
    "EMAPullbackStrategy",
    "BreakRetestStrategy",
    # Registry
    "StrategyRegistry",
    "get_strategy_registry",
]
