"""Telegram Notification & Command Listener module for Hyperliquid Bot."""

import json
import logging
import threading
import time
from typing import Any, Callable, Dict, Optional
import urllib.parse
import urllib.request

logger = logging.getLogger("hyperliquid_bot.telegram")


class TelegramNotifier:
    """Sends notifications, trade alerts, and listens for interactive commands via Telegram."""

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
    ):
        self.bot_token = bot_token
        self.chat_id = str(chat_id) if chat_id else None
        self.is_enabled = bool(self.bot_token and self.chat_id)
        self.command_handlers: Dict[str, Callable[[], str]] = {}
        self._polling_thread: Optional[threading.Thread] = None
        self._is_polling = False
        self._last_update_id = 0

        if self.is_enabled:
            logger.info("📱 Notifiche Telegram ATTIVATE")
        else:
            logger.info("📱 Notifiche Telegram DISATTIVATE (token o chat_id mancanti)")

    def register_command(self, command: str, handler: Callable[[], str]) -> None:
        """Register a callback handler for a Telegram command (e.g. '/status')."""
        cmd = command.lower().strip()
        if not cmd.startswith("/"):
            cmd = "/" + cmd
        self.command_handlers[cmd] = handler

    def start_polling(self) -> None:
        """Start listening for incoming Telegram commands in a background daemon thread."""
        if not self.is_enabled or self._is_polling:
            return
        self._is_polling = True
        self._polling_thread = threading.Thread(
            target=self._poll_updates_loop,
            name="TelegramPollingThread",
            daemon=True,
        )
        self._polling_thread.start()
        logger.info("🤖 Telegram Command Listener AVVIATO (comandi attivi: /status, /balance, /closeall, /help)")

    def stop_polling(self) -> None:
        """Stop listening for Telegram commands."""
        self._is_polling = False

    def _poll_updates_loop(self) -> None:
        """Long-polling loop for Telegram updates."""
        # Initial offset sync: discard old stale messages sent before startup
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates?offset=-1&timeout=0"
            req = urllib.request.Request(url, headers={"User-Agent": "HyperliquidBot/1.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    results = data.get("result", [])
                    if results:
                        self._last_update_id = results[-1]["update_id"]
        except Exception:
            pass

        while self._is_polling:
            try:
                offset = self._last_update_id + 1
                url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates?offset={offset}&timeout=5"
                req = urllib.request.Request(url, headers={"User-Agent": "HyperliquidBot/1.0"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode("utf-8"))
                        for update in data.get("result", []):
                            self._last_update_id = update["update_id"]
                            self._handle_update(update)
            except Exception:
                time.sleep(2.0)
            time.sleep(0.5)

    def _handle_update(self, update: Dict[str, Any]) -> None:
        """Process a single Telegram message update securely."""
        msg = update.get("message")
        if not msg:
            return

        chat = msg.get("chat", {})
        sender_chat_id = str(chat.get("id", ""))

        # Security check: only accept commands from the authorized chat_id!
        if sender_chat_id != self.chat_id:
            logger.warning(f"⚠️ Tentativo di comando Telegram non autorizzato da chat ID: {sender_chat_id}")
            return

        text = msg.get("text", "").strip()
        if not text.startswith("/"):
            return

        # Split command and possible bot username suffix e.g. /status@MyBot
        cmd_part = text.split()[0].lower().split("@")[0]

        if cmd_part in self.command_handlers:
            try:
                response = self.command_handlers[cmd_part]()
                if response:
                    self.send_message(response)
            except Exception as e:
                logger.error(f"Errore durante l'esecuzione del comando {cmd_part}: {e}")
                self.send_message(f"❌ <b>Errore durante l'esecuzione del comando:</b> {e}")
        elif cmd_part in ["/start", "/help"]:
            help_msg = (
                "🤖 <b>Comandi Disponibili Hyperliquid Bot:</b>\n\n"
                "📊 /status — Report guadagni e posizioni in tempo reale\n"
                "🏦 /balance — Saldo conto, margine e capitale allocato\n"
                "🛑 /closeall — <i>Chiusura di emergenza</i> di tutte le posizioni\n"
                "ℹ️ /help — Mostra questo messaggio di aiuto"
            )
            self.send_message(help_msg)
        else:
            self.send_message(f"❓ Comando non riconosciuto: <code>{cmd_part}</code>\nInvia /help per la lista comandi.")

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
                headers={"Content-Type": "application/json", "User-Agent": "HyperliquidBot/1.0"},
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
        msg += (
            f"\n<i>Il bot è ora attivo 24/7.</i>\n"
            f"💡 <i>Invia /help per visualizzare i comandi interattivi disponibili.</i>"
        )
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

    def send_daily_summary(
        self,
        date_str: str,
        daily_earnings_usd: float,
        total_lifetime_earnings_usd: float,
        capital_allocated_usd: float,
        daily_roi_pct: float,
        compounded_boost_usd: float = 0.0,
        positions_summary: str = "",
    ) -> None:
        """Send elegant daily midnight earnings report."""
        msg = (
            f"🌙 <b>REPORT GIORNALIERO BOT ({date_str})</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 <b>Guadagno 24h:</b> 🟢 <b>+${daily_earnings_usd:.4f} USD</b>\n"
            f"📈 <b>ROI Giornaliero:</b> <b>+{daily_roi_pct:.2f}%</b>\n"
            f"🏦 <b>Capitale Allocato:</b> ${capital_allocated_usd:,.2f}\n"
        )
        if compounded_boost_usd > 0:
            msg += f"⚡ <b>Auto-Compounding Attivo:</b> +${compounded_boost_usd:.2f} reinvestiti\n"
        msg += (
            f"🏆 <b>Totale Storico Incassato:</b> <b>+${total_lifetime_earnings_usd:.4f} USD</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
        )
        if positions_summary:
            msg += f"<b>Posizioni Attive:</b>\n{positions_summary}\n"
        msg += f"<i>Il bot continua a macinare rendita 24/7. Buonanotte!</i> 😴"

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
