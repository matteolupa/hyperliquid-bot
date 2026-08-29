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
from ..persistence import StatePersistenceManager
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
        symbol: str = "SOL",
        order_size_usd: float = 100.0,
        base_spread_bps: float = 8.0,  # 8 bps spread (0.08%)
        inventory_risk_gamma: float = 0.1,  # Inventory risk aversion factor
        max_inventory_usd: float = 1_000.0,
        risk_manager: Optional[RiskManager] = None,
        fee_calculator: Optional[FeeCalculator] = None,
        dry_run: bool = True,
        telegram: Optional[Any] = None,
    ):
        super().__init__(
            client=client,
            risk_manager=risk_manager,
            fee_calculator=fee_calculator,
            dry_run=dry_run,
            telegram=telegram,
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
        self.avg_entry_price: float = 0.0

        self.persistence = StatePersistenceManager(
            filename=f"mm_state_{self.symbol}_{'dry' if self.dry_run else 'live'}.json"
        )

    def _save_state(self) -> None:
        data = {
            "inventory_units": self.inventory_units,
            "realized_pnl_usd": self.realized_pnl_usd,
            "total_trades_count": self.total_trades_count,
            "avg_entry_price": self.avg_entry_price,
        }
        self.persistence.save_state(data)

    def _restore_state(self) -> None:
        state = self.persistence.load_state()
        if not state:
            return
        self.inventory_units = state.get("inventory_units", 0.0)
        self.realized_pnl_usd = state.get("realized_pnl_usd", 0.0)
        self.total_trades_count = state.get("total_trades_count", 0)
        self.avg_entry_price = state.get("avg_entry_price", 0.0)
        logger.info(
            f"🔄 Ripristinato stato MM su {self.symbol}: Inventario={self.inventory_units:.4f} | "
            f"PnL Storico: +${self.realized_pnl_usd:.4f}"
        )

    def calculate_reservation_price(
        self,
        mid_price: float,
        inventory_units: float,
    ) -> float:
        """Calculate Avellaneda-Stoikov reservation price based on current inventory."""
        inventory_usd = inventory_units * mid_price
        normalized_inventory = inventory_usd / max(self.max_inventory_usd, 1.0)
        skew_factor = self.inventory_risk_gamma * normalized_inventory * (self.base_spread_bps / 10_000.0)
        reservation_price = mid_price * (1.0 - skew_factor)
        return round(reservation_price, 4)

    def calculate_quotes(
        self,
        mid_price: float,
        inventory_units: float,
    ) -> MarketMakingQuotes:
        """Calculate optimal Bid and Ask prices ensuring fee profitability and cost-basis protection."""
        res_price = self.calculate_reservation_price(mid_price, inventory_units)
        half_spread_pct = (self.base_spread_bps / 2.0) / 10_000.0

        bid_price = round(res_price * (1.0 - half_spread_pct), 4)
        raw_ask_price = round(res_price * (1.0 + half_spread_pct), 4)

        # COST-BASIS PROTECTION: If we hold inventory, NEVER quote ASK below entry price + fees!
        if inventory_units > 0 and self.avg_entry_price > 0:
            min_profitable_ask = round(self.avg_entry_price * (1.0 + half_spread_pct), 4)
            ask_price = max(raw_ask_price, min_profitable_ask)
        else:
            ask_price = raw_ask_price

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
        self._restore_state()
        mode_str = "DRY-RUN (Simulazione)" if self.dry_run else "LIVE TRADING"
        logger.info(f"🚀 [{self.name}] Avviato su {self.symbol} in modalità: {mode_str}")
        logger.info(
            f"   Size Ordine: ${self.order_size_usd:.2f} | Base Spread: {self.base_spread_bps} bps ({self.base_spread_bps/100:.3f}%) | "
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
            prev_quotes = self.last_quotes

            # Simulation of passive limit order fills in DRY-RUN
            if self.dry_run and prev_quotes:
                # 1. Price moved down through our Bid -> Buy Fill
                if mid_price <= prev_quotes.bid_price and (self.inventory_units * mid_price) < self.max_inventory_usd:
                    fill_size = prev_quotes.order_size
                    fill_price = prev_quotes.bid_price
                    fee = self.fee_calculator.calculate_trade_fee(size=fill_size, price=fill_price, is_maker=True)

                    total_cost = (self.inventory_units * self.avg_entry_price) + (fill_size * fill_price)
                    self.inventory_units += fill_size
                    self.avg_entry_price = total_cost / self.inventory_units if self.inventory_units > 0 else mid_price
                    self.total_trades_count += 1
                    self.realized_pnl_usd -= fee.total_fee_usd

                    logger.info(
                        f"📥 [MM BUY FILL (Maker)] {self.symbol}: {fill_size:.4f} units @ ${fill_price:,.2f} | "
                        f"Inventario: {self.inventory_units:.4f} units"
                    )
                    if self.telegram:
                        self.telegram.send_trade_alert(
                            action="MM BUY (Limit Fill)",
                            symbol=self.symbol,
                            size=fill_size,
                            price=fill_price,
                            notes=f"Inventario Attuale: {self.inventory_units:.4f} {self.symbol}",
                        )

                # 2. Price moved up through our Ask -> Sell Fill
                elif mid_price >= prev_quotes.ask_price and self.inventory_units > 0:
                    fill_size = min(self.inventory_units, prev_quotes.order_size)
                    fill_price = prev_quotes.ask_price
                    fee = self.fee_calculator.calculate_trade_fee(size=fill_size, price=fill_price, is_maker=True)

                    gross_profit = (fill_price - self.avg_entry_price) * fill_size
                    net_profit = gross_profit - fee.total_fee_usd
                    self.inventory_units -= fill_size
                    self.realized_pnl_usd += net_profit
                    self.total_trades_count += 1

                    logger.info(
                        f"🎯 [MM SELL FILL (Maker Spread Captured!)] {self.symbol}: {fill_size:.4f} units @ ${fill_price:,.2f} | "
                        f"Profitto Netto: +${net_profit:.4f} | PnL Totale: ${self.realized_pnl_usd:.4f}"
                    )
                    if self.telegram:
                        self.telegram.send_trade_alert(
                            action="MM SELL (Spread Incassato!)",
                            symbol=self.symbol,
                            size=fill_size,
                            price=fill_price,
                            pnl=net_profit,
                            notes=f"PnL Totale Accumulato: +${self.realized_pnl_usd:.4f} USD",
                        )

            # Calculate and set active quotes for the next tick based on updated inventory
            quotes = self.calculate_quotes(mid_price, self.inventory_units)
            self.last_quotes = quotes

            logger.info(
                f"📈 [{self.symbol}] Mid: ${mid_price:,.2f} | "
                f"BID: ${quotes.bid_price:,.2f} | ASK: ${quotes.ask_price:,.2f} | "
                f"Spread: {quotes.spread_bps} bps | Inventario: {quotes.inventory_units:.4f} | "
                f"PnL: ${self.realized_pnl_usd:+.4f}"
            )

            self._save_state()

        except Exception as e:
            logger.error(f"Errore durante tick di market making per {self.symbol}: {e}", exc_info=True)

    def on_stop(self) -> None:
        self.is_running = False
        self._save_state()
        logger.info(
            f"🛑 [{self.name}] Fermato su {self.symbol}. "
            f"PnL Realizzato: ${self.realized_pnl_usd:.4f} | Trades: {self.total_trades_count}"
        )

    def format_status_report(self) -> str:
        """Format human-readable market maker status report."""
        unrealized = 0.0
        if self.last_quotes and self.inventory_units > 0:
            unrealized = (self.last_quotes.mid_price - self.avg_entry_price) * self.inventory_units

        lines = [
            "\n" + "=" * 65,
            f"📊 [RESOCONTO MARKET MAKER & SPREAD ({self.symbol})]",
            f"   Trade / Fills Eseguiti:   {self.total_trades_count}",
            f"   Profitto Netto Realizzato: +${self.realized_pnl_usd:.4f} USD",
            f"   Inventario Attuale:       {self.inventory_units:.4f} {self.symbol} (${self.inventory_units * (self.last_quotes.mid_price if self.last_quotes else 0):,.2f})",
            f"   PnL Flottante Inventario: ${unrealized:+.4f} USD",
        ]
        if self.last_quotes:
            lines.append(f"   Quotazioni Attive:        BID ${self.last_quotes.bid_price:,.2f} | ASK ${self.last_quotes.ask_price:,.2f} (Spread: {self.last_quotes.spread_bps} bps)")
        lines.append("=" * 65)
        return "\n".join(lines)

    def get_status(self) -> Dict[str, Any]:
        return {
            "strategy": self.name,
            "symbol": self.symbol,
            "dry_run": self.dry_run,
            "inventory_units": self.inventory_units,
            "realized_pnl_usd": round(self.realized_pnl_usd, 4),
            "total_trades_count": self.total_trades_count,
            "formatted_report": self.format_status_report(),
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
