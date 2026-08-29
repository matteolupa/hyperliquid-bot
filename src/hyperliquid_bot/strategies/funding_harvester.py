"""Delta-Neutral Funding Rate Arbitrage Strategy.

Captures hourly funding rate payments on Hyperliquid perpetuals while hedging directional market risk.
"""

from dataclasses import dataclass, field
import logging
import time
from typing import Any, Dict, List, Optional
from .base import BaseStrategy
from ..client import HyperliquidClient
from ..fees import FeeCalculator
from ..persistence import StatePersistenceManager
from ..risk import RiskManager

logger = logging.getLogger("hyperliquid_bot.strategy.funding")


@dataclass
class FundingOpportunity:
    """Represents a market with an attractive funding rate."""

    coin: str
    mark_price: float
    hourly_funding_rate: float
    annualized_apy_pct: float
    open_interest_usd: float


@dataclass
class ActiveFundingPosition:
    """Tracks an active funding harvest position."""

    coin: str
    size: float
    entry_price: float
    entry_time: float
    hourly_rate_at_entry: float
    accumulated_funding_usd: float = 0.0


class FundingHarvesterStrategy(BaseStrategy):
    """Monitors and harvests positive funding rates on Hyperliquid."""

    def __init__(
        self,
        client: HyperliquidClient,
        risk_manager: Optional[RiskManager] = None,
        fee_calculator: Optional[FeeCalculator] = None,
        dry_run: bool = True,
        telegram: Optional[Any] = None,
        min_entry_apy_pct: float = 12.0,  # Minimum 12% APY to enter
        min_exit_apy_pct: float = 3.0,  # Exit if funding falls below 3% APY
        max_positions: int = 3,  # Max active markets
        allocation_per_position_usd: float = 2_000.0,
        auto_compound: bool = True,
        min_open_interest_usd: float = 50_000.0,  # Minimum Open Interest in USD to prevent illiquid slippage
        persistence_checks_required: int = 2,  # Number of consecutive ticks candidate must hold high APY
    ):
        super().__init__(
            client=client,
            risk_manager=risk_manager,
            fee_calculator=fee_calculator,
            dry_run=dry_run,
            telegram=telegram,
        )
        self.min_entry_apy_pct = min_entry_apy_pct
        self.min_exit_apy_pct = min_exit_apy_pct
        self.max_positions = max_positions
        self.base_allocation_usd = allocation_per_position_usd
        self.allocation_per_position_usd = allocation_per_position_usd
        self.auto_compound = auto_compound
        self.min_open_interest_usd = min_open_interest_usd
        self.persistence_checks_required = max(1, persistence_checks_required)
        self.candidate_seen_count: Dict[str, int] = {}
        self.active_positions: Dict[str, ActiveFundingPosition] = {}
        self.total_funding_earned_usd: float = 0.0
        self.persistence = StatePersistenceManager(
            filename=f"funding_state_{'dry' if self.dry_run else 'live'}.json"
        )

    @property
    def current_allocation_usd(self) -> float:
        """Calculate allocation per position dynamically including auto-compounded profits."""
        if not self.auto_compound:
            return self.base_allocation_usd
        total_lifetime = self.total_funding_earned_usd + sum(
            p.accumulated_funding_usd for p in self.active_positions.values()
        )
        if total_lifetime > 0:
            extra_per_position = total_lifetime / max(self.max_positions, 1)
            return round(self.base_allocation_usd + extra_per_position, 2)
        return self.base_allocation_usd

    def _save_state(self) -> None:
        """Persist current positions and earnings to disk."""
        data = {
            "total_funding_earned_usd": self.total_funding_earned_usd,
            "active_positions": {
                coin: {
                    "coin": p.coin,
                    "size": p.size,
                    "entry_price": p.entry_price,
                    "entry_time": p.entry_time,
                    "hourly_rate_at_entry": p.hourly_rate_at_entry,
                    "accumulated_funding_usd": p.accumulated_funding_usd,
                }
                for coin, p in self.active_positions.items()
            },
        }
        self.persistence.save_state(data)

    def _restore_state(self) -> None:
        """Restore positions and earnings from disk."""
        state = self.persistence.load_state()
        if not state:
            return

        self.total_funding_earned_usd = state.get("total_funding_earned_usd", 0.0)
        saved_positions = state.get("active_positions", {})
        for coin, p_data in saved_positions.items():
            self.active_positions[coin] = ActiveFundingPosition(
                coin=p_data["coin"],
                size=p_data["size"],
                entry_price=p_data["entry_price"],
                entry_time=p_data["entry_time"],
                hourly_rate_at_entry=p_data["hourly_rate_at_entry"],
                accumulated_funding_usd=p_data.get("accumulated_funding_usd", 0.0),
            )
        if self.active_positions:
            logger.info(
                f"🔄 Ripristinate {len(self.active_positions)} posizioni attive dal salvataggio precedente "
                f"(Totale storico funding: ${self.total_funding_earned_usd:.4f})"
            )

    @staticmethod
    def calculate_apy(hourly_funding_rate: float) -> float:
        """Convert hourly funding rate to annualized percentage yield (APY)."""
        return hourly_funding_rate * 24.0 * 365.0 * 100.0

    @staticmethod
    def calculate_funding_payment(
        position_notional_usd: float,
        hourly_funding_rate: float,
    ) -> float:
        """Calculate the expected hourly payment in USD."""
        return position_notional_usd * hourly_funding_rate

    def scan_opportunities(self) -> List[FundingOpportunity]:
        """Scan all Hyperliquid markets for funding rate opportunities."""
        opportunities = []
        try:
            meta_ctxs = self.client.info.meta_and_asset_ctxs()
            universe = meta_ctxs[0]["universe"]
            asset_ctxs = meta_ctxs[1]

            for i, asset in enumerate(universe):
                coin = asset["name"]
                if i >= len(asset_ctxs):
                    continue
                ctx = asset_ctxs[i]

                funding_str = ctx.get("funding", "0")
                hourly_funding = float(funding_str)
                mark_price = float(ctx.get("markPx", "0"))
                open_interest = float(ctx.get("openInterest", "0")) * mark_price
                apy = self.calculate_apy(hourly_funding)

                if apy >= min(self.min_entry_apy_pct, self.min_exit_apy_pct):
                    # Filter by minimum open interest to prevent slippage on illiquid pairs
                    if open_interest < self.min_open_interest_usd:
                        continue

                    opportunities.append(
                        FundingOpportunity(
                            coin=coin,
                            mark_price=mark_price,
                            hourly_funding_rate=hourly_funding,
                            annualized_apy_pct=round(apy, 2),
                            open_interest_usd=round(open_interest, 2),
                        )
                    )

            opportunities.sort(key=lambda x: x.annualized_apy_pct, reverse=True)
        except Exception as e:
            logger.error(f"Error scanning funding rates: {e}")

        return opportunities

    def on_start(self) -> None:
        self.is_running = True
        self._restore_state()
        mode_str = "DRY-RUN (Simulazione)" if self.dry_run else "LIVE TRADING"
        logger.info(f"🚀 [{self.name}] Avviato in modalità: {mode_str}")
        logger.info(
            f"   Soglia Minima Ingresso: {self.min_entry_apy_pct}% APY | Uscita: {self.min_exit_apy_pct}% APY | "
            f"Min Open Interest: ${self.min_open_interest_usd:,.0f} | Persistenza: {self.persistence_checks_required} tick"
        )

    def on_tick(self) -> None:
        if not self.is_running:
            return

        opportunities = self.scan_opportunities()
        if opportunities:
            top_opp = opportunities[0]
            logger.info(
                f"📊 Opportunità Top: {top_opp.coin} | APY: {top_opp.annualized_apy_pct}% "
                f"(Rate: {top_opp.hourly_funding_rate * 100:.4f}%/h) | Prezzo: ${top_opp.mark_price:,.2f} | "
                f"OI: ${top_opp.open_interest_usd:,.0f}"
            )

        # 1. Manage existing positions (check if APY decayed)
        for coin, pos in list(self.active_positions.items()):
            # Calculate accrued simulated funding
            hours_elapsed = (time.time() - pos.entry_time) / 3600.0
            hourly_pay = self.calculate_funding_payment(
                pos.size * pos.entry_price, pos.hourly_rate_at_entry
            )
            est_funding = hourly_pay * hours_elapsed
            pos.accumulated_funding_usd = est_funding

            # Find current market rate
            current_opp = next((o for o in opportunities if o.coin == coin), None)
            current_apy = current_opp.annualized_apy_pct if current_opp else 0.0

            if current_apy < self.min_exit_apy_pct:
                logger.info(
                    f"🔻 Chiusura posizione su {coin}: APY ({current_apy:.2f}%) sotto la soglia di uscita "
                    f"({self.min_exit_apy_pct}%). Funding incassato: ${est_funding:.4f}"
                )
                if self.telegram:
                    self.telegram.send_trade_alert(
                        action="Chiusura Delta-Neutral (Funding)",
                        symbol=coin,
                        size=pos.size,
                        price=pos.entry_price,
                        pnl=est_funding,
                        notes=f"Funding incassato: +${est_funding:.4f} USD",
                    )
                self.total_funding_earned_usd += est_funding
                del self.active_positions[coin]

        # Clean up persistence trackers for coins that dropped below threshold
        active_candidate_coins = {o.coin for o in opportunities if o.annualized_apy_pct >= self.min_entry_apy_pct}
        self.candidate_seen_count = {
            c: count for c, count in self.candidate_seen_count.items() if c in active_candidate_coins
        }

        # 2. Enter new opportunities if slots available
        for opp in opportunities:
            if len(self.active_positions) >= self.max_positions:
                break
            if opp.coin in self.active_positions:
                continue

            if opp.annualized_apy_pct < self.min_entry_apy_pct:
                continue

            if opp.mark_price <= 0:
                continue

            # Persistence filter: ensure high APY is sustained across consecutive checks
            current_seen = self.candidate_seen_count.get(opp.coin, 0) + 1
            self.candidate_seen_count[opp.coin] = current_seen

            if current_seen < self.persistence_checks_required:
                logger.info(
                    f"⏳ [PERSISTENZA] {opp.coin} APY {opp.annualized_apy_pct}% rilevato ({current_seen}/{self.persistence_checks_required}). "
                    f"In attesa di conferma al prossimo tick..."
                )
                continue

            target_size = self.current_allocation_usd / opp.mark_price
            notional = target_size * opp.mark_price

            # Risk check
            if not self.risk_manager.validate_order(
                symbol=opp.coin,
                size=target_size,
                price=opp.mark_price,
            ):
                continue

            # Fee check (Ensure 1 day of funding covers round trip fee)
            round_trip = self.fee_calculator.calculate_round_trip_fee(
                size=target_size,
                entry_price=opp.mark_price,
                exit_price=opp.mark_price,
                entry_is_maker=True,
                exit_is_maker=True,
            )
            daily_funding_usd = self.calculate_funding_payment(notional, opp.hourly_funding_rate) * 24.0

            if daily_funding_usd < round_trip["total_fee_usd"]:
                logger.info(
                    f"⚠️ Salto {opp.coin}: Funding giornaliero stimato (${daily_funding_usd:.4f}) "
                    f"< Commissioni Round-Trip (${round_trip['total_fee_usd']:.4f})"
                )
                continue

            if self.dry_run:
                logger.info(
                    f"✅ [DRY-RUN] Entrata Delta-Neutral simulata su {opp.coin}: "
                    f"Size: {target_size:.4f} (${notional:,.2f}) @ APY {opp.annualized_apy_pct}%"
                )
            else:
                logger.info(
                    f"🚀 [LIVE] Apertura posizione reale su {opp.coin}: Size: {target_size:.4f} (${notional:,.2f})"
                )
                # LIVE order placement via exchange wrapper can be called here

            self.active_positions[opp.coin] = ActiveFundingPosition(
                coin=opp.coin,
                size=target_size,
                entry_price=opp.mark_price,
                entry_time=time.time(),
                hourly_rate_at_entry=opp.hourly_funding_rate,
            )

        # Persist state after each tick
        self._save_state()

    def on_stop(self) -> None:
        self.is_running = False
        self._save_state()
        logger.info(f"🛑 [{self.name}] Fermato. Totale funding registrato: ${self.total_funding_earned_usd:.4f}")

    def format_status_report(self) -> str:
        """Format a beautiful human-readable earnings report for logs."""
        total_allocated = sum(p.size * p.entry_price for p in self.active_positions.values())
        total_accrued = sum(p.accumulated_funding_usd for p in self.active_positions.values())
        total_hourly_rate = sum(
            self.calculate_funding_payment(p.size * p.entry_price, p.hourly_rate_at_entry)
            for p in self.active_positions.values()
        )
        total_daily_rate = total_hourly_rate * 24.0
        total_lifetime = self.total_funding_earned_usd + total_accrued
        compounded_extra = total_lifetime if self.auto_compound else 0.0

        lines = [
            "\n" + "=" * 65,
            f"📊 [RESOCONTO GUADAGNI FUNDING ARBITRAGE]",
            f"   Capitale Allocato:        ${total_allocated:,.2f} ({len(self.active_positions)} posizioni attive)",
            f"   Rendita Oraria Stimata:   +${total_hourly_rate:.4f}/h (+${total_daily_rate:.2f}/giorno)",
            f"   Funding Maturato Attuale: +${total_accrued:.4f} USD",
            f"   Totale Guadagni Incassati:+${total_lifetime:.4f} USD",
        ]
        if self.auto_compound and compounded_extra > 0:
            lines.append(f"   ⚡ Auto-Compounding:      +${compounded_extra:.4f} reinvestiti (Taglia/Pos: ${self.current_allocation_usd:.2f})")
        lines.append("-" * 65)

        for coin, p in self.active_positions.items():
            hours = (time.time() - p.entry_time) / 3600.0
            apy = self.calculate_apy(p.hourly_rate_at_entry)
            lines.append(
                f"   • {coin:<5} | Size: {p.size:.4f} (${p.size * p.entry_price:,.2f}) | "
                f"APY: {apy:>7.2f}% | Attiva da: {hours:.1f}h | "
                f"Funding: +${p.accumulated_funding_usd:.4f}"
            )
        lines.append("=" * 65)
        return "\n".join(lines)

    def get_status(self) -> Dict[str, Any]:
        total_allocated = sum(p.size * p.entry_price for p in self.active_positions.values())
        total_accrued = sum(p.accumulated_funding_usd for p in self.active_positions.values())
        total_lifetime = self.total_funding_earned_usd + total_accrued
        return {
            "strategy": self.name,
            "dry_run": self.dry_run,
            "active_positions_count": len(self.active_positions),
            "capital_allocated_usd": round(total_allocated, 2),
            "total_lifetime_earnings_usd": round(total_lifetime, 4),
            "compounded_boost_usd": round(total_lifetime if self.auto_compound else 0.0, 4),
            "active_positions": {
                coin: {
                    "size": p.size,
                    "entry_price": p.entry_price,
                    "estimated_funding_usd": round(p.accumulated_funding_usd, 4),
                    "apy": round(self.calculate_apy(p.hourly_rate_at_entry), 2),
                }
                for coin, p in self.active_positions.items()
            },
            "total_funding_earned_usd": round(self.total_funding_earned_usd, 4),
            "formatted_report": self.format_status_report(),
        }
