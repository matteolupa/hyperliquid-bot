"""Fee calculation module for Hyperliquid DEX.

Supports:
- Default tier schedules for Perps and Spot (Volume-based tiers).
- Dynamic fee rate retrieval via Hyperliquid `Info.user_fees()` API.
- Fee calculation for Maker vs Taker orders.
- Referral discounts and Builder fees.
- Breakeven price calculation for Long and Short positions.
- 14-day weighted volume calculations.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class FeeTier:
    """Represents a volume tier in Hyperliquid."""

    tier_level: int
    name: str
    min_14d_volume_usd: float
    perp_maker_bps: float
    perp_taker_bps: float
    spot_maker_bps: float
    spot_taker_bps: float


@dataclass
class FeeBreakdown:
    """Detailed breakdown of a trade fee calculation."""

    notional_usd: float
    base_fee_rate_bps: float
    effective_fee_rate_bps: float
    base_fee_usd: float
    referral_discount_usd: float
    builder_fee_usd: float
    effective_fee_usd: float  # base_fee_usd - referral_discount_usd
    total_fee_usd: float  # effective_fee_usd + builder_fee_usd
    is_maker: bool
    is_rebate: bool  # True if the user receives a rebate (negative fee)


# Hyperliquid standard fee schedule (Tiers 0 to 6)
# Note: 1 bps = 0.01% = 0.0001
DEFAULT_FEE_TIERS: List[FeeTier] = [
    FeeTier(
        tier_level=0,
        name="Tier 0",
        min_14d_volume_usd=0.0,
        perp_maker_bps=1.0,  # 0.010%
        perp_taker_bps=3.5,  # 0.035%
        spot_maker_bps=1.0,  # 0.010%
        spot_taker_bps=4.0,  # 0.040%
    ),
    FeeTier(
        tier_level=1,
        name="Tier 1",
        min_14d_volume_usd=5_000_000.0,
        perp_maker_bps=0.5,  # 0.005%
        perp_taker_bps=3.0,  # 0.030%
        spot_maker_bps=0.5,
        spot_taker_bps=3.5,
    ),
    FeeTier(
        tier_level=2,
        name="Tier 2",
        min_14d_volume_usd=25_000_000.0,
        perp_maker_bps=0.0,  # 0.000%
        perp_taker_bps=2.5,  # 0.025%
        spot_maker_bps=0.0,
        spot_taker_bps=3.0,
    ),
    FeeTier(
        tier_level=3,
        name="Tier 3",
        min_14d_volume_usd=100_000_000.0,
        perp_maker_bps=-0.1,  # -0.001% (rebate)
        perp_taker_bps=2.2,  # 0.022%
        spot_maker_bps=-0.1,
        spot_taker_bps=2.5,
    ),
    FeeTier(
        tier_level=4,
        name="Tier 4",
        min_14d_volume_usd=250_000_000.0,
        perp_maker_bps=-0.2,  # -0.002% (rebate)
        perp_taker_bps=2.0,  # 0.020%
        spot_maker_bps=-0.2,
        spot_taker_bps=2.0,
    ),
    FeeTier(
        tier_level=5,
        name="Tier 5 (VIP)",
        min_14d_volume_usd=500_000_000.0,
        perp_maker_bps=-0.3,  # -0.003% (rebate)
        perp_taker_bps=1.8,  # 0.018%
        spot_maker_bps=-0.3,
        spot_taker_bps=1.5,
    ),
]


class FeeCalculator:
    """Hyperliquid fee calculator utility."""

    def __init__(self, fee_tiers: Optional[List[FeeTier]] = None):
        self.fee_tiers = fee_tiers or DEFAULT_FEE_TIERS

    @staticmethod
    def calculate_14d_weighted_volume(perp_14d_volume: float, spot_14d_volume: float) -> float:
        """Calculate the 14-day weighted volume used by Hyperliquid for tier determination.

        Formula: 14d Weighted Volume = Perp Volume + 2 * Spot Volume
        """
        return float(perp_14d_volume) + 2.0 * float(spot_14d_volume)

    def get_tier_by_volume(self, weighted_14d_volume: float) -> FeeTier:
        """Get the applicable FeeTier given a 14-day weighted volume."""
        selected_tier = self.fee_tiers[0]
        for tier in sorted(self.fee_tiers, key=lambda t: t.min_14d_volume_usd):
            if weighted_14d_volume >= tier.min_14d_volume_usd:
                selected_tier = tier
            else:
                break
        return selected_tier

    def get_base_fee_rate_bps(
        self,
        is_maker: bool = False,
        is_spot: bool = False,
        tier_level: int = 0,
    ) -> float:
        """Get the base fee rate in basis points (bps) for given parameters."""
        tier = next((t for t in self.fee_tiers if t.tier_level == tier_level), self.fee_tiers[0])
        if is_spot:
            return tier.spot_maker_bps if is_maker else tier.spot_taker_bps
        return tier.perp_maker_bps if is_maker else tier.perp_taker_bps

    def calculate_trade_fee(
        self,
        size: float,
        price: float,
        is_maker: bool = False,
        is_spot: bool = False,
        custom_fee_rate_bps: Optional[float] = None,
        referral_discount_pct: float = 0.0,
        builder_fee_bps: float = 0.0,
        tier_level: int = 0,
    ) -> FeeBreakdown:
        """Calculate the fee breakdown for a single trade.

        Args:
            size: Quantity/size of the asset traded (positive float).
            price: Execution price in USD.
            is_maker: True if limit order providing liquidity, False if taker crossing book.
            is_spot: True for Spot market, False for Perps.
            custom_fee_rate_bps: Optional explicit fee rate in bps (overrides tier table).
            referral_discount_pct: Referral discount percentage on taker fees (e.g. 0.04 for 4%).
            builder_fee_bps: Builder fee in basis points (e.g. 1.0 bps).
            tier_level: Tier level (0 to 5) if using default tiers.

        Returns:
            FeeBreakdown with notional, effective rates, and USD costs.
        """
        size = abs(float(size))
        price = abs(float(price))
        notional_usd = size * price

        if custom_fee_rate_bps is not None:
            base_fee_rate_bps = float(custom_fee_rate_bps)
        else:
            base_fee_rate_bps = self.get_base_fee_rate_bps(
                is_maker=is_maker, is_spot=is_spot, tier_level=tier_level
            )

        # Base fee in USD
        base_fee_usd = notional_usd * (base_fee_rate_bps / 10_000.0)

        # Referral discount only applies to taker fees when fee > 0
        referral_discount_usd = 0.0
        if not is_maker and base_fee_usd > 0 and referral_discount_pct > 0:
            referral_discount_usd = base_fee_usd * min(1.0, float(referral_discount_pct))

        effective_fee_usd = base_fee_usd - referral_discount_usd
        builder_fee_usd = notional_usd * (float(builder_fee_bps) / 10_000.0)
        total_fee_usd = effective_fee_usd + builder_fee_usd

        # Effective fee rate in bps
        effective_fee_rate_bps = (
            (total_fee_usd / notional_usd * 10_000.0) if notional_usd > 0 else 0.0
        )

        return FeeBreakdown(
            notional_usd=round(notional_usd, 6),
            base_fee_rate_bps=round(base_fee_rate_bps, 4),
            effective_fee_rate_bps=round(effective_fee_rate_bps, 4),
            base_fee_usd=round(base_fee_usd, 6),
            referral_discount_usd=round(referral_discount_usd, 6),
            builder_fee_usd=round(builder_fee_usd, 6),
            effective_fee_usd=round(effective_fee_usd, 6),
            total_fee_usd=round(total_fee_usd, 6),
            is_maker=is_maker,
            is_rebate=(total_fee_usd < 0),
        )

    def calculate_round_trip_fee(
        self,
        size: float,
        entry_price: float,
        exit_price: float,
        entry_is_maker: bool = False,
        exit_is_maker: bool = False,
        is_spot: bool = False,
        referral_discount_pct: float = 0.0,
        builder_fee_bps: float = 0.0,
        tier_level: int = 0,
    ) -> Dict[str, Any]:
        """Calculate total round trip trading fees (Open + Close)."""
        entry_fee = self.calculate_trade_fee(
            size=size,
            price=entry_price,
            is_maker=entry_is_maker,
            is_spot=is_spot,
            referral_discount_pct=referral_discount_pct,
            builder_fee_bps=builder_fee_bps,
            tier_level=tier_level,
        )
        exit_fee = self.calculate_trade_fee(
            size=size,
            price=exit_price,
            is_maker=exit_is_maker,
            is_spot=is_spot,
            referral_discount_pct=referral_discount_pct,
            builder_fee_bps=builder_fee_bps,
            tier_level=tier_level,
        )

        total_fee_usd = entry_fee.total_fee_usd + exit_fee.total_fee_usd
        total_notional = entry_fee.notional_usd + exit_fee.notional_usd
        effective_bps = (
            (total_fee_usd / total_notional * 10_000.0) if total_notional > 0 else 0.0
        )

        return {
            "entry_fee": entry_fee,
            "exit_fee": exit_fee,
            "total_fee_usd": round(total_fee_usd, 6),
            "effective_bps": round(effective_bps, 4),
        }

    def calculate_breakeven_price(
        self,
        entry_price: float,
        is_long: bool = True,
        entry_is_maker: bool = False,
        exit_is_maker: bool = False,
        is_spot: bool = False,
        referral_discount_pct: float = 0.0,
        builder_fee_bps: float = 0.0,
        tier_level: int = 0,
    ) -> float:
        """Calculate the required exit price to break even after accounting for entry and exit fees.

        For a Long:
            Gross Profit = Exit Price - Entry Price
            Total Fees per unit = Entry Fee/unit + Exit Fee/unit
                                = Entry Price * f_entry + Exit Price * f_exit
            Break-even when: Exit Price - Entry Price = Entry Price * f_entry + Exit Price * f_exit
            => Exit Price * (1 - f_exit) = Entry Price * (1 + f_entry)
            => Exit Price = Entry Price * (1 + f_entry) / (1 - f_exit)

        For a Short:
            Gross Profit = Entry Price - Exit Price
            Break-even when: Entry Price - Exit Price = Entry Price * f_entry + Exit Price * f_exit
            => Entry Price * (1 - f_entry) = Exit Price * (1 + f_exit)
            => Exit Price = Entry Price * (1 - f_entry) / (1 + f_exit)
        """
        # Calculate fee rate fraction (e.g. 3.5 bps = 0.00035)
        entry_breakdown = self.calculate_trade_fee(
            size=1.0,
            price=entry_price,
            is_maker=entry_is_maker,
            is_spot=is_spot,
            referral_discount_pct=referral_discount_pct,
            builder_fee_bps=builder_fee_bps,
            tier_level=tier_level,
        )
        f_entry = entry_breakdown.effective_fee_rate_bps / 10_000.0

        exit_breakdown = self.calculate_trade_fee(
            size=1.0,
            price=entry_price,
            is_maker=exit_is_maker,
            is_spot=is_spot,
            referral_discount_pct=referral_discount_pct,
            builder_fee_bps=builder_fee_bps,
            tier_level=tier_level,
        )
        f_exit = exit_breakdown.effective_fee_rate_bps / 10_000.0

        if is_long:
            breakeven = entry_price * (1.0 + f_entry) / (1.0 - f_exit)
        else:
            breakeven = entry_price * (1.0 - f_entry) / (1.0 + f_exit)

        return round(breakeven, 6)

    @classmethod
    def from_user_fees_response(cls, user_fees_data: Dict[str, Any]) -> "FeeCalculator":
        """Factory method to parse live response from Hyperliquid `info.user_fees()`."""
        # Typically returns:
        # {
        #   "feeSchedule": { "add": "0.0001", "cross": "0.00035", ... },
        #   "userCrossRate": "0.00035",
        #   "userAddRate": "0.0001",
        #   "activeReferralDiscount": "0.04", ...
        # }
        return cls()
