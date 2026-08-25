"""Unit tests for the Hyperliquid Fee Calculator."""

import math
import unittest
from hyperliquid_bot.fees import FeeCalculator, DEFAULT_FEE_TIERS


class TestFeeCalculator(unittest.TestCase):

    def setUp(self):
        self.calculator = FeeCalculator()

    def test_calculate_trade_fee_perp_taker_tier0(self):
        # Trade: 1.0 ETH at $3000 -> Notional $3000
        # Tier 0 Perp Taker fee = 3.5 bps (0.035%)
        # Fee = 3000 * 0.00035 = $1.05
        breakdown = self.calculator.calculate_trade_fee(
            size=1.0,
            price=3000.0,
            is_maker=False,
            is_spot=False,
            tier_level=0,
        )

        self.assertEqual(breakdown.notional_usd, 3000.0)
        self.assertEqual(breakdown.base_fee_rate_bps, 3.5)
        self.assertEqual(breakdown.effective_fee_rate_bps, 3.5)
        self.assertEqual(breakdown.base_fee_usd, 1.05)
        self.assertEqual(breakdown.total_fee_usd, 1.05)
        self.assertFalse(breakdown.is_maker)
        self.assertFalse(breakdown.is_rebate)

    def test_calculate_trade_fee_perp_maker_tier0(self):
        # Tier 0 Perp Maker fee = 1.0 bps (0.010%)
        # Trade: 2.0 BTC at $50000 -> Notional $100,000
        # Fee = 100,000 * 0.00010 = $10.0
        breakdown = self.calculator.calculate_trade_fee(
            size=2.0,
            price=50000.0,
            is_maker=True,
            is_spot=False,
            tier_level=0,
        )

        self.assertEqual(breakdown.notional_usd, 100000.0)
        self.assertEqual(breakdown.base_fee_rate_bps, 1.0)
        self.assertEqual(breakdown.base_fee_usd, 10.0)
        self.assertEqual(breakdown.total_fee_usd, 10.0)
        self.assertTrue(breakdown.is_maker)
        self.assertFalse(breakdown.is_rebate)

    def test_calculate_trade_fee_spot_taker(self):
        # Tier 0 Spot Taker fee = 4.0 bps (0.040%)
        # Trade: 100 SOL at $150 -> Notional $15,000
        # Fee = 15,000 * 0.0004 = $6.0
        breakdown = self.calculator.calculate_trade_fee(
            size=100.0,
            price=150.0,
            is_maker=False,
            is_spot=True,
            tier_level=0,
        )

        self.assertEqual(breakdown.notional_usd, 15000.0)
        self.assertEqual(breakdown.base_fee_rate_bps, 4.0)
        self.assertEqual(breakdown.base_fee_usd, 6.0)
        self.assertEqual(breakdown.total_fee_usd, 6.0)

    def test_maker_rebate_high_tier(self):
        # Tier 3 Perp Maker fee = -0.1 bps (-0.001% rebate)
        # Trade: 10 BTC at $60,000 -> Notional $600,000
        # Rebate = 600,000 * -0.00001 = -$6.0
        breakdown = self.calculator.calculate_trade_fee(
            size=10.0,
            price=60000.0,
            is_maker=True,
            is_spot=False,
            tier_level=3,
        )

        self.assertEqual(breakdown.base_fee_rate_bps, -0.1)
        self.assertEqual(breakdown.base_fee_usd, -6.0)
        self.assertEqual(breakdown.total_fee_usd, -6.0)
        self.assertTrue(breakdown.is_rebate)

    def test_referral_discount_and_builder_fee(self):
        # Notional $10,000, Perp Taker Tier 0 (3.5 bps -> $3.50 base fee)
        # 4% referral discount -> $3.50 * 0.04 = $0.14 discount -> effective $3.36
        # Builder fee 1.0 bps -> $10,000 * 0.0001 = $1.00
        # Total fee = $3.36 + $1.00 = $4.36
        breakdown = self.calculator.calculate_trade_fee(
            size=10.0,
            price=1000.0,
            is_maker=False,
            is_spot=False,
            referral_discount_pct=0.04,
            builder_fee_bps=1.0,
            tier_level=0,
        )

        self.assertEqual(breakdown.base_fee_usd, 3.50)
        self.assertEqual(breakdown.referral_discount_usd, 0.14)
        self.assertEqual(breakdown.effective_fee_usd, 3.36)
        self.assertEqual(breakdown.builder_fee_usd, 1.00)
        self.assertEqual(breakdown.total_fee_usd, 4.36)

    def test_14d_weighted_volume_and_tier_lookup(self):
        # Perp vol $10M + Spot vol $10M -> Weighted vol = 10M + 2*10M = $30M
        weighted_vol = self.calculator.calculate_14d_weighted_volume(
            perp_14d_volume=10_000_000,
            spot_14d_volume=10_000_000,
        )
        self.assertEqual(weighted_vol, 30_000_000)

        # $30M falls in Tier 2 (>= $25M and < $100M)
        tier = self.calculator.get_tier_by_volume(weighted_vol)
        self.assertEqual(tier.tier_level, 2)
        self.assertEqual(tier.perp_maker_bps, 0.0)
        self.assertEqual(tier.perp_taker_bps, 2.5)

    def test_breakeven_price_long(self):
        # Long 1 unit of BTC at $50,000.
        # Taker on entry (3.5 bps = 0.00035), Maker on exit (1.0 bps = 0.00010)
        entry_price = 50000.0
        be_price = self.calculator.calculate_breakeven_price(
            entry_price=entry_price,
            is_long=True,
            entry_is_maker=False,
            exit_is_maker=True,
            tier_level=0,
        )

        self.assertGreater(be_price, entry_price)
        # Check that net PnL at be_price is zero
        round_trip = self.calculator.calculate_round_trip_fee(
            size=1.0,
            entry_price=entry_price,
            exit_price=be_price,
            entry_is_maker=False,
            exit_is_maker=True,
            tier_level=0,
        )
        gross_pnl = be_price - entry_price
        net_pnl = gross_pnl - round_trip["total_fee_usd"]
        self.assertAlmostEqual(net_pnl, 0.0, places=3)

    def test_breakeven_price_short(self):
        # Short 1 unit of ETH at $3000.
        # Taker on entry, Taker on exit (3.5 bps both)
        entry_price = 3000.0
        be_price = self.calculator.calculate_breakeven_price(
            entry_price=entry_price,
            is_long=False,
            entry_is_maker=False,
            exit_is_maker=False,
            tier_level=0,
        )

        self.assertLess(be_price, entry_price)
        round_trip = self.calculator.calculate_round_trip_fee(
            size=1.0,
            entry_price=entry_price,
            exit_price=be_price,
            entry_is_maker=False,
            exit_is_maker=False,
            tier_level=0,
        )
        gross_pnl = entry_price - be_price
        net_pnl = gross_pnl - round_trip["total_fee_usd"]
        self.assertAlmostEqual(net_pnl, 0.0, places=3)


if __name__ == "__main__":
    unittest.main()
