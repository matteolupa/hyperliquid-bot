"""Base strategy class for Hyperliquid Bot."""

from abc import ABC, abstractmethod
import logging
from typing import Any, Dict, Optional
from ..client import HyperliquidClient
from ..fees import FeeCalculator
from ..risk import RiskManager

logger = logging.getLogger("hyperliquid_bot.strategy")


class BaseStrategy(ABC):
    """Abstract Base Class for all trading strategies."""

    def __init__(
        self,
        client: HyperliquidClient,
        risk_manager: Optional[RiskManager] = None,
        fee_calculator: Optional[FeeCalculator] = None,
        dry_run: bool = True,
        telegram: Optional[Any] = None,
    ):
        self.client = client
        self.risk_manager = risk_manager or RiskManager()
        self.fee_calculator = fee_calculator or FeeCalculator()
        self.dry_run = dry_run
        self.telegram = telegram
        self.name = self.__class__.__name__
        self.is_running = False

    @abstractmethod
    def on_start(self) -> None:
        """Called when strategy starts."""
        pass

    @abstractmethod
    def on_tick(self) -> None:
        """Called on every iteration loop tick."""
        pass

    @abstractmethod
    def on_stop(self) -> None:
        """Called when strategy stops (cleanup/cancel orders)."""
        pass

    @abstractmethod
    def get_status(self) -> Dict[str, Any]:
        """Return diagnostic metrics and strategy status."""
        pass

    def get_equity(self) -> Optional[float]:
        """Return current strategy equity for risk and drawdown monitoring."""
        return None
