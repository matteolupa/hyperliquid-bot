"""Demonstration script for Hyperliquid SDK and Fee Calculator."""

import os
from hyperliquid_bot import FeeCalculator, HyperliquidClient, HyperliquidConfig


def demo_offline_fee_calculations():
    print("=" * 60)
    print(" 1. CALCOLO FEES OFFLINE (SIMULAZIONE)")
    print("=" * 60)

    calc = FeeCalculator()

    # Scenario 1: Taker Perp Order (e.g. 0.5 BTC a $60,000)
    btc_size = 0.5
    btc_price = 60_000.0
    fee_perp_taker = calc.calculate_trade_fee(
        size=btc_size,
        price=btc_price,
        is_maker=False,
        is_spot=False,
        tier_level=0,
    )
    print(f"\n[Perp Taker - Tier 0]")
    print(f"  Nozionale:             ${fee_perp_taker.notional_usd:,.2f}")
    print(f"  Aliquota base:         {fee_perp_taker.base_fee_rate_bps} bps ({fee_perp_taker.base_fee_rate_bps / 100:.3f}%)")
    print(f"  Fee stimata:           ${fee_perp_taker.total_fee_usd:.4f}")

    # Scenario 2: Maker Perp Order con Rebate (Tier 3, 100M+ volume)
    fee_perp_maker_tier3 = calc.calculate_trade_fee(
        size=btc_size,
        price=btc_price,
        is_maker=True,
        is_spot=False,
        tier_level=3,
    )
    print(f"\n[Perp Maker con Rebate - Tier 3]")
    print(f"  Nozionale:             ${fee_perp_maker_tier3.notional_usd:,.2f}")
    print(f"  Aliquota:              {fee_perp_maker_tier3.effective_fee_rate_bps} bps")
    print(f"  Rebate guadagnato:     ${abs(fee_perp_maker_tier3.total_fee_usd):.4f} (è un accredito: {fee_perp_maker_tier3.is_rebate})")

    # Scenario 3: Taker con Sconto Referral (4%) e Builder Fee (1 bps)
    fee_ref = calc.calculate_trade_fee(
        size=10.0,
        price=3000.0,  # 10 ETH @ $3000 = $30,000
        is_maker=False,
        is_spot=False,
        referral_discount_pct=0.04,
        builder_fee_bps=1.0,
        tier_level=0,
    )
    print(f"\n[Perp Taker con Sconto Referral 4% + Builder Fee 1 bps]")
    print(f"  Nozionale:             ${fee_ref.notional_usd:,.2f}")
    print(f"  Base Fee:              ${fee_ref.base_fee_usd:.4f}")
    print(f"  Sconto Referral:       -${fee_ref.referral_discount_usd:.4f}")
    print(f"  Builder Fee:           +${fee_ref.builder_fee_usd:.4f}")
    print(f"  Totale Fee:            ${fee_ref.total_fee_usd:.4f} ({fee_ref.effective_fee_rate_bps:.2f} bps effettivi)")


def demo_breakeven_and_round_trip():
    print("\n" + "=" * 60)
    print(" 2. CALCOLO ROUND-TRIP E PREZZO DI BREAK-EVEN")
    print("=" * 60)

    calc = FeeCalculator()

    # Esempio Long su ETH: Entry Taker @ $3,000, Exit Maker
    entry_price = 3000.0
    be_long = calc.calculate_breakeven_price(
        entry_price=entry_price,
        is_long=True,
        entry_is_maker=False,
        exit_is_maker=True,
        tier_level=0,
    )
    print(f"\n[Posizione LONG su ETH]")
    print(f"  Prezzo di ingresso:    ${entry_price:,.2f} (Taker)")
    print(f"  Prezzo di Break-Even:  ${be_long:,.2f} (Exit Maker)")
    print(f"  Delta minimo richiesto: +${be_long - entry_price:.4f} (+{((be_long - entry_price) / entry_price) * 100:.4f}%)")

    # Esempio Short su BTC: Entry Taker @ $65,000, Exit Taker
    btc_entry = 65000.0
    be_short = calc.calculate_breakeven_price(
        entry_price=btc_entry,
        is_long=False,
        entry_is_maker=False,
        exit_is_maker=False,
        tier_level=0,
    )
    print(f"\n[Posizione SHORT su BTC]")
    print(f"  Prezzo di ingresso:    ${btc_entry:,.2f} (Taker)")
    print(f"  Prezzo di Break-Even:  ${be_short:,.2f} (Exit Taker)")
    print(f"  Delta minimo richiesto: -${btc_entry - be_short:.4f} (-{((btc_entry - be_short) / btc_entry) * 100:.4f}%)")


def demo_tier_volume():
    print("\n" + "=" * 60)
    print(" 3. DETERMINAZIONE TIER DA VOLUME PONDERATO 14 GIORNI")
    print("=" * 60)

    calc = FeeCalculator()
    perp_vol = 15_000_000.0  # $15M
    spot_vol = 6_000_000.0   # $6M -> conta doppio: 2 * 6M = $12M
    weighted_vol = calc.calculate_14d_weighted_volume(perp_vol, spot_vol)
    tier = calc.get_tier_by_volume(weighted_vol)

    print(f"  Volume Perp (14d):     ${perp_vol:,.2f}")
    print(f"  Volume Spot (14d):     ${spot_vol:,.2f}")
    print(f"  Volume Ponderato:      ${weighted_vol:,.2f} (Perp + 2 * Spot)")
    print(f"  Tier Assegnato:        {tier.name} (Minimo richiesto: ${tier.min_14d_volume_usd:,.0f})")
    print(f"  Perp Fees: Maker={tier.perp_maker_bps} bps | Taker={tier.perp_taker_bps} bps")


def demo_live_sdk_connection():
    print("\n" + "=" * 60)
    print(" 4. CONNESSIONE LIVE SDK (TESTNET / MAINNET)")
    print("=" * 60)

    try:
        config = HyperliquidConfig.from_env()
        client = HyperliquidClient(config)
        print(f"  Network attiva: {config.network} ({config.base_url})")

        mids = client.get_all_mids()
        sample_symbols = ["BTC", "ETH", "SOL", "PURR"]
        print(f"  Prezzi medi di mercato correnti:")
        for sym in sample_symbols:
            if sym in mids:
                print(f"    - {sym}: ${float(mids[sym]):,.2f}")

        # Se è configurato un wallet o account_address, interroga le fee live
        if config.account_address:
            print(f"\n  Recupero tariffe live per account: {config.account_address}")
            user_fees = client.get_user_fees()
            print(f"  Dati Fee Account: {user_fees}")
        else:
            print("\n  [Nota] Imposta ACCOUNT_ADDRESS nel file .env per visualizzare le tariffe live dell'account.")
    except ImportError as ie:
        print(f"  [Info SDK non installato] {ie}")
    except Exception as e:
        print(f"  [Info] Query live non riuscita (es. offline): {e}")


if __name__ == "__main__":
    demo_offline_fee_calculations()
    demo_breakeven_and_round_trip()
    demo_tier_volume()
    demo_live_sdk_connection()
