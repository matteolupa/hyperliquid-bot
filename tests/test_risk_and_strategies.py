"""Unit tests for RiskManager and Strategy logic."""

import unittest
from hyperliquid_bot.risk import RiskLimits, RiskManager
from hyperliquid_bot.strategies.funding_harvester import FundingHarvesterStrategy
from hyperliquid_bot.strategies.market_maker import AdaptiveMarketMakerStrategy
from hyperliquid_bot.strategies.scalper import ScalperStrategy
from hyperliquid_bot.fees import FeeCalculator


class TestRiskAndStrategies(unittest.TestCase):

    def test_risk_manager_circuit_breaker(self):
        limits = RiskLimits(max_drawdown_pct=0.10)  # 10% max DD
        rm = RiskManager(limits=limits, initial_equity=10_000.0)

        # Equity drops to $9,500 (5% DD) -> Not tripped
        is_tripped = rm.update_equity(9500.0)
        self.assertFalse(is_tripped)
        self.assertFalse(rm.is_circuit_breaker_tripped)

        # Equity drops to $8,900 (11% DD from peak $10,000) -> Tripped!
        is_tripped = rm.update_equity(8900.0)
        self.assertTrue(is_tripped)
        self.assertTrue(rm.is_circuit_breaker_tripped)

        # Further orders must be rejected
        valid = rm.validate_order(symbol="ETH", size=1.0, price=3000.0)
        self.assertFalse(valid)

    def test_risk_manager_order_limits(self):
        limits = RiskLimits(
            max_position_size_usd=5_000.0,
            max_total_notional_usd=10_000.0,
            min_order_size_usd=20.0,
        )
        rm = RiskManager(limits=limits)

        # Too small order ($10 < $20)
        self.assertFalse(rm.validate_order(symbol="SOL", size=0.1, price=100.0))

        # Valid order ($3000)
        self.assertTrue(rm.validate_order(symbol="ETH", size=1.0, price=3000.0))

        # Exceeds max position size ($6000 > $5000)
        self.assertFalse(rm.validate_order(symbol="ETH", size=2.0, price=3000.0))

    def test_funding_harvester_calculations(self):
        # 0.0001 hourly rate = 0.01% / hour
        # APY = 0.0001 * 24 * 365 * 100% = 87.6%
        hourly_rate = 0.0001
        apy = FundingHarvesterStrategy.calculate_apy(hourly_rate)
        self.assertAlmostEqual(apy, 87.6, places=2)

        # Notional $10,000 with 0.01%/h rate -> Payment = $1.00 / hour
        payment = FundingHarvesterStrategy.calculate_funding_payment(10_000.0, hourly_rate)
        self.assertAlmostEqual(payment, 1.0, places=4)

    def test_market_maker_quotes_and_skew(self):
        # Dummy client not needed for mathematical quote calculation
        class DummyClient:
            pass

        mm = AdaptiveMarketMakerStrategy(
            client=DummyClient(),
            symbol="ETH",
            order_size_usd=300.0,
            base_spread_bps=10.0,  # 10 bps spread
            inventory_risk_gamma=0.2,
            max_inventory_usd=3000.0,
        )

        mid_price = 3000.0

        # Scenario 1: Zero inventory -> Reservation price == Mid price
        quotes_neutral = mm.calculate_quotes(mid_price=mid_price, inventory_units=0.0)
        self.assertEqual(quotes_neutral.reservation_price, mid_price)
        self.assertLess(quotes_neutral.bid_price, mid_price)
        self.assertGreater(quotes_neutral.ask_price, mid_price)
        self.assertAlmostEqual(quotes_neutral.spread_bps, 10.0, places=1)

        # Scenario 2: Long inventory (+1 ETH = $3000) -> Reservation price drops to sell inventory
        quotes_long = mm.calculate_quotes(mid_price=mid_price, inventory_units=1.0)
        self.assertLess(quotes_long.reservation_price, mid_price)
        self.assertLess(quotes_long.bid_price, quotes_neutral.bid_price)
        self.assertLess(quotes_long.ask_price, quotes_neutral.ask_price)

    def test_scalper_strategy_breakeven_tp(self):
        class DummyClient:
            def get_all_mids(self):
                return {"ETH": "3000.0"}

        scalper = ScalperStrategy(
            client=DummyClient(),
            symbol="ETH",
            order_size_usd=50.0,
            profit_target_pct=1.0,  # +1% net target
            dry_run=True,
        )

        scalper.on_start()
        scalper.on_tick()

        # Check that trade was created
        self.assertIsNotNone(scalper.active_trade)
        trade = scalper.active_trade
        self.assertEqual(trade.symbol, "ETH")
        self.assertEqual(trade.entry_price, 3000.0)
        self.assertGreater(trade.breakeven_price, 3000.0)
        self.assertGreater(trade.take_profit_price, trade.breakeven_price)
        self.assertGreater(trade.target_net_profit_usd, 0.0)

    def test_telegram_notifier_disabled(self):
        from hyperliquid_bot.telegram import TelegramNotifier
        notifier = TelegramNotifier(bot_token=None, chat_id=None)
        self.assertFalse(notifier.is_enabled)
        # Should gracefully return False without raising exceptions
        res = notifier.send_message("Test message")
        self.assertFalse(res)

    def test_state_persistence_save_load(self):
        import tempfile
        import shutil
        from hyperliquid_bot.persistence import StatePersistenceManager

        temp_dir = tempfile.mkdtemp()
        try:
            pm = StatePersistenceManager(data_dir=temp_dir, filename="test_state.json")
            sample_state = {
                "total_funding_earned_usd": 12.34,
                "active_positions": {"ETH": {"size": 0.05, "entry_price": 2500.0}},
            }
            # Save
            self.assertTrue(pm.save_state(sample_state))
            # Load
            loaded = pm.load_state()
            self.assertEqual(loaded["total_funding_earned_usd"], 12.34)
            self.assertEqual(loaded["active_positions"]["ETH"]["entry_price"], 2500.0)
        finally:
            shutil.rmtree(temp_dir)


if __name__ == "__main__":
    unittest.main()
