"""Configuration management for Hyperliquid Bot."""

from dataclasses import dataclass
import os
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

MAINNET_API_URL = "https://api.hyperliquid.xyz"
TESTNET_API_URL = "https://api.hyperliquid-testnet.xyz"


@dataclass
class HyperliquidConfig:
    """Hyperliquid Bot Configuration."""

    network: str = "testnet"
    account_address: Optional[str] = None
    secret_key: Optional[str] = None
    vault_address: Optional[str] = None
    custom_base_url: Optional[str] = None
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None

    @property
    def is_mainnet(self) -> bool:
        """Check if network is mainnet."""
        return self.network.lower() in ("mainnet", "prod", "production")

    @property
    def base_url(self) -> str:
        """Get the base API URL based on configuration."""
        if self.custom_base_url:
            return self.custom_base_url
        return MAINNET_API_URL if self.is_mainnet else TESTNET_API_URL

    @classmethod
    def from_env(cls) -> "HyperliquidConfig":
        """Load configuration from environment variables."""
        return cls(
            network=os.getenv("NETWORK", "testnet"),
            account_address=os.getenv("ACCOUNT_ADDRESS") or None,
            secret_key=os.getenv("SECRET_KEY") or None,
            vault_address=os.getenv("VAULT_ADDRESS") or None,
            custom_base_url=os.getenv("CUSTOM_BASE_URL") or None,
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID") or None,
        )
