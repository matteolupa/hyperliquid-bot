"""Risk management and safety controls for Hyperliquid Bot."""

from dataclasses import dataclass, field
import logging
from typing import Dict, Optional

logger = logging.getLogger("hyperliquid_bot.risk")


@dataclass
class RiskLimits:
    """Configurable risk thresholds."""

    max_position_size_usd: float = 10_000.0  # Max USD per individual asset
    max_total_notional_usd: float = 50_000.0  # Max total exposure across all positions
    max_drawdown_pct: float = 0.05  # Circuit breaker triggers at 5% drawdown
    max_leverage: float = 5.0  # Max leverage allowed
    max_slippage_pct: float = 0.005  # Max 0.5% slippage on market orders
    min_order_size_usd: float = 10.0  # Minimum order size to avoid dust orders


class RiskManager:
    """Enforces risk rules, position limits, and emergency circuit breakers."""

    def __init__(self, limits: Optional[RiskLimits] = None, initial_equity: Optional[float] = None):
        self.limits = limits or RiskLimits()
        self.initial_equity = initial_equity
        self.peak_equity = initial_equity or 0.0
        self.is_circuit_breaker_tripped = False
        self.circuit_breaker_reason: Optional[str] = None

    def update_equity(self, current_equity: float) -> bool:
        """Update equity tracking and evaluate drawdown circuit breaker.

        Returns True if circuit breaker is tripped, False otherwise.
        """
        if current_equity <= 0:
            return False

        if self.initial_equity is None:
            self.initial_equity = current_equity
            self.peak_equity = current_equity

        if current_equity > self.peak_equity:
            self.peak_equity = current_equity

        # Calculate drawdown from peak
        drawdown = (self.peak_equity - current_equity) / self.peak_equity
        if drawdown >= self.limits.max_drawdown_pct:
            self.is_circuit_breaker_tripped = True
            self.circuit_breaker_reason = (
                f"Max drawdown exceeded! Current DD: {drawdown * 100:.2f}% "
                f"(Peak: ${self.peak_equity:,.2f}, Current: ${current_equity:,.2f})"
            )
            logger.critical(f"🚨 [CIRCUIT BREAKER] {self.circuit_breaker_reason}")
            return True

        return False

    def validate_order(
        self,
        symbol: str,
        size: float,
        price: float,
        current_position_usd: float = 0.0,
        total_portfolio_notional_usd: float = 0.0,
    ) -> bool:
        """Validate if an order complies with risk constraints."""
        if self.is_circuit_breaker_tripped:
            logger.warning(
                f"Order rejected for {symbol}: Circuit breaker active ({self.circuit_breaker_reason})"
            )
            return False

        order_notional_usd = abs(size * price)

        # 1. Minimum order check
        if order_notional_usd < self.limits.min_order_size_usd:
            logger.warning(
                f"Order rejected for {symbol}: Notional ${order_notional_usd:.2f} below min ${self.limits.min_order_size_usd:.2f}"
            )
            return False

        # 2. Max position size per asset
        projected_asset_notional = abs(current_position_usd) + order_notional_usd
        if projected_asset_notional > self.limits.max_position_size_usd:
            logger.warning(
                f"Order rejected for {symbol}: Projected position ${projected_asset_notional:.2f} "
                f"exceeds limit ${self.limits.max_position_size_usd:.2f}"
            )
            return False

        # 3. Max total portfolio notional
        projected_total_notional = total_portfolio_notional_usd + order_notional_usd
        if projected_total_notional > self.limits.max_total_notional_usd:
            logger.warning(
                f"Order rejected for {symbol}: Projected total portfolio ${projected_total_notional:.2f} "
                f"exceeds limit ${self.limits.max_total_notional_usd:.2f}"
            )
            return False

        return True
