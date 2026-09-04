"""Hyperliquid SDK Client wrapper."""

from typing import Any, Dict, Optional

try:
    from eth_account import Account
    from eth_account.signers.local import LocalAccount
    ETH_ACCOUNT_AVAILABLE = True
except ImportError:
    Account = None
    LocalAccount = Any
    ETH_ACCOUNT_AVAILABLE = False

try:
    from hyperliquid.exchange import Exchange
    from hyperliquid.info import Info
    from hyperliquid.utils import constants
    HYPERLIQUID_SDK_AVAILABLE = True
except ImportError:
    Exchange = Any
    Info = Any
    constants = None
    HYPERLIQUID_SDK_AVAILABLE = False

from .config import HyperliquidConfig
from .fees import FeeBreakdown, FeeCalculator


class HyperliquidClient:
    """Convenient wrapper for Hyperliquid Info and Exchange clients."""

    def __init__(self, config: Optional[HyperliquidConfig] = None):
        if not HYPERLIQUID_SDK_AVAILABLE:
            raise ImportError(
                "Hyperliquid SDK is not installed. Please run: pip install hyperliquid-python-sdk eth-account"
            )

        self.config = config or HyperliquidConfig.from_env()
        base_url = (
            constants.MAINNET_API_URL
            if self.config.is_mainnet
            else constants.TESTNET_API_URL
        )
        if self.config.custom_base_url:
            base_url = self.config.custom_base_url

        import time
        max_retries = 3
        for attempt in range(max_retries):
            try:
                self.info = Info(base_url=base_url, skip_ws=True)
                break
            except Exception as e:
                if attempt == max_retries - 1:
                    raise e
                time.sleep(2)

        self.fee_calculator = FeeCalculator()

        # Initialize wallet and Exchange client if secret_key is provided
        self.wallet: Optional[LocalAccount] = None
        self.exchange: Optional[Exchange] = None
        if self.config.secret_key:
            if not ETH_ACCOUNT_AVAILABLE:
                raise ImportError(
                    "eth-account is required when supplying secret_key. Run: pip install eth-account"
                )
            self.wallet = Account.from_key(self.config.secret_key)
            self.exchange = Exchange(
                self.wallet,
                base_url=base_url,
                account_address=self.config.account_address,
                vault_address=self.config.vault_address,
            )

    @property
    def account_address(self) -> Optional[str]:
        """Returns configured account address or wallet address."""
        if self.config.account_address:
            return self.config.account_address
        if self.wallet:
            return self.wallet.address
        return None

    def get_user_fees(self, user_address: Optional[str] = None) -> Dict[str, Any]:
        """Retrieve live fee structure and rate limit info for an address.

        Args:
            user_address: Wallet address to inspect (defaults to client's account).

        Returns:
            Dictionary containing user fee data.
        """
        target = user_address or self.account_address
        if not target:
            raise ValueError("An account address must be provided to query user fees.")
        return self.info.user_fees(target)

    def get_user_state(self, user_address: Optional[str] = None) -> Dict[str, Any]:
        """Retrieve live positions, margin summary, and balances for an address."""
        target = user_address or self.account_address
        if not target:
            raise ValueError("An account address must be provided to query user state.")
        return self.info.user_state(target)

    def get_market_meta(self) -> Dict[str, Any]:
        """Get universe metadata and asset contexts."""
        return self.info.meta()

    def get_all_mids(self) -> Dict[str, str]:
        """Get mid prices for all active markets."""
        return self.info.all_mids()

    def calculate_fee_for_account(
        self,
        size: float,
        price: float,
        is_maker: bool = False,
        is_spot: bool = False,
        user_address: Optional[str] = None,
        builder_fee_bps: float = 0.0,
    ) -> FeeBreakdown:
        """Calculate fees for a trade based on the user's actual live fee schedule.

        Queries the Hyperliquid API for current fee schedule and calculates the exact cost.
        """
        target = user_address or self.account_address
        custom_rate_bps: Optional[float] = None
        referral_discount = 0.0

        if target:
            try:
                fees_data = self.get_user_fees(target)
                # Hyperliquid API returns rates as decimals, e.g. 0.00035 = 3.5 bps
                if is_maker:
                    raw_rate = fees_data.get("userAddRate")
                else:
                    raw_rate = fees_data.get("userCrossRate")

                if raw_rate is not None:
                    custom_rate_bps = float(raw_rate) * 10_000.0

                active_ref = fees_data.get("activeReferralDiscount")
                if active_ref is not None:
                    referral_discount = float(active_ref)
            except Exception:
                # Fallback to default tier calculation if live query fails
                pass

        return self.fee_calculator.calculate_trade_fee(
            size=size,
            price=price,
            is_maker=is_maker,
            is_spot=is_spot,
            custom_fee_rate_bps=custom_rate_bps,
            referral_discount_pct=referral_discount,
            builder_fee_bps=builder_fee_bps,
        )

    def get_spot_perp_matches(self) -> Dict[str, Dict[str, Any]]:
        """Map tokens that have both an active Perpetual and a Spot market against USDC.

        Returns:
            Dict mapping coin symbol to spot pair metadata.
        """
        matches = {}
        try:
            spot_meta, _ = self.info.spot_meta_and_asset_ctxs()
            perp_meta = self.info.meta()
            perp_names = {a["name"] for a in perp_meta.get("universe", [])}

            tokens = spot_meta.get("tokens", [])
            token_by_idx = {t["index"]: t for t in tokens}

            for p in spot_meta.get("universe", []):
                t_idxs = p.get("tokens", [])
                # Quote token 0 is USDC on Hyperliquid L1
                if len(t_idxs) == 2 and t_idxs[1] == 0:
                    base_t = token_by_idx.get(t_idxs[0])
                    if base_t:
                        name = base_t.get("name")
                        if name and name in perp_names:
                            matches[name] = {
                                "coin": name,
                                "spot_pair_name": p.get("name"),
                                "spot_pair_index": p.get("index"),
                                "sz_decimals": base_t.get("szDecimals", 0),
                                "is_canonical": base_t.get("isCanonical", False),
                            }
        except Exception as e:
            pass
        return matches

    def order_market_open(
        self,
        name: str,
        is_buy: bool,
        size: float,
        slippage: float = 0.05,
    ) -> Any:
        """Place a market open order for either Spot or Perp on Hyperliquid."""
        if not self.exchange:
            raise ValueError("Exchange client is not initialized (secret_key missing).")
        return self.exchange.market_open(name=name, is_buy=is_buy, sz=size, slippage=slippage)

    def order_market_close(
        self,
        name: str,
        size: Optional[float] = None,
        is_spot: bool = False,
        slippage: float = 0.05,
    ) -> Any:
        """Close an active position (Spot sell or Perp buy/sell to cover)."""
        if not self.exchange:
            raise ValueError("Exchange client is not initialized (secret_key missing).")
        if is_spot:
            # Spot close = sell the held asset
            if size is None or size <= 0:
                raise ValueError("Size must be specified when closing a Spot position.")
            return self.exchange.market_open(name=name, is_buy=False, sz=size, slippage=slippage)
        else:
            return self.exchange.market_close(coin=name, sz=size, slippage=slippage)
