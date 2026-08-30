"""Main Bot Engine & 24/7 Runtime Loop."""

import logging
from logging.handlers import RotatingFileHandler
import os
import signal
import sys
import time
from typing import Any, Optional

from .client import HyperliquidClient
from .config import HyperliquidConfig
from .fees import FeeCalculator
from .risk import RiskManager
from .strategies.base import BaseStrategy


def setup_logger(log_dir: str = "logs", log_file: str = "bot.log") -> logging.Logger:
    """Set up structured logging for console and nohup background execution."""
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, log_file)

    logger = logging.getLogger("hyperliquid_bot")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    # Avoid duplicate handlers if setup_logger is called multiple times
    if not logger.handlers:
        formatter = logging.Formatter(
            "[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        # 1. Console handler (stdout)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

        # 2. Rotating file handler (max 10MB per file, 5 backups)
        file_handler = RotatingFileHandler(
            log_path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


class BotEngine:
    """Orchestrates 24/7 strategy execution, risk checks, and graceful shutdown."""

    def __init__(
        self,
        strategy: BaseStrategy,
        interval_seconds: float = 10.0,
        status_report_interval_seconds: float = 300.0,  # Status report every 5 minutes
        telegram: Optional[Any] = None,
    ):
        self.strategy = strategy
        self.interval_seconds = interval_seconds
        self.status_report_interval_seconds = status_report_interval_seconds
        self.telegram = telegram
        self.is_running = False
        self.logger = logging.getLogger("hyperliquid_bot.engine")

        # Register signal handlers for clean nohup termination
        signal.signal(signal.SIGINT, self._handle_shutdown_signal)
        signal.signal(signal.SIGTERM, self._handle_shutdown_signal)

    def _handle_shutdown_signal(self, signum: int, frame) -> None:
        """Handle SIGINT and SIGTERM for graceful shutdown."""
        sig_name = "SIGTERM" if signum == signal.SIGTERM else "SIGINT"
        self.logger.warning(f"⚠️ Segnale di arresto {sig_name} ricevuto! Avvio Graceful Shutdown...")
        self.stop()

    def start(self) -> None:
        """Start the continuous 24/7 bot loop."""
        self.is_running = True
        mode_str = "DRY-RUN (Simulazione)" if self.strategy.dry_run else "LIVE TRADING"
        self.logger.info("=" * 65)
        self.logger.info("🤖 HYPERLIQUID 24/7 BOT ENGINE AVVIATO")
        self.logger.info(f"   PID: {os.getpid()} | Strategia: {self.strategy.name} | Intervallo: {self.interval_seconds}s")
        self.logger.info("=" * 65)

        if self.telegram:
            self.telegram.register_command("/status", self._cmd_status)
            self.telegram.register_command("/balance", self._cmd_balance)
            self.telegram.register_command("/closeall", self._cmd_closeall)
            self.telegram.start_polling()
            self.telegram.send_startup(
                strategy_name=self.strategy.name,
                mode=mode_str,
                details=f"Intervallo tick: {self.interval_seconds}s | Report ogni: {int(self.status_report_interval_seconds/60)}m",
            )

        try:
            self.strategy.on_start()
        except Exception as e:
            self.logger.critical(f"Errore fatale all'avvio della strategia: {e}", exc_info=True)
            self.stop()
            return

        last_status_time = time.time()
        self.current_day_str = time.strftime("%Y-%m-%d")
        initial_status = self.strategy.get_status()
        self.day_start_earnings_usd = initial_status.get(
            "total_lifetime_earnings_usd", initial_status.get("total_funding_earned_usd", 0.0)
        )

        while self.is_running:
            loop_start = time.time()
            try:
                # Execute strategy tick
                self.strategy.on_tick()

                # Check Risk Manager Equity and Drawdown Circuit Breaker
                equity = None
                if hasattr(self.strategy, "get_equity"):
                    equity = self.strategy.get_equity()
                if equity is not None and getattr(self.strategy, "risk_manager", None):
                    if self.strategy.risk_manager.update_equity(equity):
                        reason = self.strategy.risk_manager.circuit_breaker_reason or "Max Drawdown Superato"
                        self.logger.critical(f"🚨 [CIRCUIT BREAKER ATTIVATO] {reason}")
                        if self.telegram:
                            self.telegram.send_trade_alert(
                                action="🚨 CIRCUIT BREAKER ATTIVATO",
                                symbol="PORTFOLIO",
                                size=0.0,
                                price=0.0,
                                pnl=None,
                                notes=reason,
                            )
                        self.stop()
                        break

                # Periodic health / status report
                if time.time() - last_status_time >= self.status_report_interval_seconds:
                    status = self.strategy.get_status()
                    if "formatted_report" in status:
                        self.logger.info(status["formatted_report"])
                        if self.telegram:
                            self.telegram.send_status_report(status["formatted_report"])
                    else:
                        self.logger.info(f"📋 [STATUS REPORT] {status}")
                    last_status_time = time.time()

                # Check for Midnight Day Transition for Daily Telegram Summary
                today_str = time.strftime("%Y-%m-%d")
                if today_str != self.current_day_str:
                    status = self.strategy.get_status()
                    current_lifetime = status.get(
                        "total_lifetime_earnings_usd", status.get("total_funding_earned_usd", 0.0)
                    )
                    daily_earnings = current_lifetime - self.day_start_earnings_usd
                    capital = status.get("capital_allocated_usd", 0.0)
                    daily_roi = (daily_earnings / capital * 100.0) if capital > 0 else 0.0
                    compounded_boost = status.get("compounded_boost_usd", 0.0)

                    # Build positions summary
                    active_pos = status.get("active_positions", {})
                    pos_lines = []
                    for coin, p_info in active_pos.items():
                        pos_lines.append(f"  • {coin}: APY {p_info.get('apy', 0.0)}% | PnL +${p_info.get('estimated_funding_usd', 0.0):.4f}")
                    pos_summary_str = "\n".join(pos_lines) if pos_lines else "Nessuna posizione attiva."

                    self.logger.info(
                        f"🌙 [REPORT GIORNALIERO {self.current_day_str}] Guadagno 24h: +${daily_earnings:.4f} USD | "
                        f"ROI: +{daily_roi:.2f}% | Capitale: ${capital:,.2f}"
                    )

                    if self.telegram:
                        self.telegram.send_daily_summary(
                            date_str=self.current_day_str,
                            daily_earnings_usd=daily_earnings,
                            total_lifetime_earnings_usd=current_lifetime,
                            capital_allocated_usd=capital,
                            daily_roi_pct=daily_roi,
                            compounded_boost_usd=compounded_boost,
                            positions_summary=pos_summary_str,
                        )

                    # Reset day tracker for the new day
                    self.current_day_str = today_str
                    self.day_start_earnings_usd = current_lifetime

            except KeyboardInterrupt:
                self.logger.info("Interruzione da tastiera.")
                break
            except Exception as e:
                self.logger.error(f"Errore nel ciclo di esecuzione: {e}. Ripristino al prossimo tick...", exc_info=True)

            # Sleep remaining interval time
            elapsed = time.time() - loop_start
            sleep_time = max(0.1, self.interval_seconds - elapsed)
            time.sleep(sleep_time)

        self.logger.info("Bot Engine loop terminato.")

    def _cmd_status(self) -> str:
        """Handle /status command from Telegram."""
        status = self.strategy.get_status()
        if "formatted_report" in status:
            return f"<pre>{status['formatted_report'].strip()}</pre>"
        return f"<pre>{str(status)}</pre>"

    def _cmd_balance(self) -> str:
        """Handle /balance command from Telegram."""
        if hasattr(self.strategy, "get_balance_report"):
            return self.strategy.get_balance_report()
        equity = self.strategy.get_equity() or 0.0
        return f"🏦 <b>Stato Saldo:</b>\n▫️ <b>Equity Totale:</b> ${equity:,.2f} USD"

    def _cmd_closeall(self) -> str:
        """Handle /closeall command from Telegram."""
        if hasattr(self.strategy, "close_all_positions"):
            return self.strategy.close_all_positions(reason="Chiusura manuale da comando Telegram /closeall")
        return "ℹ️ <b>Nessuna posizione attiva da chiudere.</b>"

    def stop(self) -> None:
        """Gracefully stop the bot engine and cleanup strategy."""
        if not self.is_running:
            return
        self.is_running = False
        self.logger.info("Arresto in corso: pulizia ordini e salvataggio stato...")
        try:
            if self.telegram:
                self.telegram.stop_polling()
            self.strategy.on_stop()
            if self.telegram:
                self.telegram.send_shutdown(
                    strategy_name=self.strategy.name,
                    summary="Arresto manuale o segnale terminazione ricevuto.",
                )
        except Exception as e:
            self.logger.error(f"Errore durante lo stop della strategia: {e}")
        self.logger.info("✅ Bot arrestato con successo.")
