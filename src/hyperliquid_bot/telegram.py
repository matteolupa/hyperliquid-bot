"""Telegram Notification module for Hyperliquid Bot."""

import logging
from typing import Optional
import urllib.request
import json

logger = logging.getLogger("hyperliquid_bot.telegram")


class TelegramNotifier:
    """Sends notifications, trade alerts, and status reports to Telegram."""

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
    ):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.is_enabled = bool(self.bot_token and self.chat_id)

        if self.is_enabled:
            logger.info("📱 Notifiche Telegram ATTIVATE")
        else:
            logger.info("📱 Notifiche Telegram DISATTIVATE (token o chat_id mancanti)")

    def send_message(self, message: str) -> bool:
        """Send a plain text or Markdown message to Telegram chat."""
        if not self.is_enabled:
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }

        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status == 200:
                    return True
        except Exception as e:
            logger.warning(f"Impossibile inviare messaggio Telegram: {e}")

        return False

    def send_startup(self, strategy_name: str, mode: str, details: str = "") -> None:
        """Send bot startup notification."""
        msg = (
            f"🚀 <b>Hyperliquid Bot Avviato!</b>\n\n"
            f"▫️ <b>Strategia:</b> <code>{strategy_name}</code>\n"
            f"▫️ <b>Modalità:</b> <code>{mode}</code>\n"
        )
        if details:
            msg += f"▫️ <b>Dettagli:</b> {details}\n"
        msg += f"\n<i>Il bot è ora attivo 24/7.</i>"
        self.send_message(msg)

    def send_status_report(self, report_text: str) -> None:
        """Send formatted status report."""
        msg = f"<pre>{report_text.strip()}</pre>"
        self.send_message(msg)

    def send_trade_alert(
        self,
        action: str,
        symbol: str,
        size: float,
        price: float,
        pnl: Optional[float] = None,
        notes: str = "",
    ) -> None:
        """Send alert on trade buy / sell / take-profit."""
        if "ACQUISTO" in action.upper() or "BUY" in action.upper():
            emoji = "🛒"
        elif "PROFIT" in action.upper() or (pnl is not None and pnl > 0):
            emoji = "🎯"
        elif "STOP" in action.upper() or (pnl is not None and pnl < 0):
            emoji = "🛑"
        else:
            emoji = "📊"

        msg = (
            f"{emoji} <b>{action} ({symbol})</b>\n\n"
            f"▫️ <b>Size:</b> {size:.4f} {symbol} (${size * price:,.2f})\n"
            f"▫️ <b>Prezzo:</b> ${price:,.2f}\n"
        )
        if pnl is not None:
            pnl_emoji = "🟢" if pnl >= 0 else "🔴"
            msg += f"▫️ <b>PnL Netto:</b> {pnl_emoji} <b>${pnl:+.4f} USD</b>\n"
        if notes:
            msg += f"▫️ <b>Note:</b> {notes}\n"

        self.send_message(msg)

    def send_shutdown(self, strategy_name: str, summary: str = "") -> None:
        """Send bot shutdown alert."""
        msg = (
            f"🛑 <b>Hyperliquid Bot Fermato!</b>\n\n"
            f"▫️ <b>Strategia:</b> {strategy_name}\n"
        )
        if summary:
            msg += f"▫️ <b>Riepilogo:</b> {summary}\n"
        self.send_message(msg)
