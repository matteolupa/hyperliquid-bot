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
from .ledger import FundingLedger
from .telegram import TelegramNotifier
from .funding_analytics import FundingAnalytics, FundingTrend
from .multi_exchange import MultiExchangeMonitor, ExchangeSpread
from .basis_monitor import BasisMonitor, BasisData
from .performance import PerformanceTracker

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
    "FundingLedger",
    "FundingAnalytics",
    "FundingTrend",
    "MultiExchangeMonitor",
    "ExchangeSpread",
    "BasisMonitor",
    "BasisData",
    "PerformanceTracker",
]

__version__ = "0.1.0"
