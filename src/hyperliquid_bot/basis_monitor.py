import logging
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Any

logger = logging.getLogger("hyperliquid_bot.basis_monitor")

@dataclass
class BasisData:
    """
    Data structure representing the basis (price difference) between Spot and Perpetual markets.
    """
    coin: str
    spot_mid_price: float
    perp_mark_price: float
    basis_bps: float
    basis_pct: float
    basis_direction: str
    annualized_basis_apy: float


class BasisMonitor:
    """
    Monitors the price difference (basis) between Spot and Perpetual markets on Hyperliquid
    to identify extra yield from price convergence.
    """

    def __init__(self, client: Any, refresh_interval_seconds: float = 60.0):
        """
        Initializes the BasisMonitor.

        Args:
            client: Duck-typed Hyperliquid client with info endpoints.
            refresh_interval_seconds: Cache TTL in seconds.
        """
        self.client = client
        self.refresh_interval_seconds = refresh_interval_seconds
        
        # Cache interno per evitare di chiamare le API troppo spesso
        self._cache: Dict[str, BasisData] = {}
        self._last_update: float = 0.0

    def _fetch_spot_prices(self) -> Dict[str, float]:
        """
        Fetches and maps Spot mid prices for USDC pairs.
        
        Returns:
            Dict mapping base coin symbol to its spot mid price.
        """
        try:
            # Otteniamo i dati spot
            spot_meta, spot_asset_ctxs = self.client.info.spot_meta_and_asset_ctxs()
            
            spot_prices: Dict[str, float] = {}
            tokens = spot_meta.get("tokens", [])
            universe = spot_meta.get("universe", [])
            
            # Costruiamo mappa indicizzata per campo 'index' del token
            token_by_idx = {t["index"]: t for t in tokens if "index" in t}
            
            for i, pair in enumerate(universe):
                pair_tokens = pair.get("tokens", [])
                # Quote token 0 = USDC su Hyperliquid L1
                if len(pair_tokens) >= 2 and pair_tokens[1] == 0:
                    base_t = token_by_idx.get(pair_tokens[0])
                    if not base_t:
                        continue
                    base_token_name = base_t.get("name", "")
                    
                    if i < len(spot_asset_ctxs) and base_token_name:
                        ctx = spot_asset_ctxs[i]
                        # Alcuni formati potrebbero avere midPx o markPx
                        price_str = ctx.get("midPx") or ctx.get("markPx")
                        if price_str:
                            spot_prices[base_token_name] = float(price_str)
                            
            return spot_prices
        except Exception as e:
            logger.error(f"Errore durante il recupero dei prezzi spot: {e}")
            return {}

    def _fetch_perp_prices(self) -> Dict[str, float]:
        """
        Fetches and maps Perpetual mark prices.
        
        Returns:
            Dict mapping coin symbol to its perpetual mark price.
        """
        try:
            # Otteniamo i dati perp
            meta, asset_ctxs = self.client.info.meta_and_asset_ctxs()
            
            perp_prices: Dict[str, float] = {}
            universe = meta.get("universe", [])
            
            for i, coin_info in enumerate(universe):
                coin_name = coin_info.get("name", "")
                if i < len(asset_ctxs) and coin_name:
                    ctx = asset_ctxs[i]
                    price_str = ctx.get("markPx")
                    if price_str:
                        perp_prices[coin_name] = float(price_str)
                        
            return perp_prices
        except Exception as e:
            logger.error(f"Errore durante il recupero dei prezzi perp: {e}")
            return {}

    def get_basis(self, coins: List[str]) -> Dict[str, BasisData]:
        """
        Calculates the basis for a list of coins. Uses cache if available and fresh.

        Args:
            coins: List of coin symbols to calculate basis for.

        Returns:
            Dictionary mapping coin symbol to its BasisData.
        """
        current_time = time.time()
        
        # Se la cache è scaduta, aggiorniamo i dati
        if current_time - self._last_update > self.refresh_interval_seconds or not self._cache:
            self._cache.clear()
            
            # 1. Metodo primario live: all_mids + get_spot_perp_matches (estremamente preciso e veloce)
            used_all_mids = False
            if (hasattr(self.client, "get_spot_perp_matches")
                    and hasattr(self.client, "info")
                    and hasattr(self.client.info, "all_mids")):
                try:
                    matches = self.client.get_spot_perp_matches()
                    all_mids = self.client.info.all_mids()
                    for coin, match in matches.items():
                        spot_pair = match.get("spot_pair_name")
                        spot_px = float(all_mids.get(spot_pair, 0))
                        perp_px = float(all_mids.get(coin, 0))
                        if spot_px > 0 and perp_px > 0:
                            basis_bps = ((perp_px - spot_px) / spot_px) * 10000.0
                            # Sanity filter: su coppie reali Spot-Perp il basis non supera il 5% (500 bps).
                            # Valori superiori indicano ticker omonimi non collegati all'asset reale.
                            if abs(basis_bps) > 500.0:
                                continue
                            basis_pct = basis_bps / 100.0
                            if basis_bps > 1.0:
                                direction = "PREMIUM"
                            elif basis_bps < -1.0:
                                direction = "DISCOUNT"
                            else:
                                direction = "FLAT"
                            annualized_basis_apy = (abs(basis_pct) / 100.0) * (365.0 * 24.0 / 8.0) * 100.0
                            self._cache[coin] = BasisData(
                                coin=coin,
                                spot_mid_price=spot_px,
                                perp_mark_price=perp_px,
                                basis_bps=round(basis_bps, 2),
                                basis_pct=round(basis_pct, 4),
                                basis_direction=direction,
                                annualized_basis_apy=round(annualized_basis_apy, 2),
                            )
                    used_all_mids = True
                except Exception as e:
                    logger.debug(f"all_mids basis fetch fallback: {e}")

            # 2. Metodo fallback (per mock e test unitari dove all_mids non è implementato)
            if not used_all_mids:
                spot_prices = self._fetch_spot_prices()
                perp_prices = self._fetch_perp_prices()
                
                for coin in set(list(spot_prices.keys()) + list(perp_prices.keys())):
                    if coin in spot_prices and coin in perp_prices:
                        spot_mid_price = spot_prices[coin]
                        perp_mark_price = perp_prices[coin]
                        
                        if spot_mid_price <= 0:
                            continue
                            
                        basis_bps = ((perp_mark_price - spot_mid_price) / spot_mid_price) * 10000.0
                        basis_pct = basis_bps / 100.0
                        
                        if basis_bps > 1.0:
                            direction = "PREMIUM"
                        elif basis_bps < -1.0:
                            direction = "DISCOUNT"
                        else:
                            direction = "FLAT"
                            
                        annualized_basis_apy = (abs(basis_pct) / 100.0) * (365.0 * 24.0 / 8.0) * 100.0
                        
                        self._cache[coin] = BasisData(
                            coin=coin,
                            spot_mid_price=spot_mid_price,
                            perp_mark_price=perp_mark_price,
                            basis_bps=round(basis_bps, 2),
                            basis_pct=round(basis_pct, 4),
                            basis_direction=direction,
                            annualized_basis_apy=round(annualized_basis_apy, 2),
                        )
                    
            self._last_update = current_time

        # Restituiamo solo i dati per le monete richieste
        result: Dict[str, BasisData] = {}
        for coin in coins:
            if coin in self._cache:
                result[coin] = self._cache[coin]
            else:
                logger.debug(f"Dati basis non trovati o coppia spot assente per la moneta: {coin}")
                
        return result

    def format_basis_report(self, coins: List[str], limit: int = 5) -> str:
        """
        Generates a Telegram-ready HTML formatted report for the basis of the given coins.

        Args:
            coins: List of coin symbols to include in the report.
            limit: Maximum number of coins to include in the formatted report.

        Returns:
            HTML formatted string report.
        """
        basis_data = self.get_basis(coins)
        
        if not basis_data:
            return "<i>Nessun dato basis disponibile.</i>"
            
        report_lines = ["<b>📊 Analisi Basis Spot vs Perp</b>\n"]
        
        # Ordiniamo per spread assoluto decrescente e limitiamo i risultati
        sorted_coins = sorted(
            basis_data.values(), 
            key=lambda x: abs(x.basis_bps), 
            reverse=True
        )[:limit]
        
        for data in sorted_coins:
            if data.basis_direction == "PREMIUM":
                emoji = "📈"
            elif data.basis_direction == "DISCOUNT":
                emoji = "📉"
            else:
                emoji = "➡️"
                
            line = (
                f"{emoji} <b>{data.coin}</b>: {data.basis_direction}\n"
                f"   Spot: <code>${data.spot_mid_price:.4f}</code> | Perp: <code>${data.perp_mark_price:.4f}</code>\n"
                f"   Spread: <b>{data.basis_bps:.2f} bps</b> ({data.basis_pct:.3f}%)\n"
                f"   APY Stimato (8h): <b>{data.annualized_basis_apy:.2f}%</b>\n"
            )
            report_lines.append(line)
            
        return "\n".join(report_lines)
