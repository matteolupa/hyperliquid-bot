"""Performance Tracker & Equity Curve Logger.

Tracks hourly portfolio snapshots, records equity curves to CSV,
and calculates rolling 24-hour and 7-day performance statistics.
"""

import csv
import logging
import os
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("hyperliquid_bot.performance")

HEADERS = [
    "timestamp",
    "datetime_utc",
    "equity",
    "capital_allocated",
    "total_funding_earned",
    "active_positions_count",
    "hourly_earnings_usd",
    "realized_apy_pct",
]


class PerformanceTracker:
    """Logs equity curve snapshots and aggregates historical performance metrics."""

    def __init__(self, data_dir: str = "data", dry_run: bool = True):
        self.data_dir = data_dir
        self.dry_run = dry_run
        mode_str = "dry" if dry_run else "live"
        self.filename = f"equity_curve_{mode_str}.csv"
        self.filepath = os.path.join(self.data_dir, self.filename)
        self._ensure_file()

    def _ensure_file(self) -> None:
        """Ensure data directory and CSV file with header exist."""
        os.makedirs(self.data_dir, exist_ok=True)
        if not os.path.exists(self.filepath):
            with open(self.filepath, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(HEADERS)

    def record_snapshot(
        self,
        equity: float,
        capital_allocated: float,
        total_funding_earned: float,
        active_positions_count: int,
        hourly_earnings_usd: float,
        realized_apy_pct: float,
        timestamp: Optional[float] = None,
    ) -> None:
        """Append an hourly snapshot row to the equity curve CSV."""
        t = timestamp or time.time()
        dt_str = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(t))
        row = [
            f"{t:.2f}",
            dt_str,
            f"{equity:.4f}",
            f"{capital_allocated:.4f}",
            f"{total_funding_earned:.4f}",
            str(active_positions_count),
            f"{hourly_earnings_usd:.6f}",
            f"{realized_apy_pct:.2f}",
        ]
        try:
            with open(self.filepath, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(row)
        except Exception as e:
            logger.error(f"Errore scrittura snapshot equity curve su {self.filepath}: {e}")

    def get_history(self, max_hours: int = 168) -> List[Dict[str, Any]]:
        """Read the most recent snapshots up to max_hours (168 = 7 days)."""
        if not os.path.exists(self.filepath):
            return []
        rows = []
        try:
            with open(self.filepath, "r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for r in reader:
                    rows.append(r)
        except Exception as e:
            logger.error(f"Errore lettura {self.filepath}: {e}")
            return []
        return rows[-max_hours:]

    def get_stats(self) -> Dict[str, Any]:
        """Compute rolling 24h and 7d aggregated performance statistics."""
        history = self.get_history(max_hours=168)
        now = time.time()
        one_day_ago = now - 86400
        seven_days_ago = now - (7 * 86400)

        def _safe_float(v, default=0.0):
            try:
                return float(v)
            except (ValueError, TypeError):
                return default

        rows_24h = [r for r in history if _safe_float(r.get("timestamp")) >= one_day_ago]
        rows_7d = [r for r in history if _safe_float(r.get("timestamp")) >= seven_days_ago]

        # 24h stats
        earnings_24h = sum(_safe_float(r.get("hourly_earnings_usd")) for r in rows_24h)
        payments_24h = len([r for r in rows_24h if _safe_float(r.get("hourly_earnings_usd")) > 0])
        avg_hourly_24h = (earnings_24h / len(rows_24h)) if rows_24h else 0.0

        # 7d stats
        earnings_7d = sum(_safe_float(r.get("hourly_earnings_usd")) for r in rows_7d)
        payments_7d = len([r for r in rows_7d if _safe_float(r.get("hourly_earnings_usd")) > 0])
        avg_hourly_7d = (earnings_7d / len(rows_7d)) if rows_7d else 0.0

        latest = history[-1] if history else {}
        equity = _safe_float(latest.get("equity"))
        capital = _safe_float(latest.get("capital_allocated"))
        roi_24h = (earnings_24h / capital * 100.0) if capital > 0 else 0.0
        roi_7d = (earnings_7d / capital * 100.0) if capital > 0 else 0.0

        return {
            "earnings_24h_usd": earnings_24h,
            "roi_24h_pct": roi_24h,
            "payments_count_24h": payments_24h,
            "avg_hourly_24h_usd": avg_hourly_24h,
            "earnings_7d_usd": earnings_7d,
            "roi_7d_pct": roi_7d,
            "payments_count_7d": payments_7d,
            "avg_hourly_7d_usd": avg_hourly_7d,
            "total_snapshots": len(history),
            "current_equity_usd": equity,
        }

    def format_stats_report(
        self,
        strategy_status: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Generate a formatted Telegram HTML report for the /stats command."""
        stats = self.get_stats()
        status = strategy_status or {}

        lifetime_earned = status.get(
            "total_lifetime_earnings_usd",
            status.get("total_funding_earned_usd", 0.0)
        )
        capital = status.get("capital_allocated_usd", 0.0)
        active_count = len(status.get("active_positions", {}))
        accrued = status.get("total_accrued_funding_usd", 0.0)
        hourly_yield = status.get("hourly_yield_usd", 0.0)
        daily_yield = status.get("daily_yield_usd", 0.0)

        # Realized APY based on 24h run-rate
        projected_apy_24h = (stats["roi_24h_pct"] * 365.0) if stats["roi_24h_pct"] > 0 else 0.0

        now = time.time()
        sec_to_next = 3600 - int(now % 3600)
        mins_to_next = sec_to_next // 60

        lines = [
            "📈 <b>Performance & Rendimenti Funding Arbitrage</b>",
            "━━━━━━━━━━━━━━━━━━━━━━",
            f"🏦 <b>Capitale Allocato:</b> <code>${capital:,.2f}</code> ({active_count} posizioni)",
            f"🏆 <b>Totale Storico Incassato:</b> <b>+${lifetime_earned:,.4f} USD</b>",
        ]
        if active_count > 0:
            lines.append(f"⚡ <b>Rendita Stimata Live:</b> +${hourly_yield:.4f}/h (+${daily_yield:.2f}/giorno)")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━")

        if stats["total_snapshots"] < 24:
            lines.append(f"⏱️ <b>Ultime 24 Ore:</b> <i>({stats['total_snapshots']}/24 snapshot orari raccolti)</i>")
        else:
            lines.append("⏱️ <b>Ultime 24 Ore:</b>")

        if stats["total_snapshots"] == 0:
            lines.append(f"  • Status: <i>In accumulo (1° rollover :00 UTC tra ~{mins_to_next}m)</i>")
            lines.append(f"  • Funding Maturato Attivo: 🟢 <b>+${accrued:.4f} USD</b>")
            run_rate_roi = (daily_yield / capital * 100.0) if capital > 0 else 0.0
            run_rate_apy = run_rate_roi * 365.0
            lines.append(f"  • Proiezione 24h Live: <b>+${daily_yield:.2f} USD</b> (~{run_rate_apy:.1f}% APY)")
        else:
            lines.append(f"  • Guadagno Netto: 🟢 <b>+${stats['earnings_24h_usd']:.4f} USD</b>")
            lines.append(f"  • ROI 24h: <b>+{stats['roi_24h_pct']:.2f}%</b> (Proiez. APY: {projected_apy_24h:.1f}%)")
            lines.append(f"  • Pagamenti Orari Incassati: <b>{stats['payments_count_24h']}</b>")
            lines.append(f"  • Rendita Oraria Media: +${stats['avg_hourly_24h_usd']:.4f}/h")

        lines.append("━━━━━━━━━━━━━━━━━━━━━━")

        if stats["total_snapshots"] < 168:
            days_collected = round(stats["total_snapshots"] / 24.0, 1)
            lines.append(f"📅 <b>Ultimi 7 Giorni:</b> <i>({days_collected}/7 giorni registrati)</i>")
        else:
            lines.append("📅 <b>Ultimi 7 Giorni:</b>")

        if stats["total_snapshots"] == 0:
            lines.append(f"  • Status: <i>In accumulo progressivo su {self.filename}</i>")
            lines.append(f"  • Proiezione 7d Live: <b>+${daily_yield * 7.0:.2f} USD</b>")
        else:
            lines.append(f"  • Guadagno Complessivo: 🟢 <b>+${stats['earnings_7d_usd']:.4f} USD</b>")
            lines.append(f"  • ROI 7d: <b>+{stats['roi_7d_pct']:.2f}%</b>")
            lines.append(f"  • Accrediti Totali: <b>{stats['payments_count_7d']}</b>")
            avg_daily = (stats["earnings_7d_usd"] / (max(1, stats["total_snapshots"]) / 24.0)) if stats["earnings_7d_usd"] > 0 else 0.0
            lines.append(f"  • Rendita Giornaliera Media: +${avg_daily:.2f}/giorno")

        lines.append("━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"ℹ️ <i>Snapshot orario automatico ad ogni :00 UTC su {self.filename}</i>")
        return "\n".join(lines)
