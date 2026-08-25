"""Main Bot Engine & 24/7 Runtime Loop."""

import logging
from logging.handlers import RotatingFileHandler
import os
import signal
import sys
import time
from typing import Optional

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

        while self.is_running:
            loop_start = time.time()
            try:
                # Execute strategy tick
                self.strategy.on_tick()

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

    def stop(self) -> None:
        """Gracefully stop the bot engine and cleanup strategy."""
        if not self.is_running:
            return
        self.is_running = False
        self.logger.info("Arresto in corso: pulizia ordini e salvataggio stato...")
        try:
            self.strategy.on_stop()
            if self.telegram:
                self.telegram.send_shutdown(
                    strategy_name=self.strategy.name,
                    summary="Arresto manuale o segnale terminazione ricevuto.",
                )
        except Exception as e:
            self.logger.error(f"Errore durante lo stop della strategia: {e}")
        self.logger.info("✅ Bot arrestato con successo.")
