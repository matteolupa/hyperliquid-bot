#!/usr/bin/env python3
"""CLI Entrypoint for running Hyperliquid 24/7 Trading Bot."""

import argparse
import sys

from hyperliquid_bot import (
    AdaptiveMarketMakerStrategy,
    BotEngine,
    FeeCalculator,
    FundingHarvesterStrategy,
    HyperliquidClient,
    HyperliquidConfig,
    RiskLimits,
    RiskManager,
    ScalperStrategy,
    TelegramNotifier,
    setup_logger,
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Hyperliquid 24/7 Algorithmic Trading Bot",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--strategy",
        type=str,
        choices=["funding", "market_maker", "scalper"],
        default="scalper",
        help="Strategy to run: 'scalper' (Buy & Take Profit), 'funding' (Delta-Neutral Funding Harvester), 'market_maker' (Adaptive Grid/MM)",
    )
    parser.add_argument(
        "--symbol",
        type=str,
        default="ETH",
        help="Target symbol for scalper / market maker strategy (e.g. BTC, ETH, SOL)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Run in simulation mode without placing real orders (default: True)",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Enable LIVE order placement (overrides --dry-run)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=None,
        help="Execution loop interval in seconds (default: 10s for Scalper/MM, 30s for Funding)",
    )
    parser.add_argument(
        "--order-size-usd",
        type=float,
        default=50.0,
        help="Order / position size in USD (e.g. 50.0 for $50 / 50€)",
    )
    parser.add_argument(
        "--profit-target-pct",
        type=float,
        default=0.8,
        help="Net profit target %% above break-even for Scalper (e.g. 0.8 for +0.8%%)",
    )
    parser.add_argument(
        "--stop-loss-pct",
        type=float,
        default=2.0,
        help="Stop loss %% for Scalper (e.g. 2.0 for -2.0%%)",
    )
    parser.add_argument(
        "--report-interval",
        type=float,
        default=300.0,
        help="Interval in seconds between periodic status/earnings reports (default: 300s / 5 minutes)",
    )
    parser.add_argument(
        "--min-apy",
        type=float,
        default=12.0,
        help="Minimum annualized funding APY %% required to enter a position (Funding strategy)",
    )
    parser.add_argument(
        "--auto-compound",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Reinvest funding profits automatically into position sizes (Auto-Compounding)",
    )
    parser.add_argument(
        "--min-oi-usd",
        type=float,
        default=50_000.0,
        help="Minimum Open Interest in USD to prevent entering illiquid markets (default: $50,000)",
    )
    parser.add_argument(
        "--persistence-checks",
        type=int,
        default=2,
        help="Number of consecutive scans a token must maintain high APY before entering (default: 2)",
    )
    parser.add_argument(
        "--max-apy",
        type=float,
        default=1000.0,
        help="Anti-manipulation filter: ignore tokens with APY above this threshold (default: 1000%%)",
    )
    parser.add_argument(
        "--trailing-exit",
        type=float,
        default=50.0,
        help="Trailing APY exit: close position if APY drops by this %% from its peak (default: 50%%)",
    )
    parser.add_argument(
        "--spread-bps",
        type=float,
        default=8.0,
        help="Base Bid/Ask spread in basis points for Market Maker (1 bps = 0.01%)",
    )
    parser.add_argument(
        "--max-drawdown-pct",
        type=float,
        default=5.0,
        help="Emergency Circuit Breaker max drawdown percentage (e.g. 5.0 for 5%)",
    )

    return parser.parse_args()


def main():
    args = parse_args()

    # Initialize Logger first (Rotates log to logs/bot.log)
    logger = setup_logger(log_dir="logs", log_file="bot.log")

    try:
        # Determine execution mode (Safety: dry-run by default unless --live is specified)
        is_dry_run = True if not args.live else False

        # Load configuration
        config = HyperliquidConfig.from_env()
        client = HyperliquidClient(config)
        fee_calculator = FeeCalculator()

        # Risk Manager
        risk_limits = RiskLimits(
            max_drawdown_pct=args.max_drawdown_pct / 100.0,
            max_position_size_usd=args.order_size_usd * 10,
        )
        risk_manager = RiskManager(limits=risk_limits)

        # Telegram Notifier
        telegram = TelegramNotifier(
            bot_token=config.telegram_bot_token,
            chat_id=config.telegram_chat_id,
        )

        # Instantiate selected strategy
        if args.strategy == "scalper":
            interval = args.interval if args.interval is not None else 10.0
            strategy = ScalperStrategy(
                client=client,
                symbol=args.symbol,
                order_size_usd=args.order_size_usd,
                profit_target_pct=args.profit_target_pct,
                stop_loss_pct=args.stop_loss_pct,
                risk_manager=risk_manager,
                fee_calculator=fee_calculator,
                dry_run=is_dry_run,
                telegram=telegram,
            )
        elif args.strategy == "funding":
            interval = args.interval if args.interval is not None else 30.0
            strategy = FundingHarvesterStrategy(
                client=client,
                risk_manager=risk_manager,
                fee_calculator=fee_calculator,
                dry_run=is_dry_run,
                telegram=telegram,
                min_entry_apy_pct=args.min_apy,
                allocation_per_position_usd=args.order_size_usd,
                auto_compound=args.auto_compound,
                min_open_interest_usd=args.min_oi_usd,
                persistence_checks_required=args.persistence_checks,
                max_entry_apy_pct=args.max_apy,
                trailing_exit_pct=args.trailing_exit,
            )
        elif args.strategy == "market_maker":
            interval = args.interval if args.interval is not None else 10.0
            strategy = AdaptiveMarketMakerStrategy(
                client=client,
                symbol=args.symbol,
                risk_manager=risk_manager,
                fee_calculator=fee_calculator,
                dry_run=is_dry_run,
                telegram=telegram,
                order_size_usd=args.order_size_usd,
                base_spread_bps=args.spread_bps,
            )
        else:
            logger.error(f"Strategia non valida: {args.strategy}")
            sys.exit(1)

        # Initialize Engine and Start
        engine = BotEngine(
            strategy=strategy,
            interval_seconds=interval,
            status_report_interval_seconds=args.report_interval,
            telegram=telegram,
        )
        engine.start()

    except ImportError as ie:
        logger.critical(
            f"❌ Dipendenza mancante: {ie}\n"
            f"Esegui prima l'installazione dei pacchetti con:\n"
            f"  pip install -r requirements.txt\n"
            f"Oppure (se usi l'ambiente virtuale):\n"
            f"  source .venv/bin/activate && pip install -r requirements.txt"
        )
        sys.exit(1)
    except Exception as e:
        logger.critical(f"❌ Errore critico all'avvio del bot: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
