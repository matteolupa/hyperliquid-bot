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

    def test_auto_compounding_allocation(self):
        from hyperliquid_bot.strategies.funding_harvester import FundingHarvesterStrategy

        class DummyClient:
            pass

        strategy = FundingHarvesterStrategy(
            client=DummyClient(),
            allocation_per_position_usd=200.0,
            max_positions=2,
            auto_compound=True,
            dry_run=True,
        )
        self.assertEqual(strategy.current_allocation_usd, 200.0)

        # Simulate earned funding
        strategy.total_funding_earned_usd = 50.0
        # 50.0 / 2 positions = 25.0 extra per position -> 225.0
        self.assertEqual(strategy.current_allocation_usd, 225.0)

    def test_telegram_daily_summary_method(self):
        from hyperliquid_bot.telegram import TelegramNotifier
        notifier = TelegramNotifier(bot_token=None, chat_id=None)
        # Should gracefully return None when disabled
        notifier.send_daily_summary(
            date_str="2026-08-28",
            daily_earnings_usd=10.50,
            total_lifetime_earnings_usd=50.25,
            capital_allocated_usd=500.0,
            daily_roi_pct=2.10,
            compounded_boost_usd=50.25,
            positions_summary="• APEX: APY 150%",
        )

    def test_liquidity_and_persistence_filters(self):
        import tempfile
        import shutil
        from hyperliquid_bot.persistence import StatePersistenceManager
        from hyperliquid_bot.strategies.funding_harvester import FundingHarvesterStrategy

        temp_dir = tempfile.mkdtemp()
        try:
            class MockInfo:
                def meta_and_asset_ctxs(self):
                    return [
                        {"universe": [{"name": "HIGH_LIQ"}, {"name": "LOW_LIQ"}]},
                        [
                            {"funding": "0.0001", "markPx": "100.0", "openInterest": "2000"},  # 200k OI -> APY 87.6%
                            {"funding": "0.0002", "markPx": "1.0", "openInterest": "5000"},    # 5k OI -> APY 175.2% (Illiquid)
                        ],
                    ]

            class MockClient:
                info = MockInfo()

            strategy = FundingHarvesterStrategy(
                client=MockClient(),
                min_entry_apy_pct=10.0,
                min_open_interest_usd=50_000.0,
                persistence_checks_required=2,
                dry_run=True,
            )
            strategy.persistence = StatePersistenceManager(data_dir=temp_dir, filename="test_funding.json")

            # Scan should filter out LOW_LIQ because its OI is 5k < 50k
            opps = strategy.scan_opportunities()
            self.assertEqual(len(opps), 1)
            self.assertEqual(opps[0].coin, "HIGH_LIQ")

            strategy.on_start()

            # Persistence check on tick 1 (should wait)
            strategy.on_tick()
            self.assertNotIn("HIGH_LIQ", strategy.active_positions)
            self.assertEqual(strategy.candidate_seen_count["HIGH_LIQ"], 1)

            # Persistence check on tick 2 (confirmed -> enters)
            strategy.on_tick()
            self.assertIn("HIGH_LIQ", strategy.active_positions)
        finally:
            shutil.rmtree(temp_dir)

    def test_dynamic_live_funding_accrual(self):
        import tempfile
        import shutil
        from hyperliquid_bot.persistence import StatePersistenceManager
        from hyperliquid_bot.strategies.funding_harvester import FundingHarvesterStrategy, ActiveFundingPosition

        temp_dir = tempfile.mkdtemp()
        try:
            class MockInfo:
                def __init__(self):
                    self.current_rate = "0.0001"  # 87.6% APY

                def meta_and_asset_ctxs(self):
                    return [
                        {"universe": [{"name": "TESTCOIN"}]},
                        [{"funding": self.current_rate, "markPx": "10.0", "openInterest": "10000"}],
                    ]

            mock_info = MockInfo()
            class MockClient:
                info = mock_info

            strategy = FundingHarvesterStrategy(
                client=MockClient(),
                allocation_per_position_usd=100.0,
                dry_run=True,
            )
            strategy.persistence = StatePersistenceManager(data_dir=temp_dir, filename="test_accrual.json")
            strategy.on_start()

            # Create an existing position 1 hour ago
            import time
            start_t = time.time() - 3600.0
            strategy.active_positions["TESTCOIN"] = ActiveFundingPosition(
                coin="TESTCOIN",
                size=10.0,
                entry_price=10.0,
                entry_time=start_t,
                hourly_rate_at_entry=0.0001,
                last_accrual_time=start_t,
                current_hourly_rate=0.0001,
            )

            # Change rate in market to 0.0002
            mock_info.current_rate = "0.0002"
            strategy.on_tick()

            # Pos should have accrued ~ 100$ * 0.0002 * 1h = ~$0.02
            pos = strategy.active_positions["TESTCOIN"]
            self.assertGreater(pos.accumulated_funding_usd, 0.015)
            self.assertEqual(pos.current_hourly_rate, 0.0002)
        finally:
            shutil.rmtree(temp_dir)

    def test_portfolio_notional_risk_check(self):
        import tempfile
        import shutil
        from hyperliquid_bot.persistence import StatePersistenceManager
        from hyperliquid_bot.risk import RiskManager, RiskLimits
        from hyperliquid_bot.strategies.funding_harvester import FundingHarvesterStrategy

        temp_dir = tempfile.mkdtemp()
        try:
            class MockInfo:
                def meta_and_asset_ctxs(self):
                    return [
                        {"universe": [{"name": "COIN1"}, {"name": "COIN2"}]},
                        [
                            {"funding": "0.0001", "markPx": "10.0", "openInterest": "100000"},
                            {"funding": "0.0001", "markPx": "10.0", "openInterest": "100000"},
                        ],
                    ]

            class MockClient:
                info = MockInfo()

            # Set max total portfolio notional to $150 and max per position $120
            risk = RiskManager(limits=RiskLimits(max_total_notional_usd=150.0, max_position_size_usd=120.0))
            strategy = FundingHarvesterStrategy(
                client=MockClient(),
                risk_manager=risk,
                allocation_per_position_usd=100.0,
                persistence_checks_required=1,
                max_positions=2,
                dry_run=True,
            )
            strategy.persistence = StatePersistenceManager(data_dir=temp_dir, filename="test_risk.json")
            strategy.on_start()

            # Tick 1: should enter COIN1 ($100 notional)
            strategy.on_tick()
            self.assertIn("COIN1", strategy.active_positions)

            # Tick 2: COIN2 ($100 notional) would make total portfolio $200 > $150 -> rejected by risk manager
            strategy.on_tick()
            self.assertNotIn("COIN2", strategy.active_positions)
        finally:
            shutil.rmtree(temp_dir)

    def test_trailing_apy_exit(self):
        """Ottimizzazione B: la posizione viene chiusa quando APY cala >50% dal picco."""
        import tempfile
        import shutil
        import time
        from hyperliquid_bot.persistence import StatePersistenceManager
        from hyperliquid_bot.strategies.funding_harvester import (
            FundingHarvesterStrategy,
            ActiveFundingPosition,
        )

        temp_dir = tempfile.mkdtemp()
        try:
            class MockInfo:
                def __init__(self):
                    self.rate = "0.0001"  # APY ~87.6%

                def meta_and_asset_ctxs(self):
                    return [
                        {"universe": [{"name": "TOKEN"}]},
                        [{"funding": self.rate, "markPx": "1.0", "openInterest": "100000"}],
                    ]

            mock_info = MockInfo()

            class MockClient:
                info = mock_info

            strategy = FundingHarvesterStrategy(
                client=MockClient(),
                allocation_per_position_usd=100.0,
                trailing_exit_pct=50.0,
                min_exit_apy_pct=1.0,  # bassa soglia assoluta per testare il trailing
                dry_run=True,
            )
            strategy.persistence = StatePersistenceManager(data_dir=temp_dir, filename="test_trailing.json")
            strategy.on_start()

            # Create a position with peak_apy_pct = 100%
            now = time.time()
            strategy.active_positions["TOKEN"] = ActiveFundingPosition(
                coin="TOKEN",
                size=100.0,
                entry_price=1.0,
                entry_time=now - 100,
                hourly_rate_at_entry=0.0001,
                last_accrual_time=now - 1,
                current_hourly_rate=0.0001,
                peak_apy_pct=100.0,  # picco al 100%
            )

            # APY cala a 40% -> 60% di drop dal picco -> sopra la soglia del 50% -> chiude
            mock_info.rate = str(40.0 / (24.0 * 365.0 * 100.0))
            strategy.on_tick()
            self.assertNotIn("TOKEN", strategy.active_positions, "Il trailing exit avrebbe dovuto chiudere la posizione")
        finally:
            shutil.rmtree(temp_dir)

    def test_max_apy_anti_manipulation_filter(self):
        """Ottimizzazione G: token con APY > max_entry_apy_pct vengono ignorati in ingresso."""
        import tempfile
        import shutil
        from hyperliquid_bot.persistence import StatePersistenceManager
        from hyperliquid_bot.strategies.funding_harvester import FundingHarvesterStrategy

        temp_dir = tempfile.mkdtemp()
        try:
            class MockInfo:
                def meta_and_asset_ctxs(self):
                    return [
                        {"universe": [{"name": "MANIPULATION_COIN"}]},
                        [{"funding": "0.2", "markPx": "1.0", "openInterest": "500000"}],
                        # 0.2/h * 24 * 365 * 100 = 175200% APY -> enorme, è manipolazione
                    ]

            class MockClient:
                info = MockInfo()

            strategy = FundingHarvesterStrategy(
                client=MockClient(),
                allocation_per_position_usd=100.0,
                max_entry_apy_pct=500.0,  # limite al 500%
                persistence_checks_required=1,
                dry_run=True,
            )
            strategy.persistence = StatePersistenceManager(data_dir=temp_dir, filename="test_maxapy.json")
            strategy.on_start()
            strategy.on_tick()

            # Non deve essere entrato nonostante OI sufficiente
            self.assertNotIn("MANIPULATION_COIN", strategy.active_positions)
        finally:
            shutil.rmtree(temp_dir)

    def test_ledger_csv_written_on_close(self):
        """Ottimizzazione F: il ledger CSV viene scritto quando una posizione viene chiusa."""
        import tempfile
        import shutil
        import os
        import time
        from hyperliquid_bot.persistence import StatePersistenceManager
        from hyperliquid_bot.ledger import FundingLedger
        from hyperliquid_bot.strategies.funding_harvester import (
            FundingHarvesterStrategy,
            ActiveFundingPosition,
        )

        temp_dir = tempfile.mkdtemp()
        try:
            class MockInfo:
                def meta_and_asset_ctxs(self):
                    # APY = 0 -> posizione viene chiusa
                    return [
                        {"universe": [{"name": "EXITCOIN"}]},
                        [{"funding": "0.000001", "markPx": "1.0", "openInterest": "100000"}],
                    ]

            class MockClient:
                info = MockInfo()

            strategy = FundingHarvesterStrategy(
                client=MockClient(),
                allocation_per_position_usd=100.0,
                min_exit_apy_pct=5.0,
                dry_run=True,
            )
            strategy.persistence = StatePersistenceManager(data_dir=temp_dir, filename="test_ledger.json")
            strategy.ledger = FundingLedger(data_dir=temp_dir, dry_run=True)
            strategy.on_start()

            # Inject a position that will be exited (current APY ~0.876% < 5% exit threshold)
            now = time.time()
            strategy.active_positions["EXITCOIN"] = ActiveFundingPosition(
                coin="EXITCOIN",
                size=100.0,
                entry_price=1.0,
                entry_time=now - 3600,
                hourly_rate_at_entry=0.001,
                last_accrual_time=now - 1,
                current_hourly_rate=0.001,
                peak_apy_pct=8.76,
            )

            strategy.on_tick()

            # EXITCOIN should have been closed
            self.assertNotIn("EXITCOIN", strategy.active_positions)

            # Check CSV ledger was written
            ledger_path = os.path.join(temp_dir, "funding_ledger_dry.csv")
            self.assertTrue(os.path.exists(ledger_path))
            with open(ledger_path, "r") as f:
                content = f.read()
            self.assertIn("EXITCOIN", content)
        finally:
            shutil.rmtree(temp_dir)

    def test_candidate_seen_count_persistence(self):
        """Ottimizzazione I: candidate_seen_count viene salvato e ripristinato correttamente."""
        import tempfile
        import shutil
        from hyperliquid_bot.persistence import StatePersistenceManager
        from hyperliquid_bot.strategies.funding_harvester import FundingHarvesterStrategy

        temp_dir = tempfile.mkdtemp()
        try:
            class MockInfo:
                def meta_and_asset_ctxs(self):
                    return [
                        {"universe": [{"name": "WATCHED"}]},
                        [{"funding": "0.0002", "markPx": "1.0", "openInterest": "100000"}],
                    ]

            class MockClient:
                info = MockInfo()

            strategy = FundingHarvesterStrategy(
                client=MockClient(),
                persistence_checks_required=3,
                dry_run=True,
            )
            strategy.persistence = StatePersistenceManager(data_dir=temp_dir, filename="test_persist.json")
            strategy.on_start()

            # Tick 1: candidato visto 1 volta
            strategy.on_tick()
            self.assertEqual(strategy.candidate_seen_count.get("WATCHED"), 1)

            # Simula riavvio: crea una nuova strategia con la stessa persistence
            strategy2 = FundingHarvesterStrategy(
                client=MockClient(),
                persistence_checks_required=3,
                dry_run=True,
            )
            strategy2.persistence = StatePersistenceManager(data_dir=temp_dir, filename="test_persist.json")
            strategy2.on_start()

            # Il contatore deve essere ripristinato a 1 (non azzerato)
            self.assertEqual(strategy2.candidate_seen_count.get("WATCHED"), 1)
        finally:
            shutil.rmtree(temp_dir)

    def test_telegram_interactive_commands(self):
        """Test registrazione ed esecuzione comandi Telegram interattivi."""
        from hyperliquid_bot.telegram import TelegramNotifier

        notifier = TelegramNotifier(bot_token="test_token", chat_id="12345")
        notifier.register_command("/status", lambda: "REPORT_OK")
        notifier.register_command("balance", lambda: "BALANCE_OK")

        # Mock send_message
        sent_messages = []
        notifier.send_message = lambda msg: sent_messages.append(msg)

        # 1. Update from authorized chat
        update_valid = {
            "update_id": 1,
            "message": {
                "chat": {"id": 12345},
                "text": "/status",
            },
        }
        notifier._handle_update(update_valid)
        self.assertIn("REPORT_OK", sent_messages)

        # 2. Update with /balance
        update_balance = {
            "update_id": 2,
            "message": {
                "chat": {"id": 12345},
                "text": "/balance",
            },
        }
        notifier._handle_update(update_balance)
        self.assertIn("BALANCE_OK", sent_messages)

        # 3. Update with /help
        update_help = {
            "update_id": 3,
            "message": {
                "chat": {"id": 12345},
                "text": "/help",
            },
        }
        notifier._handle_update(update_help)
        self.assertTrue(any("Comandi Disponibili" in m for m in sent_messages))

        # 4. Unauthorized chat update (should be ignored)
        update_unauthorized = {
            "update_id": 4,
            "message": {
                "chat": {"id": 99999},  # Wrong ID
                "text": "/status",
            },
        }
        sent_count_before = len(sent_messages)
        notifier._handle_update(update_unauthorized)
        self.assertEqual(len(sent_messages), sent_count_before)

    def test_funding_strategy_closeall_and_balance(self):
        """Test metodi close_all_positions e get_balance_report di FundingHarvesterStrategy."""
        import tempfile
        import shutil
        import time
        from hyperliquid_bot.persistence import StatePersistenceManager
        from hyperliquid_bot.ledger import FundingLedger
        from hyperliquid_bot.strategies.funding_harvester import (
            FundingHarvesterStrategy,
            ActiveFundingPosition,
        )

        temp_dir = tempfile.mkdtemp()
        try:
            class MockClient:
                pass

            strategy = FundingHarvesterStrategy(
                client=MockClient(),
                allocation_per_position_usd=150.0,
                dry_run=True,
            )
            strategy.persistence = StatePersistenceManager(data_dir=temp_dir, filename="test_close.json")
            strategy.ledger = FundingLedger(data_dir=temp_dir, dry_run=True)
            strategy.on_start()

            # Add two positions
            now = time.time()
            strategy.active_positions["COIN_A"] = ActiveFundingPosition(
                coin="COIN_A", size=10.0, entry_price=15.0, entry_time=now - 3600, hourly_rate_at_entry=0.0001
            )
            strategy.active_positions["COIN_B"] = ActiveFundingPosition(
                coin="COIN_B", size=5.0, entry_price=30.0, entry_time=now - 3600, hourly_rate_at_entry=0.0002
            )

            # Test get_balance_report
            bal_report = strategy.get_balance_report()
            self.assertIn("Stato Portafoglio", bal_report)
            self.assertIn("Equity Totale", bal_report)

            # Test close_all_positions
            res = strategy.close_all_positions(reason="Test Close")
            self.assertIn("Chiusura di Emergenza Completata", res)
            self.assertEqual(len(strategy.active_positions), 0)

            # Calling close_all again when empty
            res_empty = strategy.close_all_positions()
            self.assertIn("Nessuna posizione attiva", res_empty)
        finally:
            shutil.rmtree(temp_dir)

    def test_negative_funding_arbitrage(self):
        """Test arbitraggio funding negativo: acquisto LONG su tassi negativi e ricezione pagamenti."""
        import tempfile
        import shutil
        import time
        from hyperliquid_bot.persistence import StatePersistenceManager
        from hyperliquid_bot.strategies.funding_harvester import FundingHarvesterStrategy

        temp_dir = tempfile.mkdtemp()
        try:
            class MockInfo:
                def __init__(self):
                    # Negative rate: -0.0002/h = -175.2% APY (shorts pay longs)
                    self.rate = "-0.0002"

                def meta_and_asset_ctxs(self):
                    return [
                        {"universe": [{"name": "PANIC_COIN"}]},
                        [{"funding": self.rate, "markPx": "10.0", "openInterest": "100000"}],
                    ]

            mock_info = MockInfo()

            class MockClient:
                info = mock_info

            strategy = FundingHarvesterStrategy(
                client=MockClient(),
                allocation_per_position_usd=100.0,
                persistence_checks_required=1,
                allow_negative_funding=True,
                dry_run=True,
            )
            strategy.persistence = StatePersistenceManager(data_dir=temp_dir, filename="test_neg.json")
            strategy.on_start()

            # 1. Scan opportunities detects side="LONG" with positive effective APY
            opps = strategy.scan_opportunities()
            self.assertEqual(len(opps), 1)
            self.assertEqual(opps[0].side, "LONG")
            self.assertAlmostEqual(opps[0].annualized_apy_pct, 175.2, places=1)

            # 2. Enter position on tick
            strategy.on_tick()
            self.assertIn("PANIC_COIN", strategy.active_positions)
            pos = strategy.active_positions["PANIC_COIN"]
            self.assertEqual(pos.side, "LONG")

            # 3. Simulate 1 hour passing and verify positive funding accrual
            pos.last_accrual_time = time.time() - 3600
            strategy.on_tick()
            self.assertGreater(pos.accumulated_funding_usd, 0.0)

            # 4. If rate decays below exit threshold (e.g. -0.000001 = 0.87% APY < 3%), position exits
            mock_info.rate = "-0.000001"
            strategy.on_tick()
            self.assertNotIn("PANIC_COIN", strategy.active_positions, "Position should exit when funding rate decays below threshold")
        finally:
            shutil.rmtree(temp_dir)

    def test_history_and_watchlist_reporting(self):
        """Test comandi /history e /watchlist per consultare lo storico del ledger e le opportunità."""
        import tempfile
        import shutil
        from hyperliquid_bot.persistence import StatePersistenceManager
        from hyperliquid_bot.ledger import FundingLedger
        from hyperliquid_bot.strategies.funding_harvester import FundingHarvesterStrategy

        temp_dir = tempfile.mkdtemp()
        try:
            class MockInfo:
                def meta_and_asset_ctxs(self):
                    return [
                        {"universe": [{"name": "ACE"}, {"name": "SOL"}]},
                        [
                            {"funding": "0.0005", "markPx": "1.5", "openInterest": "200000"},
                            {"funding": "-0.0003", "markPx": "150.0", "openInterest": "500000"},
                        ],
                    ]

            class MockClient:
                info = MockInfo()

            strategy = FundingHarvesterStrategy(
                client=MockClient(),
                allocation_per_position_usd=100.0,
                dry_run=True,
            )
            strategy.persistence = StatePersistenceManager(data_dir=temp_dir, filename="test_hw.json")
            strategy.ledger = FundingLedger(data_dir=temp_dir, dry_run=True)
            strategy.on_start()

            # 1. Test get_watchlist_report
            wl_report = strategy.get_watchlist_report(limit=5)
            self.assertIn("Top 2 Opportunità", wl_report)
            self.assertIn("ACE", wl_report)
            self.assertIn("SOL", wl_report)
            self.assertIn("🔴 SHORT", wl_report)
            self.assertIn("🟢 LONG", wl_report)

            # 2. Test get_history_report with empty ledger
            hist_empty = strategy.get_history_report()
            self.assertIn("Nessuna operazione chiusa", hist_empty)

            # 3. Add record to ledger and test get_history_report
            strategy.ledger.record_close(
                coin="ACE",
                size=10.0,
                entry_price=1.5,
                entry_time=1000.0,
                exit_time=4600.0,
                apy_entry_pct=438.0,
                apy_exit_pct=219.0,
                funding_usd=0.0450,
                exit_reason="Trailing APY Exit",
                side="SHORT",
            )
            hist_report = strategy.get_history_report()
            self.assertIn("Ultime 1 Posizioni Chiuse", hist_report)
            self.assertIn("ACE", hist_report)
            self.assertIn("+$0.0450 USD", hist_report)
            self.assertIn("Trailing APY Exit", hist_report)
        finally:
            shutil.rmtree(temp_dir)


if __name__ == "__main__":
    unittest.main()
