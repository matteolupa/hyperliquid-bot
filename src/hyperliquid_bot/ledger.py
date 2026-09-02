"""Funding Ledger — Registro storico delle posizioni chiuse per contabilità e analisi."""

import csv
import logging
import os
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("hyperliquid_bot.ledger")


class FundingLedger:
    """Appende ogni posizione chiusa su un file CSV per rendicontazione fiscale e analisi storica."""

    HEADERS = [
        "data_chiusura",
        "coin",
        "side",
        "size",
        "entry_price",
        "notional_usd",
        "entry_time_utc",
        "exit_time_utc",
        "duration_hours",
        "apy_entry_pct",
        "apy_exit_pct",
        "funding_usd",
        "exit_reason",
        "dry_run",
    ]

    def __init__(self, data_dir: str = "data", dry_run: bool = True):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        suffix = "dry" if dry_run else "live"
        self.filepath = os.path.join(data_dir, f"funding_ledger_{suffix}.csv")
        self._ensure_header()

    def _ensure_header(self) -> None:
        """Crea il file CSV con intestazioni se non esiste."""
        if not os.path.exists(self.filepath):
            try:
                with open(self.filepath, "w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=self.HEADERS)
                    writer.writeheader()
                logger.info(f"📒 Ledger contabile creato: {self.filepath}")
            except Exception as e:
                logger.error(f"Errore creazione ledger: {e}")

    def record_close(
        self,
        coin: str,
        size: float,
        entry_price: float,
        entry_time: float,
        exit_time: float,
        apy_entry_pct: float,
        apy_exit_pct: float,
        funding_usd: float,
        exit_reason: str,
        side: str = "SHORT",
        dry_run: bool = True,
    ) -> None:
        """Registra una posizione chiusa nel ledger CSV."""
        notional_usd = size * entry_price
        duration_hours = (exit_time - entry_time) / 3600.0
        entry_dt = datetime.fromtimestamp(entry_time, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        exit_dt = datetime.fromtimestamp(exit_time, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        date_str = datetime.fromtimestamp(exit_time, tz=timezone.utc).strftime("%Y-%m-%d")

        row = {
            "data_chiusura": date_str,
            "coin": coin,
            "side": side,
            "size": round(size, 6),
            "entry_price": round(entry_price, 6),
            "notional_usd": round(notional_usd, 2),
            "entry_time_utc": entry_dt,
            "exit_time_utc": exit_dt,
            "duration_hours": round(duration_hours, 3),
            "apy_entry_pct": round(apy_entry_pct, 4),
            "apy_exit_pct": round(apy_exit_pct, 4),
            "funding_usd": round(funding_usd, 6),
            "exit_reason": exit_reason,
            "dry_run": "yes" if dry_run else "no",
        }

        try:
            with open(self.filepath, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=self.HEADERS)
                writer.writerow(row)
            logger.info(
                f"📒 [LEDGER] {coin} ({side}) chiuso: +${funding_usd:.4f} USD | "
                f"{duration_hours:.1f}h | APY entrata: {apy_entry_pct:.2f}% | Motivo: {exit_reason}"
            )
        except Exception as e:
            logger.error(f"Errore scrittura ledger per {coin}: {e}")

    def get_recent_trades(self, limit: int = 5) -> list:
        """Legge le ultime N operazioni registrate nel CSV."""
        if not os.path.exists(self.filepath):
            return []
        try:
            with open(self.filepath, "r", newline="", encoding="utf-8") as f:
                reader = list(csv.DictReader(f))
                return reader[-limit:] if reader else []
        except Exception as e:
            logger.error(f"Errore lettura ledger: {e}")
            return []
