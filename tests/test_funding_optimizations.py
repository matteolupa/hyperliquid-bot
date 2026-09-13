"""Unit tests for the Funding Arbitrage Optimizations:
1. Dynamic Yield-Weighted Sizing
2. Hourly Rollover & Push Notification
3. Countdown & Estimated Payment
4. Performance Tracker & Equity Curve (24h/7d metrics, /stats)
5. Perp Liquidation Buffer & Margin Health
"""

import os
import shutil
import tempfile
import time
import unittest
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

from hyperliquid_bot.performance import PerformanceTracker
from hyperliquid_bot.strategies.funding_harvester import (
    ActiveFundingPosition,
    FundingHarvesterStrategy,
    FundingOpportunity,
)
from hyperliquid_bot.engine import BotEngine


class TestFundingOptimizations(unittest.TestCase):
    """Test suite covering dynamic sizing, hourly settlement alerts, performance tracking, and liquidation buffers."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_dynamic_yield_weighted_sizing(self):
        """Verify that capital is dynamically weighted according to asset yield/ranking."""
        class DummyClient:
            info = MagicMock()

        strategy = FundingHarvesterStrategy(
            client=DummyClient(),
            allocation_per_position_usd=100.0,
            max_positions=3,
            min_entry_apy_pct=5.0,  # Ensure all 3 test opps are eligible
            dynamic_sizing=True,
            enable_trend_detection=False,
            enable_cross_exchange=False,
            enable_basis_monitor=False,
        )

        opp_aztec = FundingOpportunity(
            coin="AZTEC", mark_price=0.014, hourly_funding_rate=0.0002,
            annualized_apy_pct=17.5, open_interest_usd=500_000.0,
        )
        opp_hype = FundingOpportunity(
            coin="HYPE", mark_price=79.0, hourly_funding_rate=0.00012,
            annualized_apy_pct=10.9, open_interest_usd=1_000_000.0,
        )
        opp_mon = FundingOpportunity(
            coin="MON", mark_price=0.02, hourly_funding_rate=0.00012,
            annualized_apy_pct=10.9, open_interest_usd=500_000.0,
        )
        opps = [opp_aztec, opp_hype, opp_mon]

        # Total capital = $100 * 3 = $300
        alloc_aztec = strategy.get_allocation_for_opportunity(opp_aztec, opps)
        alloc_hype = strategy.get_allocation_for_opportunity(opp_hype, opps)
        alloc_mon = strategy.get_allocation_for_opportunity(opp_mon, opps)

        # Rank 0 gets 45% ($135.00), Rank 1 gets 33% ($99.00), Rank 2 gets 22% ($66.00)
        self.assertEqual(alloc_aztec, 135.00)
        self.assertEqual(alloc_hype, 99.00)
        self.assertEqual(alloc_mon, 66.00)
        self.assertAlmostEqual(alloc_aztec + alloc_hype + alloc_mon, 300.00)

        # Test fallback when dynamic_sizing is False
        strategy.dynamic_sizing = False
        self.assertEqual(strategy.get_allocation_for_opportunity(opp_aztec, opps), 100.00)
        self.assertEqual(strategy.get_allocation_for_opportunity(opp_mon, opps), 100.00)

    def test_hourly_rollover_and_push_notification(self):
        """Verify that crossing an hour boundary triggers hourly snapshot recording and Telegram alert."""
        class MockClient:
            class Info:
                def meta_and_asset_ctxs(self):
                    return ({"universe": []}, [])
            info = Info()

        mock_tg = MagicMock()
        strategy = FundingHarvesterStrategy(
            client=MockClient(),
            telegram=mock_tg,
            dry_run=True,
            enable_hourly_alerts=True,
            enable_trend_detection=False,
            enable_cross_exchange=False,
            enable_basis_monitor=False,
        )
        strategy.performance_tracker = PerformanceTracker(data_dir=self.temp_dir, dry_run=True)
        strategy.on_start()

        # Populate active positions
        now = time.time()
        strategy.active_positions = {
            "AZTEC": ActiveFundingPosition(
                coin="AZTEC", size=10000.0, entry_price=0.014, entry_time=now - 3600,
                hourly_rate_at_entry=0.0002, side="SHORT", hedge_mode="spot-perp",
            ),
            "PURR": ActiveFundingPosition(
                coin="PURR", size=1000.0, entry_price=0.11, entry_time=now - 3600,
                hourly_rate_at_entry=0.0001, side="SHORT", hedge_mode="spot-perp",
            ),
        }

        # Force last settlement hour to 1 hour in the past
        strategy.last_settlement_hour = int(now // 3600) - 1

        # Run tick
        strategy.on_tick()

        # Verify settlement hour updated to current hour
        self.assertEqual(strategy.last_settlement_hour, int(now // 3600))

        # Verify Telegram alert was triggered with expected content
        mock_tg.send_message.assert_called_once()
        msg = mock_tg.send_message.call_args[0][0]
        self.assertIn("Accredito Funding Orario", msg)
        self.assertIn("AZTEC", msg)
        self.assertIn("PURR", msg)
        self.assertIn("Incasso Ultima Ora:", msg)

        # Verify performance snapshot was appended to CSV
        history = strategy.performance_tracker.get_history()
        self.assertEqual(len(history), 1)
        self.assertGreater(float(history[0]["hourly_earnings_usd"]), 0.0)

    def test_countdown_and_liquidation_buffer_in_report(self):
        """Verify countdown to next funding and liquidation buffer display in status report."""
        class DummyClient:
            info = MagicMock()

        strategy = FundingHarvesterStrategy(
            client=DummyClient(),
            dry_run=True,
            enable_trend_detection=False,
            enable_cross_exchange=False,
            enable_basis_monitor=False,
        )
        strategy.active_positions = {
            "HYPE": ActiveFundingPosition(
                coin="HYPE", size=2.0, entry_price=79.0, entry_time=time.time(),
                hourly_rate_at_entry=0.000125, side="SHORT", hedge_mode="spot-perp",
            )
        }

        report = strategy.format_status_report()
        self.assertIn("Prossimo Accredito:", report)
        self.assertIn("tra ", report)
        self.assertIn("Buffer Liquidazione:", report)
        self.assertIn("HYPE +", report)

    def test_performance_tracker_stats_and_formatting(self):
        """Verify 24h/7d metrics aggregation and /stats report generation."""
        tracker = PerformanceTracker(data_dir=self.temp_dir, dry_run=True)

        now = time.time()
        # Record 4 snapshots in the last 4 hours
        for i in range(4):
            tracker.record_snapshot(
                equity=500.0 + i * 0.1,
                capital_allocated=500.0,
                total_funding_earned=10.0 + i * 0.1,
                active_positions_count=3,
                hourly_earnings_usd=0.05,
                realized_apy_pct=8.76,
                timestamp=now - (3 - i) * 3600,
            )

        stats = tracker.get_stats()
        self.assertAlmostEqual(stats["earnings_24h_usd"], 0.20, places=3)
        self.assertEqual(stats["payments_count_24h"], 4)
        self.assertAlmostEqual(stats["avg_hourly_24h_usd"], 0.05, places=3)
        self.assertGreater(stats["roi_24h_pct"], 0.0)

        # Test Telegram /stats report format
        report = tracker.format_stats_report({
            "capital_allocated_usd": 500.0,
            "total_lifetime_earnings_usd": 10.3,
            "active_positions": {"A": {}, "B": {}, "C": {}},
        })
        self.assertIn("Performance & Rendimenti Funding Arbitrage", report)
        self.assertIn("Ultime 24 Ore:", report)
        self.assertIn("Ultimi 7 Giorni:", report)
        self.assertIn("+$0.2000 USD", report)

    def test_engine_stats_command_registration(self):
        """Verify /stats command registration and execution in BotEngine."""
        mock_strategy = MagicMock()
        mock_strategy.name = "TestFunding"
        mock_strategy.get_stats_report.return_value = "<b>Test Stats Report</b>"

        mock_tg = MagicMock()
        engine = BotEngine(strategy=mock_strategy, telegram=mock_tg)

        # Test command handler directly
        res = engine._cmd_stats()
        self.assertEqual(res, "<b>Test Stats Report</b>")


if __name__ == "__main__":
    unittest.main()
