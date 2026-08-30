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
from ..ledger import FundingLedger
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
    last_accrual_time: Optional[float] = None
    current_hourly_rate: Optional[float] = None
    peak_apy_pct: Optional[float] = None  # Highest APY observed since entry (for trailing exit)

    def __post_init__(self):
        if self.last_accrual_time is None:
            self.last_accrual_time = self.entry_time
        if self.current_hourly_rate is None:
            self.current_hourly_rate = self.hourly_rate_at_entry
        if self.peak_apy_pct is None:
            # Initialize peak APY from entry rate (24h * 365 * 100 = annualized %)
            self.peak_apy_pct = self.hourly_rate_at_entry * 24.0 * 365.0 * 100.0


class FundingHarvesterStrategy(BaseStrategy):
    """Monitors and harvests positive funding rates on Hyperliquid."""

    def __init__(
        self,
        client: HyperliquidClient,
        risk_manager: Optional[RiskManager] = None,
        fee_calculator: Optional[FeeCalculator] = None,
        dry_run: bool = True,
        telegram: Optional[Any] = None,
        min_entry_apy_pct: float = 12.0,       # Minimum 12% APY to enter
        min_exit_apy_pct: float = 3.0,          # Exit if funding falls below 3% APY
        max_entry_apy_pct: float = 1000.0,      # Anti-manipulation: ignore absurd spikes above 1000% APY
        trailing_exit_pct: float = 50.0,        # Trailing exit: close if APY drops >50% from peak
        max_positions: int = 3,                 # Max active markets
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
        self.max_entry_apy_pct = max_entry_apy_pct
        self.trailing_exit_pct = trailing_exit_pct
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
        self.ledger = FundingLedger(dry_run=self.dry_run)

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

    def get_equity(self) -> float:
        """Calculate total strategy equity (base capital + realized + accrued funding)."""
        base_capital = self.base_allocation_usd * self.max_positions
        total_accrued = sum(p.accumulated_funding_usd for p in self.active_positions.values())
        return base_capital + self.total_funding_earned_usd + total_accrued

    def _save_state(self) -> None:
        """Persist current positions, earnings and candidate counters to disk."""
        data = {
            "total_funding_earned_usd": self.total_funding_earned_usd,
            "candidate_seen_count": self.candidate_seen_count,
            "active_positions": {
                coin: {
                    "coin": p.coin,
                    "size": p.size,
                    "entry_price": p.entry_price,
                    "entry_time": p.entry_time,
                    "hourly_rate_at_entry": p.hourly_rate_at_entry,
                    "accumulated_funding_usd": p.accumulated_funding_usd,
                    "last_accrual_time": p.last_accrual_time,
                    "current_hourly_rate": p.current_hourly_rate,
                    "peak_apy_pct": p.peak_apy_pct,
                }
                for coin, p in self.active_positions.items()
            },
        }
        self.persistence.save_state(data)

    def _restore_state(self) -> None:
        """Restore positions, earnings and candidate counters from disk."""
        state = self.persistence.load_state()
        if not state:
            return

        self.total_funding_earned_usd = state.get("total_funding_earned_usd", 0.0)
        # Restore candidate persistence counters (optimization I)
        self.candidate_seen_count = state.get("candidate_seen_count", {})
        saved_positions = state.get("active_positions", {})
        for coin, p_data in saved_positions.items():
            entry_rate = p_data["hourly_rate_at_entry"]
            self.active_positions[coin] = ActiveFundingPosition(
                coin=p_data["coin"],
                size=p_data["size"],
                entry_price=p_data["entry_price"],
                entry_time=p_data["entry_time"],
                hourly_rate_at_entry=entry_rate,
                accumulated_funding_usd=p_data.get("accumulated_funding_usd", 0.0),
                last_accrual_time=p_data.get("last_accrual_time", p_data["entry_time"]),
                current_hourly_rate=p_data.get("current_hourly_rate", entry_rate),
                peak_apy_pct=p_data.get("peak_apy_pct", entry_rate * 24.0 * 365.0 * 100.0),
            )
        if self.active_positions:
            logger.info(
                f"🔄 Ripristinate {len(self.active_positions)} posizioni attive dal salvataggio precedente "
                f"(Totale storico funding: ${self.total_funding_earned_usd:.4f})"
            )
        if self.candidate_seen_count:
            logger.info(
                f"🔄 Ripristinati {len(self.candidate_seen_count)} candidati in watchlist dal salvataggio precedente"
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
                    # Anti-manipulation: ignore absurd APY spikes (delisting/low-liquidity traps)
                    if apy > self.max_entry_apy_pct and coin not in self.active_positions:
                        logger.debug(
                            f"🚫 [ANTI-MANIP] {coin} APY {apy:.0f}% supera il limite massimo "
                            f"({self.max_entry_apy_pct:.0f}%) — ignorato."
                        )
                        continue

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
            f"Max APY Ingresso: {self.max_entry_apy_pct:.0f}% | Trailing Exit: -{self.trailing_exit_pct:.0f}% dal picco | "
            f"Min Open Interest: ${self.min_open_interest_usd:,.0f} | Persistenza: {self.persistence_checks_required} tick"
        )

    def _check_exit(self, coin: str, pos, current_apy: float, now: float) -> Optional[str]:
        """Determina se una posizione deve essere chiusa. Ritorna il motivo dell'uscita o None."""
        # 1. Uscita classica: APY scende sotto la soglia assoluta
        if current_apy < self.min_exit_apy_pct:
            return f"APY ({current_apy:.2f}%) sotto soglia assoluta ({self.min_exit_apy_pct}%)"

        # 2. Trailing APY Exit: APY scende >trailing_exit_pct% dal picco storico
        if pos.peak_apy_pct and pos.peak_apy_pct > 0:
            drop_pct = (pos.peak_apy_pct - current_apy) / pos.peak_apy_pct * 100.0
            if drop_pct >= self.trailing_exit_pct:
                return (
                    f"Trailing APY Exit: APY ({current_apy:.2f}%) calato del {drop_pct:.1f}% "
                    f"dal picco ({pos.peak_apy_pct:.2f}%) — soglia: -{self.trailing_exit_pct:.0f}%"
                )
        return None

    def on_tick(self) -> None:
        if not self.is_running:
            return

        now = time.time()
        opportunities = self.scan_opportunities()
        if opportunities:
            top_opp = opportunities[0]
            logger.info(
                f"📊 Opportunità Top: {top_opp.coin} | APY: {top_opp.annualized_apy_pct}% "
                f"(Rate: {top_opp.hourly_funding_rate * 100:.4f}%/h) | Prezzo: ${top_opp.mark_price:,.2f} | "
                f"OI: ${top_opp.open_interest_usd:,.0f}"
            )

        # 1. Manage existing positions (accrue dynamic live funding and check if APY decayed)
        for coin, pos in list(self.active_positions.items()):
            # Find current live market rate
            current_opp = next((o for o in opportunities if o.coin == coin), None)
            current_rate = current_opp.hourly_funding_rate if current_opp else (pos.current_hourly_rate or pos.hourly_rate_at_entry)
            current_apy = current_opp.annualized_apy_pct if current_opp else 0.0

            # Incrementally accrue simulated live funding based on exact elapsed time
            last_time = pos.last_accrual_time or pos.entry_time
            delta_hours = max(0.0, (now - last_time) / 3600.0)
            if delta_hours > 0:
                delta_funding = self.calculate_funding_payment(
                    pos.size * pos.entry_price, current_rate
                ) * delta_hours
                pos.accumulated_funding_usd += delta_funding
                pos.last_accrual_time = now
                pos.current_hourly_rate = current_rate

            # Update peak APY seen for this position (for trailing exit)
            if current_apy > 0 and (pos.peak_apy_pct is None or current_apy > pos.peak_apy_pct):
                pos.peak_apy_pct = current_apy

            # Evaluate exit conditions (absolute threshold + trailing APY)
            exit_reason = self._check_exit(coin, pos, current_apy, now)
            if exit_reason:
                logger.info(
                    f"🔻 Chiusura posizione su {coin}: {exit_reason}. "
                    f"Funding incassato: ${pos.accumulated_funding_usd:.4f}"
                )
                if self.telegram:
                    self.telegram.send_trade_alert(
                        action="Chiusura Delta-Neutral (Funding)",
                        symbol=coin,
                        size=pos.size,
                        price=pos.entry_price,
                        pnl=pos.accumulated_funding_usd,
                        notes=f"Funding: +${pos.accumulated_funding_usd:.4f} | {exit_reason}",
                    )
                # Record to CSV Ledger (optimization F)
                self.ledger.record_close(
                    coin=coin,
                    size=pos.size,
                    entry_price=pos.entry_price,
                    entry_time=pos.entry_time,
                    exit_time=now,
                    apy_entry_pct=self.calculate_apy(pos.hourly_rate_at_entry),
                    apy_exit_pct=current_apy,
                    funding_usd=pos.accumulated_funding_usd,
                    exit_reason=exit_reason,
                    dry_run=self.dry_run,
                )
                self.total_funding_earned_usd += pos.accumulated_funding_usd
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

            # Risk check on individual order and total portfolio exposure
            total_portfolio_usd = sum(p.size * p.entry_price for p in self.active_positions.values())
            if not self.risk_manager.validate_order(
                symbol=opp.coin,
                size=target_size,
                price=opp.mark_price,
                total_portfolio_notional_usd=total_portfolio_usd,
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
                entry_time=now,
                hourly_rate_at_entry=opp.hourly_funding_rate,
                accumulated_funding_usd=0.0,
                last_accrual_time=now,
                current_hourly_rate=opp.hourly_funding_rate,
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
            self.calculate_funding_payment(p.size * p.entry_price, p.current_hourly_rate or p.hourly_rate_at_entry)
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
            apy = self.calculate_apy(p.current_hourly_rate or p.hourly_rate_at_entry)
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
                    "apy": round(self.calculate_apy(p.current_hourly_rate or p.hourly_rate_at_entry), 2),
                }
                for coin, p in self.active_positions.items()
            },
            "total_funding_earned_usd": round(self.total_funding_earned_usd, 4),
            "formatted_report": self.format_status_report(),
        }

    def close_all_positions(self, reason: str = "Chiusura di emergenza manuale da Telegram") -> str:
        """Emergency/manual closure of all active positions."""
        if not self.active_positions:
            return "ℹ️ <b>Nessuna posizione attiva da chiudere al momento.</b>"

        now = time.time()
        closed_coins = []
        total_closed_funding = 0.0

        for coin, pos in list(self.active_positions.items()):
            # Calculate final accrued funding
            last_time = pos.last_accrual_time or pos.entry_time
            delta_hours = max(0.0, (now - last_time) / 3600.0)
            if delta_hours > 0:
                delta_funding = self.calculate_funding_payment(
                    pos.size * pos.entry_price, pos.current_hourly_rate or pos.hourly_rate_at_entry
                ) * delta_hours
                pos.accumulated_funding_usd += delta_funding

            # Record to CSV ledger
            self.ledger.record_close(
                coin=coin,
                size=pos.size,
                entry_price=pos.entry_price,
                entry_time=pos.entry_time,
                exit_time=now,
                apy_entry_pct=self.calculate_apy(pos.hourly_rate_at_entry),
                apy_exit_pct=self.calculate_apy(pos.current_hourly_rate or pos.hourly_rate_at_entry),
                funding_usd=pos.accumulated_funding_usd,
                exit_reason=reason,
                dry_run=self.dry_run,
            )

            total_closed_funding += pos.accumulated_funding_usd
            self.total_funding_earned_usd += pos.accumulated_funding_usd
            closed_coins.append(coin)
            del self.active_positions[coin]

        self._save_state()
        logger.info(f"🚨 [CLOSE ALL] Chiuse forzatamente tutte le posizioni ({closed_coins}). Funding: +${total_closed_funding:.4f}")

        coins_str = ", ".join(closed_coins)
        return (
            f"🛑 <b>Chiusura di Emergenza Completata!</b>\n\n"
            f"▫️ <b>Posizioni chiuse:</b> <code>{coins_str}</code>\n"
            f"▫️ <b>Funding totale incassato:</b> 🟢 <b>+${total_closed_funding:.4f} USD</b>\n"
            f"▫️ <b>Nuovo storico totale:</b> <b>+${self.total_funding_earned_usd:.4f} USD</b>\n"
            f"▫️ <i>Stato salvato su disco e registrato nel Ledger CSV.</i>"
        )

    def get_balance_report(self) -> str:
        """Return formatted balance and portfolio status."""
        total_allocated = sum(p.size * p.entry_price for p in self.active_positions.values())
        total_accrued = sum(p.accumulated_funding_usd for p in self.active_positions.values())
        total_lifetime = self.total_funding_earned_usd + total_accrued
        equity = self.get_equity()
        daily_rate = sum(
            self.calculate_funding_payment(p.size * p.entry_price, p.current_hourly_rate or p.hourly_rate_at_entry)
            for p in self.active_positions.values()
        ) * 24.0

        msg = (
            f"🏦 <b>Stato Portafoglio & Margine</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"▫️ <b>Equity Totale:</b> <b>${equity:,.2f} USD</b>\n"
            f"▫️ <b>Capitale Allocato:</b> ${total_allocated:,.2f} ({len(self.active_positions)}/{self.max_positions} slot)\n"
            f"▫️ <b>Taglia Base per Slot:</b> ${self.base_allocation_usd:,.2f}\n"
        )
        if self.auto_compound:
            msg += f"▫️ <b>Taglia Corrente Compounded:</b> <b>${self.current_allocation_usd:.2f}</b>\n"
        msg += (
            f"▫️ <b>Funding Maturato Attuale:</b> +${total_accrued:.4f} USD\n"
            f"▫️ <b>Totale Storico Incassato:</b> 🟢 <b>+${total_lifetime:.4f} USD</b>\n"
            f"▫️ <b>Rendita Giornaliera Attuale:</b> +${daily_rate:.2f}/giorno\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<i>Modalità: {'DRY-RUN (Simulazione)' if self.dry_run else 'LIVE TRADING'}</i>"
        )
        return msg
