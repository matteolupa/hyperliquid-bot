"""
Multi-exchange monitor module for comparing funding rates across Binance, Bybit, dYdX, and Hyperliquid.
"""

import json
import logging
import time
import urllib.parse
import urllib.request
import urllib.error
from dataclasses import dataclass
from typing import Dict, List, Optional, Any

logger = logging.getLogger("hyperliquid_bot.multi_exchange")


def calculate_apy(hourly_rate: float) -> float:
    """
    Calculate APY given an hourly funding rate.
    
    Args:
        hourly_rate: The hourly funding rate.
        
    Returns:
        The annualized percentage yield.
    """
    return abs(hourly_rate) * 24.0 * 365.0 * 100.0


@dataclass
class ExchangeSpread:
    """Data structure representing funding rates across multiple exchanges."""
    coin: str
    hl_hourly_rate: float
    hl_apy: float
    binance_hourly_rate: Optional[float] = None
    binance_apy: Optional[float] = None
    bybit_hourly_rate: Optional[float] = None
    bybit_apy: Optional[float] = None
    dydx_hourly_rate: Optional[float] = None
    dydx_apy: Optional[float] = None
    best_exchange: str = ""
    best_apy: float = 0.0
    hl_vs_best_spread_pct: float = 0.0


class MultiExchangeMonitor:
    """Monitors and compares funding rates across multiple exchanges."""
    
    BINANCE_URL = "https://fapi.binance.com/fapi/v1/premiumIndex"
    BYBIT_URL = "https://api.bybit.com/v5/market/tickers"
    DYDX_URL = "https://indexer.dydx.trade/v4/perpetualMarkets"
    
    SYMBOL_MAP = {
        "BTC": {"binance": "BTCUSDT", "bybit": "BTCUSDT", "dydx": "BTC-USD"},
        "ETH": {"binance": "ETHUSDT", "bybit": "ETHUSDT", "dydx": "ETH-USD"},
        "SOL": {"binance": "SOLUSDT", "bybit": "SOLUSDT", "dydx": "SOL-USD"},
        "DOGE": {"binance": "DOGEUSDT", "bybit": "DOGEUSDT", "dydx": "DOGE-USD"},
        "AVAX": {"binance": "AVAXUSDT", "bybit": "AVAXUSDT", "dydx": "AVAX-USD"},
        "LINK": {"binance": "LINKUSDT", "bybit": "LINKUSDT", "dydx": "LINK-USD"},
        "HYPE": {"binance": None, "bybit": "HYPEUSDT", "dydx": None},
        "TRUMP": {"binance": "TRUMPUSDT", "bybit": "TRUMPUSDT", "dydx": None},
        "PURR": {"binance": None, "bybit": None, "dydx": None},
        "MON": {"binance": None, "bybit": None, "dydx": None},
        "BERA": {"binance": "BERAUSDT", "bybit": "BERAUSDT", "dydx": None},
    }

    def __init__(self, timeout_seconds: float = 5.0, refresh_interval_seconds: float = 300.0):
        self.timeout_seconds = timeout_seconds
        self.refresh_interval_seconds = refresh_interval_seconds
        self._cache: Dict[str, Dict[str, float]] = {
            "binance": {},
            "bybit": {},
            "dydx": {}
        }
        self._last_refresh: Dict[str, float] = {
            "binance": 0.0,
            "bybit": 0.0,
            "dydx": 0.0
        }

    def _fetch_binance(self) -> Dict[str, float]:
        """Fetch funding rates from Binance and normalize to hourly."""
        if time.time() - self._last_refresh["binance"] < self.refresh_interval_seconds and self._cache["binance"]:
            return self._cache["binance"]
            
        rates = {}
        try:
            req = urllib.request.Request(self.BINANCE_URL, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as response:
                data = json.loads(response.read().decode('utf-8'))
                for item in data:
                    if "symbol" in item and "lastFundingRate" in item:
                        symbol = item["symbol"]
                        # Binance rates are per 8h cycle
                        try:
                            hourly_rate = float(item["lastFundingRate"]) / 8.0
                            rates[symbol] = hourly_rate
                        except (ValueError, TypeError):
                            continue
            self._cache["binance"] = rates
            self._last_refresh["binance"] = time.time()
            logger.info("Binance rates fetched successfully")
        except Exception as e:
            logger.error(f"Errore durante il fetch da Binance: {e}")
        return rates

    def _fetch_bybit(self) -> Dict[str, float]:
        """Fetch funding rates from Bybit and normalize to hourly."""
        if time.time() - self._last_refresh["bybit"] < self.refresh_interval_seconds and self._cache["bybit"]:
            return self._cache["bybit"]
            
        rates = {}
        try:
            url = f"{self.BYBIT_URL}?category=linear"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as response:
                data = json.loads(response.read().decode('utf-8'))
                if "result" in data and "list" in data["result"]:
                    for item in data["result"]["list"]:
                        symbol = item.get("symbol")
                        funding_rate = item.get("fundingRate")
                        funding_interval = item.get("fundingInterval")
                        
                        if symbol and funding_rate and funding_interval:
                            try:
                                # Normalize bybit rates to hourly
                                hourly_rate = float(funding_rate) / (float(funding_interval) / 60.0)
                                rates[symbol] = hourly_rate
                            except (ValueError, TypeError, ZeroDivisionError):
                                continue
            self._cache["bybit"] = rates
            self._last_refresh["bybit"] = time.time()
            logger.info("Bybit rates fetched successfully")
        except Exception as e:
            logger.error(f"Errore durante il fetch da Bybit: {e}")
        return rates

    def _fetch_dydx(self) -> Dict[str, float]:
        """Fetch funding rates from dYdX (already hourly)."""
        if time.time() - self._last_refresh["dydx"] < self.refresh_interval_seconds and self._cache["dydx"]:
            return self._cache["dydx"]
            
        rates = {}
        try:
            req = urllib.request.Request(self.DYDX_URL, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as response:
                data = json.loads(response.read().decode('utf-8'))
                if "markets" in data:
                    for ticker, market_data in data["markets"].items():
                        if "nextFundingRate" in market_data:
                            try:
                                rates[ticker] = float(market_data["nextFundingRate"])
                            except (ValueError, TypeError):
                                continue
            self._cache["dydx"] = rates
            self._last_refresh["dydx"] = time.time()
            logger.info("dYdX rates fetched successfully")
        except Exception as e:
            logger.error(f"Errore durante il fetch da dYdX: {e}")
        return rates

    def fetch_spreads(self, coins: List[str], hl_rates: Dict[str, float]) -> Dict[str, ExchangeSpread]:
        """
        Fetch spreads for a list of coins using HL rates as base.
        
        Args:
            coins: List of Hyperliquid coin names (e.g. ['BTC', 'ETH'])
            hl_rates: Dictionary mapping HL coin names to their hourly funding rate
            
        Returns:
            Dictionary mapping coin names to ExchangeSpread objects
        """
        binance_rates = self._fetch_binance()
        bybit_rates = self._fetch_bybit()
        dydx_rates = self._fetch_dydx()
        
        spreads = {}
        
        for coin in coins:
            if coin not in hl_rates:
                continue
                
            hl_rate = hl_rates[coin]
            hl_apy = calculate_apy(hl_rate)
            
            spread = ExchangeSpread(
                coin=coin,
                hl_hourly_rate=hl_rate,
                hl_apy=hl_apy,
                best_exchange="Hyperliquid",
                best_apy=hl_apy
            )
            
            # Map symbols
            symbols = self.SYMBOL_MAP.get(coin, {})
            
            # Binance
            binance_sym = symbols.get("binance")
            if binance_sym and binance_sym in binance_rates:
                spread.binance_hourly_rate = binance_rates[binance_sym]
                spread.binance_apy = calculate_apy(spread.binance_hourly_rate)
                if spread.binance_apy > spread.best_apy:
                    spread.best_apy = spread.binance_apy
                    spread.best_exchange = "Binance"
                    
            # Bybit
            bybit_sym = symbols.get("bybit")
            if bybit_sym and bybit_sym in bybit_rates:
                spread.bybit_hourly_rate = bybit_rates[bybit_sym]
                spread.bybit_apy = calculate_apy(spread.bybit_hourly_rate)
                if spread.bybit_apy > spread.best_apy:
                    spread.best_apy = spread.bybit_apy
                    spread.best_exchange = "Bybit"
                    
            # dYdX
            dydx_sym = symbols.get("dydx")
            if dydx_sym and dydx_sym in dydx_rates:
                spread.dydx_hourly_rate = dydx_rates[dydx_sym]
                spread.dydx_apy = calculate_apy(spread.dydx_hourly_rate)
                if spread.dydx_apy > spread.best_apy:
                    spread.best_apy = spread.dydx_apy
                    spread.best_exchange = "dYdX"
                    
            # Calculate spread pct
            if spread.best_apy > 0:
                spread.hl_vs_best_spread_pct = hl_apy - spread.best_apy
            else:
                spread.hl_vs_best_spread_pct = 0.0
            
            spreads[coin] = spread
            
        return spreads

    def format_spread_report(self, spreads: Dict[str, ExchangeSpread], limit: int = 5) -> str:
        """
        Format the spread comparison into an HTML report for Telegram.
        
        Args:
            spreads: Dictionary of spreads.
            limit: Maximum number of coins to include.
            
        Returns:
            HTML formatted string report.
        """
        if not spreads:
            return "<b>Nessun dato di spread disponibile</b>"
            
        # Ordiniamo per APY su Hyperliquid (decrescente)
        sorted_coins = sorted(spreads.keys(), key=lambda c: spreads[c].hl_apy, reverse=True)[:limit]
        
        report = "<b>📊 Multi-Exchange Funding Spread</b>\n\n"
        
        for coin in sorted_coins:
            spread = spreads[coin]
            
            if spread.hl_vs_best_spread_pct >= 0:
                emoji = "🟢" # HL pays more or equal
            elif spread.hl_vs_best_spread_pct > -5.0:
                emoji = "➡️" # Similar (within 5%)
            else:
                emoji = "🔴" # HL pays significantly less
                
            report += f"{emoji} <b>{coin}</b>\n"
            report += f"  • HL: {spread.hl_apy:.2f}% APY ({spread.hl_hourly_rate*100:.4f}%/h)\n"
            
            if spread.binance_apy is not None:
                report += f"  • Binance: {spread.binance_apy:.2f}% APY\n"
            if spread.bybit_apy is not None:
                report += f"  • Bybit: {spread.bybit_apy:.2f}% APY\n"
            if spread.dydx_apy is not None:
                report += f"  • dYdX: {spread.dydx_apy:.2f}% APY\n"
                
            report += f"  🏆 Best: {spread.best_exchange} ({spread.best_apy:.2f}%)\n\n"
            
        return report
