"""Single-Asset Scalper / Take-Profit Strategy.

Buys a fixed USD amount (e.g. $50) on a target crypto, calculates the fee-adjusted
Take-Profit target (Break-even + net profit target %), and waits to sell for profit.
"""

from dataclasses import dataclass
import logging
import time
from typing import Any, Dict, Optional

from .base import BaseStrategy
from ..client import HyperliquidClient
from ..fees import FeeCalculator
from ..persistence import StatePersistenceManager
from ..risk import RiskManager

logger = logging.getLogger("hyperliquid_bot.strategy.scalper")


@dataclass
class ScalperTrade:
    symbol: str
    size: float
    entry_price: float
    entry_time: float
    breakeven_price: float
    take_profit_price: float
    stop_loss_price: Optional[float]
    entry_fee_usd: float
    target_net_profit_usd: float


class ScalperStrategy(BaseStrategy):
    """Scalping bot that opens a fixed-size trade and exits at fee-aware Take Profit."""

    def __init__(
        self,
        client: HyperliquidClient,
        symbol: str = "ETH",
        order_size_usd: float = 50.0,
        profit_target_pct: float = 0.8,  # +0.8% net profit target above breakeven
        stop_loss_pct: Optional[float] = 2.0,  # Optional 2.0% stop loss
        risk_manager: Optional[RiskManager] = None,
        fee_calculator: Optional[FeeCalculator] = None,
        dry_run: bool = True,
        telegram: Optional[Any] = None,
        dip_buy_pct: float = 0.2,  # Buy on 0.2% dip or immediate if no position
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
        self.profit_target_pct = profit_target_pct
        self.stop_loss_pct = stop_loss_pct
        self.dip_buy_pct = dip_buy_pct

        # Active trade state
        self.active_trade: Optional[ScalperTrade] = None
        self.total_realized_profit_usd: float = 0.0
        self.total_completed_trades: int = 0
        self.reference_price: Optional[float] = None
        self.persistence = StatePersistenceManager(
            filename=f"scalper_state_{self.symbol}_{'dry' if self.dry_run else 'live'}.json"
        )

    def _save_state(self) -> None:
        """Save trade state to disk."""
        data = {
            "total_realized_profit_usd": self.total_realized_profit_usd,
            "total_completed_trades": self.total_completed_trades,
            "active_trade": (
                {
                    "symbol": self.active_trade.symbol,
                    "size": self.active_trade.size,
                    "entry_price": self.active_trade.entry_price,
                    "entry_time": self.active_trade.entry_time,
                    "breakeven_price": self.active_trade.breakeven_price,
                    "take_profit_price": self.active_trade.take_profit_price,
                    "stop_loss_price": self.active_trade.stop_loss_price,
                    "entry_fee_usd": self.active_trade.entry_fee_usd,
                    "target_net_profit_usd": self.active_trade.target_net_profit_usd,
                }
                if self.active_trade
                else None
            ),
        }
        self.persistence.save_state(data)

    def _restore_state(self) -> None:
        """Restore trade state from disk."""
        state = self.persistence.load_state()
        if not state:
            return

        self.total_realized_profit_usd = state.get("total_realized_profit_usd", 0.0)
        self.total_completed_trades = state.get("total_completed_trades", 0)
        t_data = state.get("active_trade")
        if t_data:
            self.active_trade = ScalperTrade(
                symbol=t_data["symbol"],
                size=t_data["size"],
                entry_price=t_data["entry_price"],
                entry_time=t_data["entry_time"],
                breakeven_price=t_data["breakeven_price"],
                take_profit_price=t_data["take_profit_price"],
                stop_loss_price=t_data.get("stop_loss_price"),
                entry_fee_usd=t_data["entry_fee_usd"],
                target_net_profit_usd=t_data["target_net_profit_usd"],
            )
            logger.info(
                f"🔄 Ripristinato trade aperto su {self.symbol}: {self.active_trade.size:.4f} units @ ${self.active_trade.entry_price:,.2f}"
            )

    def on_start(self) -> None:
        self.is_running = True
        self._restore_state()
        mode_str = "DRY-RUN (Simulazione)" if self.dry_run else "LIVE TRADING"
        logger.info(f"🚀 [{self.name}] Avviato su {self.symbol} in modalità: {mode_str}")
        logger.info(
            f"   Size Ordine: ${self.order_size_usd:.2f} | "
            f"Target Profitto Netto: +{self.profit_target_pct:.2f}% | "
            f"Stop Loss: -{self.stop_loss_pct if self.stop_loss_pct else 'Disattivato'}%"
        )

    def on_tick(self) -> None:
        if not self.is_running:
            return

        try:
            mids = self.client.get_all_mids()
            current_price_str = mids.get(self.symbol)
            if not current_price_str:
                logger.warning(f"Prezzo non disponibile per {self.symbol}.")
                return

            current_price = float(current_price_str)

            # SCENARIO A: Abbiamo una posizione aperta -> Controlliamo Take-Profit o Stop-Loss
            if self.active_trade is not None:
                trade = self.active_trade
                pnl_gross = (current_price - trade.entry_price) * trade.size
                price_change_pct = ((current_price - trade.entry_price) / trade.entry_price) * 100.0

                # 1. Check Take Profit Fill
                if current_price >= trade.take_profit_price:
                    # Calcolo fee di uscita per determinare il profitto netto esatto
                    exit_fee = self.fee_calculator.calculate_trade_fee(
                        size=trade.size,
                        price=current_price,
                        is_maker=True,  # Limit order TP
                    )
                    net_profit = pnl_gross - trade.entry_fee_usd - exit_fee.total_fee_usd
                    self.total_realized_profit_usd += net_profit
                    self.total_completed_trades += 1

                    logger.info(
                        f"🎯 [TAKE PROFIT RAGGIUNTO su {self.symbol}!] "
                        f"Vendita eseguita @ ${current_price:,.2f} | "
                        f"Profitto Netto: +${net_profit:.4f} (+{price_change_pct:.2f}%) | "
                        f"Profitti Totali: ${self.total_realized_profit_usd:.4f}"
                    )
                    if self.telegram:
                        self.telegram.send_trade_alert(
                            action="TAKE PROFIT",
                            symbol=self.symbol,
                            size=trade.size,
                            price=current_price,
                            pnl=net_profit,
                            notes=f"Profitto Netto: +${net_profit:.4f} (+{price_change_pct:.2f}%) | Totale: ${self.total_realized_profit_usd:.4f}",
                        )
                    self.active_trade = None
                    self.reference_price = current_price
                    self._save_state()
                    return

                # 2. Check Stop Loss (se attivo)
                if trade.stop_loss_price and current_price <= trade.stop_loss_price:
                    exit_fee = self.fee_calculator.calculate_trade_fee(
                        size=trade.size, price=current_price, is_maker=False
                    )
                    net_loss = pnl_gross - trade.entry_fee_usd - exit_fee.total_fee_usd
                    self.total_realized_profit_usd += net_loss
                    self.total_completed_trades += 1

                    logger.warning(
                        f"🛑 [STOP LOSS SCATTATO su {self.symbol}] "
                        f"Vendita @ ${current_price:,.2f} | "
                        f"Perdita: ${net_loss:.4f} ({price_change_pct:.2f}%)"
                    )
                    if self.telegram:
                        self.telegram.send_trade_alert(
                            action="STOP LOSS",
                            symbol=self.symbol,
                            size=trade.size,
                            price=current_price,
                            pnl=net_loss,
                            notes=f"Perdita: ${net_loss:.4f} ({price_change_pct:.2f}%)",
                        )
                    self.active_trade = None
                    self.reference_price = current_price
                    self._save_state()
                    return

                # Posizione in corso: log periodico
                logger.info(
                    f"⏳ [{self.symbol}] Prezzo: ${current_price:,.2f} | "
                    f"Entry: ${trade.entry_price:,.2f} | "
                    f"Target TP: ${trade.take_profit_price:,.2f} (Mancano ${trade.take_profit_price - current_price:.2f}) | "
                    f"PnL Corrente: ${pnl_gross:+.4f} ({price_change_pct:+.2f}%)"
                )

            # SCENARIO B: Nessuna posizione aperta -> Cerchiamo l'ingresso
            else:
                if self.reference_price is None:
                    self.reference_price = current_price

                # Entrata immediata se appena avviato o se ha fatto un micro-ritracciamento
                size = round(self.order_size_usd / current_price, 4)
                notional = size * current_price

                # Validazione del rischio
                if not self.risk_manager.validate_order(
                    symbol=self.symbol,
                    size=size,
                    price=current_price,
                ):
                    return

                # Calcolo Break-Even esatto + Target Profitto
                breakeven = self.fee_calculator.calculate_breakeven_price(
                    entry_price=current_price,
                    is_long=True,
                    entry_is_maker=False,  # Entry a mercato/taker
                    exit_is_maker=True,   # Uscita a limite/maker
                )
                entry_fee_info = self.fee_calculator.calculate_trade_fee(
                    size=size, price=current_price, is_maker=False
                )

                # Prezzo di Take Profit = Breakeven + margine netto desiderato
                take_profit_price = round(breakeven * (1.0 + (self.profit_target_pct / 100.0)), 2)
                
                stop_loss_price = None
                if self.stop_loss_pct:
                    stop_loss_price = round(current_price * (1.0 - (self.stop_loss_pct / 100.0)), 2)

                target_net_profit = (take_profit_price - current_price) * size - entry_fee_info.total_fee_usd

                if self.dry_run:
                    logger.info(
                        f"🛒 [DRY-RUN ACQUISTO] {self.symbol}: {size:.4f} units a ${current_price:,.2f} (${notional:.2f})"
                    )
                else:
                    logger.info(
                        f"🛒 [LIVE ACQUISTO] {self.symbol}: {size:.4f} units a ${current_price:,.2f} (${notional:.2f})"
                    )

                logger.info(
                    f"   📌 Break-Even Fee: ${breakeven:,.2f} | "
                    f"🎯 Ordine Take-Profit impostato a: ${take_profit_price:,.2f} (+{self.profit_target_pct}%) | "
                    f"Profitto netto atteso: +${target_net_profit:.4f}"
                )

                if self.telegram:
                    self.telegram.send_trade_alert(
                        action="ACQUISTO (Entry)",
                        symbol=self.symbol,
                        size=size,
                        price=current_price,
                        notes=f"🎯 TP Target: ${take_profit_price:,.2f} (+{self.profit_target_pct}%) | Netto atteso: +${target_net_profit:.4f}",
                    )

                self.active_trade = ScalperTrade(
                    symbol=self.symbol,
                    size=size,
                    entry_price=current_price,
                    entry_time=time.time(),
                    breakeven_price=breakeven,
                    take_profit_price=take_profit_price,
                    stop_loss_price=stop_loss_price,
                    entry_fee_usd=entry_fee_info.total_fee_usd,
                    target_net_profit_usd=target_net_profit,
                )

            # Persist state
            self._save_state()

        except Exception as e:
            logger.error(f"Errore durante tick di scalper su {self.symbol}: {e}", exc_info=True)

    def on_stop(self) -> None:
        self.is_running = False
        self._save_state()
        logger.info(
            f"🛑 [{self.name}] Fermato su {self.symbol}. "
            f"Profitto Netto Realizzato: ${self.total_realized_profit_usd:.4f} | "
            f"Trade Completati: {self.total_completed_trades}"
        )

    def format_status_report(self) -> str:
        """Format human-readable scalper trade report."""
        lines = [
            "\n" + "=" * 65,
            f"📊 [RESOCONTO SCALPER BOT ({self.symbol})]",
            f"   Trade Completati:         {self.total_completed_trades}",
            f"   Profitto Netto Realizzato: +${self.total_realized_profit_usd:.4f} USD",
        ]
        if self.active_trade:
            t = self.active_trade
            pnl_est = (self.reference_price - t.entry_price) * t.size if self.reference_price else 0.0
            lines.append(f"   Posizione Attiva:         {t.size:.4f} {t.symbol} @ ${t.entry_price:,.2f}")
            lines.append(f"   Target Take-Profit:       ${t.take_profit_price:,.2f} (Atteso: +${t.target_net_profit_usd:.4f})")
            lines.append(f"   PnL Flottante:            ${pnl_est:+.4f}")
        else:
            lines.append("   Stato:                    In attesa di nuovo ordine di acquisto")
        lines.append("=" * 65)
        return "\n".join(lines)

    def get_status(self) -> Dict[str, Any]:
        return {
            "strategy": self.name,
            "symbol": self.symbol,
            "dry_run": self.dry_run,
            "has_active_trade": self.active_trade is not None,
            "formatted_report": self.format_status_report(),
            "active_trade": (
                {
                    "size": self.active_trade.size,
                    "entry_price": self.active_trade.entry_price,
                    "take_profit_price": self.active_trade.take_profit_price,
                    "target_net_profit_usd": round(self.active_trade.target_net_profit_usd, 4),
                }
                if self.active_trade
                else None
            ),
            "total_realized_profit_usd": round(self.total_realized_profit_usd, 4),
            "total_completed_trades": self.total_completed_trades,
        }
