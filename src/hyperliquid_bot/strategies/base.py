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

    def close_all_positions(self, reason: str = "Chiusura manuale da comando Telegram") -> str:
        """Emergency/manual closure of all active positions."""
        return "Nessuna posizione attiva da chiudere."

    def get_balance_report(self) -> str:
        """Return formatted balance and portfolio status."""
        equity = self.get_equity() or 0.0
        return (
            f"🏦 <b>Stato Portafoglio & Margine:</b>\n\n"
            f"▫️ <b>Strategia:</b> <code>{self.name}</code>\n"
            f"▫️ <b>Equity Totale:</b> <b>${equity:,.2f} USD</b>\n"
            f"▫️ <b>Modalità:</b> {'DRY-RUN (Simulazione)' if self.dry_run else 'LIVE TRADING'}"
        )

    def get_history_report(self, limit: int = 5) -> str:
        """Return formatted history of recent closed trades."""
        return "ℹ️ Nessuna cronologia disponibile per questa strategia."

    def get_watchlist_report(self, limit: int = 5) -> str:
        """Return formatted top market opportunities."""
        return "ℹ️ Nessuna watchlist disponibile per questa strategia."
