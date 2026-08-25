"""Hyperliquid Python SDK, Trading Bot & Fee Calculator."""

from .client import HyperliquidClient
from .config import HyperliquidConfig
from .engine import BotEngine, setup_logger
from .fees import (
    DEFAULT_FEE_TIERS,
    FeeBreakdown,
    FeeCalculator,
    FeeTier,
)
from .risk import RiskLimits, RiskManager
from .strategies import (
    AdaptiveMarketMakerStrategy,
    BaseStrategy,
    FundingHarvesterStrategy,
    FundingOpportunity,
    MarketMakingQuotes,
    ScalperStrategy,
    ScalperTrade,
)
from .telegram import TelegramNotifier

__all__ = [
    "HyperliquidClient",
    "HyperliquidConfig",
    "FeeCalculator",
    "FeeTier",
    "FeeBreakdown",
    "DEFAULT_FEE_TIERS",
    "RiskManager",
    "RiskLimits",
    "BaseStrategy",
    "FundingHarvesterStrategy",
    "FundingOpportunity",
    "AdaptiveMarketMakerStrategy",
    "MarketMakingQuotes",
    "ScalperStrategy",
    "ScalperTrade",
    "BotEngine",
    "setup_logger",
    "TelegramNotifier",
]

__version__ = "0.1.0"
