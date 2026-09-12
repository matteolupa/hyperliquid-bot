"""Unit tests for the 4 Advanced Delta-Neutral Strategy Features:
1. Funding Rate Prediction / Trend Detection
2. Multi-Exchange Spread Monitoring
3. Basis Trade Monitoring (Spot vs Perp Premium)
4. Smart Multi-Asset Rotation & Composite Scoring
"""

import tempfile
import shutil
import unittest
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

from hyperliquid_bot.funding_analytics import FundingAnalytics, FundingTrend
from hyperliquid_bot.multi_exchange import MultiExchangeMonitor, ExchangeSpread
from hyperliquid_bot.basis_monitor import BasisMonitor, BasisData
from hyperliquid_bot.strategies.funding_harvester import FundingHarvesterStrategy, FundingOpportunity, ActiveFundingPosition
from hyperliquid_bot.persistence import StatePersistenceManager
from hyperliquid_bot.ledger import FundingLedger


class TestAdvancedDeltaNeutralFeatures(unittest.TestCase):
    """Test suite covering the 4 advanced delta-neutral quant modules."""

    def test_funding_trend_detection_rising(self):
        """Test that linear regression and EMA correctly identify a RISING funding rate trend."""
        class MockClient:
            class Info:
                def funding_history(self, coin: str, start_time: int) -> List[Dict[str, Any]]:
                    base = 0.00005
                    return [
                        {"coin": coin, "fundingRate": str(base + i * 0.00001), "time": 1000 + i * 3600000}
                        for i in range(10)
                    ]
            info = Info()

        analytics = FundingAnalytics(client=MockClient(), lookback_hours=24, refresh_interval_seconds=10.0)
        trend = analytics.get_trend("HYPE")

        self.assertIsNotNone(trend)
        self.assertEqual(trend.coin, "HYPE")
        self.assertEqual(trend.trend, "RISING")
        self.assertGreater(trend.slope_4h, 0.0)
        self.assertGreater(trend.avg_4h, trend.avg_8h)
        self.assertGreaterEqual(trend.confidence, 0.75)
        self.assertGreater(trend.predicted_apy_4h, trend.avg_4h * 24 * 365 * 100)

        report = analytics.format_funding_report(["HYPE"])
        self.assertIn("HYPE", report)
        self.assertIn("📈 RISING", report)

    def test_funding_trend_detection_falling(self):
        """Test that linear regression and EMA correctly identify a FALLING funding rate trend."""
        class MockClient:
            class Info:
                def funding_history(self, coin: str, start_time: int) -> List[Dict[str, Any]]:
                    base = 0.00020
                    return [
                        {"coin": coin, "fundingRate": str(base - i * 0.00002), "time": 1000 + i * 3600000}
                        for i in range(10)
                    ]
            info = Info()

        analytics = FundingAnalytics(client=MockClient(), lookback_hours=24, refresh_interval_seconds=10.0)
        trend = analytics.get_trend("ETH")

        self.assertIsNotNone(trend)
        self.assertEqual(trend.coin, "ETH")
        self.assertEqual(trend.trend, "FALLING")
        self.assertLess(trend.slope_4h, 0.0)
        self.assertLess(trend.avg_4h, trend.avg_8h)

        report = analytics.format_funding_report(["ETH"])
        self.assertIn("📉 FALLING", report)

    def test_multi_exchange_rate_normalization(self):
        """Verify normalization of Binance (8h -> 1h) and Bybit variable intervals to hourly."""
        monitor = MultiExchangeMonitor()

        monitor._fetch_binance = MagicMock(return_value={
            "BTCUSDT": 0.0008 / 8.0,
            "ETHUSDT": 0.0004 / 8.0,
        })
        monitor._fetch_bybit = MagicMock(return_value={
            "BTCUSDT": 0.00012,
            "ETHUSDT": 0.00003,
        })
        monitor._fetch_dydx = MagicMock(return_value={
            "BTC-USD": 0.00008,
        })

        hl_rates = {
            "BTC": 0.00010,
            "ETH": 0.00006,
        }

        spreads = monitor.fetch_spreads(["BTC", "ETH"], hl_rates)

        self.assertIn("BTC", spreads)
        btc_spread = spreads["BTC"]
        self.assertAlmostEqual(btc_spread.hl_hourly_rate, 0.00010)
        self.assertAlmostEqual(btc_spread.binance_hourly_rate, 0.00010)
        self.assertEqual(btc_spread.best_exchange, "Bybit")
        self.assertGreater(btc_spread.best_apy, btc_spread.hl_apy)

        self.assertIn("ETH", spreads)
        eth_spread = spreads["ETH"]
        self.assertEqual(eth_spread.best_exchange, "Hyperliquid")
        self.assertGreaterEqual(eth_spread.hl_vs_best_spread_pct, 0.0)

        report = monitor.format_spread_report(spreads)
        self.assertIn("Multi-Exchange Funding Spread", report)
        self.assertIn("BTC", report)
        self.assertIn("ETH", report)

    def test_basis_calculation_premium_and_discount(self):
        """Verify Spot vs Perp basis computation, premium/discount detection, and APY projection."""
        class MockClient:
            class Info:
                def spot_meta_and_asset_ctxs(self):
                    return (
                        {
                            "tokens": [
                                {"index": 0, "name": "USDC"},
                                {"index": 1, "name": "HYPE"},
                                {"index": 2, "name": "PURR"},
                            ],
                            "universe": [
                                {"name": "@107", "tokens": [1, 0]},
                                {"name": "PURR/USDC", "tokens": [2, 0]},
                            ],
                        },
                        [
                            {"midPx": "100.00"},
                            {"midPx": "2.00"},
                        ],
                    )

                def meta_and_asset_ctxs(self):
                    return (
                        {"universe": [{"name": "HYPE"}, {"name": "PURR"}]},
                        [
                            {"markPx": "100.50"},
                            {"markPx": "1.98"},
                        ],
                    )
            info = Info()

        monitor = BasisMonitor(client=MockClient(), refresh_interval_seconds=60.0)
        basis = monitor.get_basis(["HYPE", "PURR"])

        self.assertIn("HYPE", basis)
        hype_data = basis["HYPE"]
        self.assertEqual(hype_data.spot_mid_price, 100.00)
        self.assertEqual(hype_data.perp_mark_price, 100.50)
        self.assertAlmostEqual(hype_data.basis_bps, 50.0)
        self.assertAlmostEqual(hype_data.basis_pct, 0.5)
        self.assertEqual(hype_data.basis_direction, "PREMIUM")
        self.assertGreater(hype_data.annualized_basis_apy, 0.0)

        self.assertIn("PURR", basis)
        pur_data = basis["PURR"]
        self.assertEqual(pur_data.spot_mid_price, 2.00)
        self.assertEqual(pur_data.perp_mark_price, 1.98)
        self.assertAlmostEqual(pur_data.basis_bps, -100.0)
        self.assertEqual(pur_data.basis_direction, "DISCOUNT")

        report = monitor.format_basis_report(["HYPE", "PURR"])
        self.assertIn("PREMIUM", report)
        self.assertIn("DISCOUNT", report)
        self.assertIn("50.00 bps", report)

    def test_composite_scoring_algorithm(self):
        """Verify that composite scoring favors rising trend, positive basis premium, and healthy cross-exchange spread."""
        class DummyClient:
            info = MagicMock()

        strategy = FundingHarvesterStrategy(
            client=DummyClient(),
            dry_run=True,
            enable_trend_detection=False,
            enable_cross_exchange=False,
            enable_basis_monitor=False,
        )

        opp1 = FundingOpportunity(
            coin="COIN1",
            mark_price=10.0,
            hourly_funding_rate=0.0001,
            annualized_apy_pct=87.6,
            open_interest_usd=100_000.0,
        )
        score1 = strategy.compute_composite_score(opp1)
        self.assertGreater(score1, 0.0)

        mock_analytics = MagicMock()
        mock_analytics.get_trend.return_value = FundingTrend(
            coin="COIN2",
            current_hourly_rate=0.0001,
            avg_1h=0.0001,
            avg_4h=0.0001,
            avg_8h=0.00008,
            avg_24h=0.00005,
            slope_4h=0.00001,
            trend="RISING",
            confidence=1.0,
            predicted_apy_4h=120.0,
            samples_count=10,
        )
        strategy.funding_analytics = mock_analytics

        mock_basis = MagicMock()
        mock_basis.get_basis.return_value = {
            "COIN2": BasisData(
                coin="COIN2",
                spot_mid_price=10.0,
                perp_mark_price=10.05,
                basis_bps=50.0,
                basis_pct=0.5,
                basis_direction="PREMIUM",
                annualized_basis_apy=54.7,
            )
        }
        strategy.basis_monitor = mock_basis

        strategy._exchange_spreads = {
            "COIN2": ExchangeSpread(
                coin="COIN2",
                hl_hourly_rate=0.0001,
                hl_apy=87.6,
                best_exchange="Hyperliquid",
                best_apy=87.6,
                hl_vs_best_spread_pct=5.0,
            )
        }

        opp2 = FundingOpportunity(
            coin="COIN2",
            mark_price=10.0,
            hourly_funding_rate=0.0001,
            annualized_apy_pct=87.6,
            open_interest_usd=100_000.0,
        )
        score2 = strategy.compute_composite_score(opp2)

        self.assertGreater(score2, score1 + 40.0)
        self.assertEqual(opp2.funding_trend, "RISING")
        self.assertEqual(opp2.basis_direction, "PREMIUM")

    def test_smart_rotation_execution(self):
        """Test that Smart Multi-Asset Rotation cleanly rotates capital from an inferior position to a superior candidate."""
        temp_dir = tempfile.mkdtemp()
        try:
            class MockInfo:
                def meta_and_asset_ctxs(self):
                    return (
                        {"universe": [
                            {"name": "LOW1"},
                            {"name": "LOW2"},
                            {"name": "LOW3"},
                            {"name": "SUPER_STAR"},
                        ]},
                        [
                            {"funding": "0.0000125", "markPx": "10.0", "openInterest": "20000"},
                            {"funding": "0.0000140", "markPx": "20.0", "openInterest": "20000"},
                            {"funding": "0.0000130", "markPx": "30.0", "openInterest": "20000"},
                            {"funding": "0.0002000", "markPx": "50.0", "openInterest": "50000"},
                        ],
                    )

            class MockClient:
                def __init__(self):
                    self.info = MockInfo()
                    self.closed_orders = []
                    self.opened_orders = []

                def get_spot_perp_matches(self):
                    return {
                        "LOW1": {"spot_pair_name": "@1"},
                        "LOW2": {"spot_pair_name": "@2"},
                        "LOW3": {"spot_pair_name": "@3"},
                        "SUPER_STAR": {"spot_pair_name": "@4"},
                    }

                def order_market_open(self, name: str, is_buy: bool, size: float, slippage: float = 0.05):
                    self.opened_orders.append({"name": name, "is_buy": is_buy, "size": size})
                    return {"status": "ok"}

                def order_market_close(self, name: str, size: Optional[float] = None, is_spot: bool = False, slippage: float = 0.05):
                    self.closed_orders.append({"name": name, "size": size, "is_spot": is_spot})
                    return {"status": "ok"}

            client = MockClient()
            strategy = FundingHarvesterStrategy(
                client=client,
                allocation_per_position_usd=100.0,
                max_positions=3,
                rotation_min_spread_pct=30.0,
                rotation_max_breakeven_hours=4.0,
                persistence_checks_required=1,
                dry_run=False,
                enable_trend_detection=False,
                enable_cross_exchange=False,
                enable_basis_monitor=False,
            )
            strategy.persistence = StatePersistenceManager(data_dir=temp_dir, filename="test_rot.json")
            strategy.ledger = FundingLedger(data_dir=temp_dir, dry_run=False)
            strategy.on_start()

            now = 1000.0
            strategy.active_positions = {
                "LOW1": ActiveFundingPosition(
                    coin="LOW1", size=10.0, entry_price=10.0, entry_time=now,
                    hourly_rate_at_entry=0.0000125, side="SHORT", hedge_mode="spot-perp",
                    spot_pair_name="@1", spot_size=10.0, perp_size=10.0,
                ),
                "LOW2": ActiveFundingPosition(
                    coin="LOW2", size=5.0, entry_price=20.0, entry_time=now,
                    hourly_rate_at_entry=0.0000140, side="SHORT", hedge_mode="spot-perp",
                    spot_pair_name="@2", spot_size=5.0, perp_size=5.0,
                ),
                "LOW3": ActiveFundingPosition(
                    coin="LOW3", size=3.33, entry_price=30.0, entry_time=now,
                    hourly_rate_at_entry=0.0000130, side="SHORT", hedge_mode="spot-perp",
                    spot_pair_name="@3", spot_size=3.33, perp_size=3.33,
                ),
            }

            self.assertEqual(len(strategy.active_positions), 3)
            self.assertIn("LOW1", strategy.active_positions)

            strategy.on_tick()

            self.assertNotIn("LOW1", strategy.active_positions)
            self.assertIn("SUPER_STAR", strategy.active_positions)
            self.assertEqual(len(strategy.active_positions), 3)

            closed_names = [o["name"] for o in client.closed_orders]
            self.assertIn("@1", closed_names)
            self.assertIn("LOW1", closed_names)

            opened_names = [o["name"] for o in client.opened_orders]
            self.assertIn("@4", opened_names)
            self.assertIn("SUPER_STAR", opened_names)

            history = strategy.ledger.get_recent_trades(limit=5)
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["coin"], "LOW1")
            self.assertIn("Rotazione", history[0]["exit_reason"])
        finally:
            shutil.rmtree(temp_dir)

    def test_smart_rotation_skipped_when_gap_below_threshold(self):
        """Verify that rotation does NOT occur if the APY gap is insufficient."""
        temp_dir = tempfile.mkdtemp()
        try:
            class MockInfo:
                def meta_and_asset_ctxs(self):
                    return (
                        {"universe": [{"name": "ACTIVE1"}, {"name": "CANDIDATE"}]},
                        [
                            {"funding": "0.0000125", "markPx": "10.0", "openInterest": "20000"},
                            {"funding": "0.0000300", "markPx": "10.0", "openInterest": "20000"},
                        ],
                    )

            class MockClient:
                info = MockInfo()
                def get_spot_perp_matches(self):
                    return {"ACTIVE1": {"spot_pair_name": "@1"}, "CANDIDATE": {"spot_pair_name": "@2"}}

            strategy = FundingHarvesterStrategy(
                client=MockClient(),
                allocation_per_position_usd=100.0,
                max_positions=1,
                rotation_min_spread_pct=30.0,
                persistence_checks_required=1,
                dry_run=True,
                enable_trend_detection=False,
                enable_cross_exchange=False,
                enable_basis_monitor=False,
            )
            strategy.persistence = StatePersistenceManager(data_dir=temp_dir, filename="test_rot_skip.json")
            strategy.ledger = FundingLedger(data_dir=temp_dir, dry_run=True)
            strategy.on_start()

            strategy.active_positions = {
                "ACTIVE1": ActiveFundingPosition(
                    coin="ACTIVE1", size=10.0, entry_price=10.0, entry_time=1000.0,
                    hourly_rate_at_entry=0.0000125, side="SHORT", hedge_mode="spot-perp",
                )
            }

            strategy.on_tick()

            self.assertIn("ACTIVE1", strategy.active_positions)
            self.assertNotIn("CANDIDATE", strategy.active_positions)
        finally:
            shutil.rmtree(temp_dir)


if __name__ == "__main__":
    unittest.main()
