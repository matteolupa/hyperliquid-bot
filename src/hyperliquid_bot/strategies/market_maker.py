"""Adaptive Market Maker Strategy (Avellaneda-Stoikov / Fee-Aware Grid).

Quotes bid/ask limit orders around mid-price, dynamically adjusting for inventory imbalance and fee thresholds.
"""

from dataclasses import dataclass
import logging
import time
from typing import Any, Dict, List, Optional
from .base import BaseStrategy
from ..client import HyperliquidClient
from ..fees import FeeCalculator
from ..risk import RiskManager

logger = logging.getLogger("hyperliquid_bot.strategy.market_maker")


@dataclass
class MarketMakingQuotes:
    """Represents the active bid/ask quotes."""

    symbol: str
    mid_price: float
    reservation_price: float
    bid_price: float
    ask_price: float
    order_size: float
    spread_bps: float
    inventory_units: float


class AdaptiveMarketMakerStrategy(BaseStrategy):
    """Fee-aware market maker quoting continuous bid/ask orders."""

    def __init__(
        self,
        client: HyperliquidClient,
        symbol: str = "ETH",
        risk_manager: Optional[RiskManager] = None,
        fee_calculator: Optional[FeeCalculator] = None,
        dry_run: bool = True,
        order_size_usd: float = 200.0,
        base_spread_bps: float = 8.0,  # 8 bps spread (0.08%)
        inventory_risk_gamma: float = 0.1,  # Inventory risk aversion factor
        max_inventory_usd: float = 2_000.0,
    ):
        super().__init__(
            client=client,
            risk_manager=risk_manager,
            fee_calculator=fee_calculator,
            dry_run=dry_run,
        )
        self.symbol = symbol
        self.order_size_usd = order_size_usd
        self.base_spread_bps = base_spread_bps
        self.inventory_risk_gamma = inventory_risk_gamma
        self.max_inventory_usd = max_inventory_usd

        # State tracking
        self.inventory_units: float = 0.0
        self.realized_pnl_usd: float = 0.0
        self.total_trades_count: int = 0
        self.last_quotes: Optional[MarketMakingQuotes] = None

    def calculate_reservation_price(
        self,
        mid_price: float,
        inventory_units: float,
    ) -> float:
        """Calculate Avellaneda-Stoikov reservation price based on current inventory.

        When inventory is positive (long), reservation price drops to incentivize selling.
        When inventory is negative (short), reservation price rises to incentivize buying.
        """
        # Inventory value relative to max allowed inventory
        inventory_usd = inventory_units * mid_price
        normalized_inventory = inventory_usd / max(self.max_inventory_usd, 1.0)

        # Shift reservation price by gamma * normalized_inventory * mid_price * spread
        skew_factor = self.inventory_risk_gamma * normalized_inventory * (self.base_spread_bps / 10_000.0)
        reservation_price = mid_price * (1.0 - skew_factor)
        return round(reservation_price, 4)

    def calculate_quotes(
        self,
        mid_price: float,
        inventory_units: float,
    ) -> MarketMakingQuotes:
        """Calculate optimal Bid and Ask prices ensuring fee profitability."""
        res_price = self.calculate_reservation_price(mid_price, inventory_units)

        # Minimum half-spread to ensure profit after round-trip maker fees (or rebates)
        # Tier 0 maker fee is 1 bps. Round trip = 2 bps. We want half-spread >= base_spread_bps / 2.
        half_spread_pct = (self.base_spread_bps / 2.0) / 10_000.0

        bid_price = round(res_price * (1.0 - half_spread_pct), 4)
        ask_price = round(res_price * (1.0 + half_spread_pct), 4)

        order_size = round(self.order_size_usd / mid_price, 4) if mid_price > 0 else 0.0
        spread_bps = round(((ask_price - bid_price) / mid_price) * 10_000.0, 2) if mid_price > 0 else 0.0

        return MarketMakingQuotes(
            symbol=self.symbol,
            mid_price=mid_price,
            reservation_price=res_price,
            bid_price=bid_price,
            ask_price=ask_price,
            order_size=order_size,
            spread_bps=spread_bps,
            inventory_units=inventory_units,
        )

    def on_start(self) -> None:
        self.is_running = True
        mode_str = "DRY-RUN (Simulazione)" if self.dry_run else "LIVE TRADING"
        logger.info(f"🚀 [{self.name}] Avviato su {self.symbol} in modalità: {mode_str}")
        logger.info(
            f"   Size Ordine: ${self.order_size_usd:.2f} | Base Spread: {self.base_spread_bps} bps | "
            f"Max Inventario: ${self.max_inventory_usd:.2f}"
        )

    def on_tick(self) -> None:
        if not self.is_running:
            return

        try:
            mids = self.client.get_all_mids()
            mid_price_str = mids.get(self.symbol)
            if not mid_price_str:
                logger.warning(f"Prezzo per {self.symbol} non disponibile al momento.")
                return

            mid_price = float(mid_price_str)
            quotes = self.calculate_quotes(mid_price, self.inventory_units)
            self.last_quotes = quotes

            # Risk check on order size
            if not self.risk_manager.validate_order(
                symbol=self.symbol,
                size=quotes.order_size,
                price=mid_price,
                current_position_usd=self.inventory_units * mid_price,
            ):
                logger.warning(f"Rischio superato su {self.symbol}. Skip quotazione.")
                return

            logger.info(
                f"📈 [{self.symbol}] Mid: ${mid_price:,.2f} | "
                f"BID: ${quotes.bid_price:,.2f} | ASK: ${quotes.ask_price:,.2f} | "
                f"Spread: {quotes.spread_bps} bps | Inventario: {quotes.inventory_units:.4f} units"
            )

            if self.dry_run:
                # In dry-run, we simulate passive quotes
                pass
            else:
                # In live mode, cancel old orders and place new post-only limit orders
                pass

        except Exception as e:
            logger.error(f"Errore durante tick di market making per {self.symbol}: {e}")

    def on_stop(self) -> None:
        self.is_running = False
        logger.info(
            f"🛑 [{self.name}] Fermato su {self.symbol}. "
            f"PnL Realizzato: ${self.realized_pnl_usd:.4f} | Trades: {self.total_trades_count}"
        )

    def get_status(self) -> Dict[str, Any]:
        return {
            "strategy": self.name,
            "symbol": self.symbol,
            "dry_run": self.dry_run,
            "inventory_units": self.inventory_units,
            "realized_pnl_usd": round(self.realized_pnl_usd, 4),
            "total_trades_count": self.total_trades_count,
            "last_quotes": (
                {
                    "mid_price": self.last_quotes.mid_price,
                    "bid_price": self.last_quotes.bid_price,
                    "ask_price": self.last_quotes.ask_price,
                    "spread_bps": self.last_quotes.spread_bps,
                }
                if self.last_quotes
                else None
            ),
        }
