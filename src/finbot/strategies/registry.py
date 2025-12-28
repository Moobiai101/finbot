"""Strategy Registry - Manages and orchestrates all strategies."""

from typing import Optional
from loguru import logger

from finbot.data.market_state import MarketState
from finbot.strategies.base import BaseStrategy, Signal, SignalType
from finbot.strategies.orb import ORBStrategy
from finbot.strategies.vwap_bounce import VWAPBounceStrategy
from finbot.strategies.engulfing_levels import EngulfingLevelsStrategy
from finbot.strategies.ema_pullback import EMAPullbackStrategy
from finbot.strategies.break_retest import BreakRetestStrategy


class StrategyRegistry:
    """
    Central registry for all trading strategies.
    
    Manages strategy lifecycle, evaluation, and signal aggregation.
    """
    
    def __init__(self):
        """Initialize registry with all strategies."""
        self.strategies: dict[str, BaseStrategy] = {}
        self._register_default_strategies()
    
    def _register_default_strategies(self) -> None:
        """Register all default strategies."""
        self.register(ORBStrategy())
        self.register(VWAPBounceStrategy())
        self.register(EngulfingLevelsStrategy())
        self.register(EMAPullbackStrategy())
        self.register(BreakRetestStrategy())
        
        logger.info(f"Registered {len(self.strategies)} strategies")
    
    def register(self, strategy: BaseStrategy) -> None:
        """Register a strategy."""
        self.strategies[strategy.name] = strategy
        logger.debug(f"Registered strategy: {strategy.name}")
    
    def get(self, name: str) -> Optional[BaseStrategy]:
        """Get a strategy by name."""
        return self.strategies.get(name)
    
    def enable(self, name: str) -> bool:
        """Enable a strategy."""
        if name in self.strategies:
            self.strategies[name].enabled = True
            logger.info(f"Enabled strategy: {name}")
            return True
        return False
    
    def disable(self, name: str) -> bool:
        """Disable a strategy."""
        if name in self.strategies:
            self.strategies[name].enabled = False
            logger.info(f"Disabled strategy: {name}")
            return True
        return False
    
    def set_enabled(self, config: dict[str, bool]) -> None:
        """
        Set enabled status for multiple strategies.
        
        Args:
            config: Dict with strategy name -> enabled status
        """
        for name, enabled in config.items():
            if name in self.strategies:
                self.strategies[name].enabled = enabled
    
    def get_enabled_strategies(self) -> list[BaseStrategy]:
        """Get list of enabled strategies."""
        return [s for s in self.strategies.values() if s.enabled]
    
    def evaluate_all(self, state: MarketState) -> list[Signal]:
        """
        Evaluate all enabled strategies against market state.
        
        Args:
            state: Current market state
            
        Returns:
            List of signals from all strategies
        """
        signals = []
        
        for strategy in self.get_enabled_strategies():
            try:
                signal = strategy.evaluate(state)
                signals.append(signal)
                
                if signal.signal_type in [SignalType.LONG, SignalType.SHORT]:
                    logger.info(
                        f"📊 {strategy.name}: {signal.signal_type.value} "
                        f"{state.symbol} | Confidence: {signal.confidence:.0%}"
                    )
                    
            except Exception as e:
                logger.error(f"Strategy {strategy.name} error: {e}")
        
        return signals
    
    def get_best_signal(
        self,
        state: MarketState,
        min_confidence: float = 0.65,
        min_rr: float = 1.5,
    ) -> Optional[Signal]:
        """
        Evaluate all strategies and return the best actionable signal.
        
        Args:
            state: Current market state
            min_confidence: Minimum required confidence
            min_rr: Minimum required risk:reward ratio
            
        Returns:
            Best signal or None if no good setup
        """
        signals = self.evaluate_all(state)
        
        # Filter actionable signals
        actionable = [
            s for s in signals
            if s.is_actionable(min_confidence) and s.risk_reward_ratio >= min_rr
        ]
        
        if not actionable:
            return None
        
        # Sort by confidence (highest first)
        actionable.sort(key=lambda x: x.confidence, reverse=True)
        
        best = actionable[0]
        logger.info(
            f"✅ Best signal: {best.strategy_name} - {best.signal_type.value} "
            f"{state.symbol} | Confidence: {best.confidence:.0%} | R:R: {best.risk_reward_ratio:.1f}"
        )
        
        return best
    
    def get_consensus_signal(
        self,
        state: MarketState,
        min_agreement: int = 2,
    ) -> Optional[Signal]:
        """
        Get signal only if multiple strategies agree.
        
        Args:
            state: Current market state
            min_agreement: Minimum number of strategies that must agree
            
        Returns:
            Aggregated signal or None
        """
        signals = self.evaluate_all(state)
        
        # Count longs and shorts
        longs = [s for s in signals if s.signal_type == SignalType.LONG]
        shorts = [s for s in signals if s.signal_type == SignalType.SHORT]
        
        if len(longs) >= min_agreement:
            # Average confidence
            avg_confidence = sum(s.confidence for s in longs) / len(longs)
            
            # Use the highest confidence signal as base
            best = max(longs, key=lambda x: x.confidence)
            
            return Signal(
                signal_type=SignalType.LONG,
                strategy_name=f"CONSENSUS ({len(longs)} strategies)",
                symbol=state.symbol,
                token=state.token,
                exchange=state.exchange,
                confidence=avg_confidence,
                entry_price=best.entry_price,
                stop_loss=best.stop_loss,
                target=best.target,
                reason=f"Consensus from: {', '.join(s.strategy_name for s in longs)}",
            )
        
        if len(shorts) >= min_agreement:
            avg_confidence = sum(s.confidence for s in shorts) / len(shorts)
            best = max(shorts, key=lambda x: x.confidence)
            
            return Signal(
                signal_type=SignalType.SHORT,
                strategy_name=f"CONSENSUS ({len(shorts)} strategies)",
                symbol=state.symbol,
                token=state.token,
                exchange=state.exchange,
                confidence=avg_confidence,
                entry_price=best.entry_price,
                stop_loss=best.stop_loss,
                target=best.target,
                reason=f"Consensus from: {', '.join(s.strategy_name for s in shorts)}",
            )
        
        return None
    
    def get_strategy_stats(self) -> dict:
        """Get statistics for all strategies."""
        stats = {}
        
        for name, strategy in self.strategies.items():
            stats[name] = {
                "enabled": strategy.enabled,
                "description": strategy.description,
                "signal_count": strategy._signal_count,
            }
        
        return stats


# Singleton
_registry: Optional[StrategyRegistry] = None


def get_strategy_registry() -> StrategyRegistry:
    """Get or create strategy registry singleton."""
    global _registry
    if _registry is None:
        _registry = StrategyRegistry()
    return _registry
