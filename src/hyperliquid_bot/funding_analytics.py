import time
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Any, Tuple

logger = logging.getLogger("hyperliquid_bot.funding_analytics")


def calculate_apy(hourly_rate: float) -> float:
    """
    Calculate APY from an hourly funding rate.
    """
    return hourly_rate * 24.0 * 365.0 * 100.0


@dataclass
class FundingTrend:
    """
    Dataclass containing funding rate trend analysis for a specific coin.
    """
    coin: str
    current_hourly_rate: float
    avg_1h: float
    avg_4h: float
    avg_8h: float
    avg_24h: float
    slope_4h: float
    trend: str
    confidence: float
    predicted_apy_4h: float
    samples_count: int


class FundingAnalytics:
    """
    Analyzes funding rate history to detect trends and predict future APY.
    Designed for delta-neutral strategies.
    """

    def __init__(self, client: Any, lookback_hours: int = 24, refresh_interval_seconds: float = 300.0) -> None:
        """
        Initialize the FundingAnalytics.
        """
        self.client = client
        self.lookback_hours = lookback_hours
        self.refresh_interval_seconds = refresh_interval_seconds
        
        # Cache per i trend delle singole monete, con TTL
        self._cache: Dict[str, Tuple[float, FundingTrend]] = {}

    def get_trend(self, coin: str) -> Optional[FundingTrend]:
        """
        Retrieve and compute the funding rate trend for a given coin.
        Uses a time-based cache to limit API calls.
        """
        now = time.time()
        
        # Controlla se i dati in cache sono ancora validi
        if coin in self._cache:
            cache_time, trend = self._cache[coin]
            if now - cache_time < self.refresh_interval_seconds:
                return trend
                
        try:
            start_time_ms = int((now - self.lookback_hours * 3600.0) * 1000)
            
            # Recupera la cronologia del funding dalla API (lista di dizionari)
            history: List[Dict[str, Any]] = self.client.info.funding_history(coin, start_time_ms)
            
            if not history:
                logger.warning(f"No funding history found for {coin}")
                return None
                
            # Ordina i risultati temporalmente, nel caso non lo fossero, e isola i tassi
            history.sort(key=lambda x: int(x.get("time", 0)))
            rates = [float(entry.get("fundingRate", 0.0)) for entry in history]
            
            samples_count = len(rates)
            if samples_count == 0:
                return None
                
            current_rate = rates[-1]
            avg_1h = current_rate
            
            # Calcolo delle medie per diverse finestre temporali
            avg_4h = sum(rates[-4:]) / len(rates[-4:]) if len(rates) >= 1 else 0.0
            avg_8h = sum(rates[-8:]) / len(rates[-8:]) if len(rates) >= 1 else 0.0
            avg_24h = sum(rates[-24:]) / len(rates[-24:]) if len(rates) >= 1 else 0.0
            
            # Calcolo della pendenza sui campioni piú recenti tramite regressione lineare semplice
            slope_4h = 0.0
            recent_rates = rates[-4:]
            n = len(recent_rates)
            
            if n > 1:
                indices = list(range(n))
                mean_i = sum(indices) / n
                mean_rate = sum(recent_rates) / n
                
                numerator = sum(i * r for i, r in zip(indices, recent_rates)) - (n * mean_i * mean_rate)
                denominator = sum(i * i for i in indices) - (n * mean_i * mean_i)
                
                if denominator != 0:
                    slope_4h = numerator / denominator
                    
            # Classificazione del trend
            trend_str = "STABLE"
            if slope_4h > 0.000001 and avg_4h > avg_8h:
                trend_str = "RISING"
            elif slope_4h < -0.000001 and avg_4h < avg_8h:
                trend_str = "FALLING"
                
            # Calcolo del livello di confidenza basato sulla coerenza della direzione
            confidence = 0.0
            if n > 1:
                agree_count = 0
                for i in range(1, n):
                    diff = recent_rates[i] - recent_rates[i-1]
                    if trend_str == "RISING" and diff > 0:
                        agree_count += 1
                    elif trend_str == "FALLING" and diff < 0:
                        agree_count += 1
                    elif trend_str == "STABLE" and abs(diff) <= 0.000001:
                        agree_count += 1
                confidence = agree_count / (n - 1)
            else:
                confidence = 1.0 if trend_str == "STABLE" else 0.0
                
            # Calcolo della previsione di APY
            predicted_rate = avg_4h + slope_4h * 2.0
            predicted_apy_4h = calculate_apy(predicted_rate)
            
            # Popola e memorizza il risultato
            trend = FundingTrend(
                coin=coin,
                current_hourly_rate=current_rate,
                avg_1h=avg_1h,
                avg_4h=avg_4h,
                avg_8h=avg_8h,
                avg_24h=avg_24h,
                slope_4h=slope_4h,
                trend=trend_str,
                confidence=confidence,
                predicted_apy_4h=predicted_apy_4h,
                samples_count=samples_count
            )
            
            self._cache[coin] = (now, trend)
            return trend
            
        except Exception as e:
            logger.error(f"Error fetching/calculating funding trend for {coin}: {e}")
            return None

    def get_all_trends(self, coins: List[str]) -> Dict[str, FundingTrend]:
        """
        Batch retrieve funding trends for multiple coins.
        """
        results: Dict[str, FundingTrend] = {}
        for coin in coins:
            trend = self.get_trend(coin)
            if trend is not None:
                results[coin] = trend
        return results

    def format_funding_report(self, coins: List[str], limit: int = 5) -> str:
        """
        Generate an HTML-formatted report for Telegram with current and projected APYs.
        """
        trends = self.get_all_trends(coins)
        if not trends:
            return "<b>Funding Report</b>\nNo data available."
            
        # Ordina dal tasso di funding corrente piu' alto al piu' basso
        sorted_trends = sorted(trends.values(), key=lambda t: t.current_hourly_rate, reverse=True)
        
        lines = ["<b>Funding Rate Report</b>\n"]
        for t in sorted_trends[:limit]:
            icon = "➡️"
            if t.trend == "RISING":
                icon = "📈"
            elif t.trend == "FALLING":
                icon = "📉"
                
            current_apy = calculate_apy(t.current_hourly_rate)
            
            line = f"<b>{t.coin}</b>: {icon} {t.trend} ({t.confidence*100:.0f}%)\n"
            line += f"  • Cur APY: {current_apy:.2f}%\n"
            line += f"  • Prd APY: {t.predicted_apy_4h:.2f}%"
            lines.append(line)
            
        return "\n".join(lines)
