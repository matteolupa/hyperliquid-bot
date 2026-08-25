"""State persistence module for saving and recovering bot state across restarts."""

from dataclasses import asdict, is_dataclass
import json
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger("hyperliquid_bot.persistence")


class StatePersistenceManager:
    """Handles saving and loading strategy state to/from disk (JSON)."""

    def __init__(self, data_dir: str = "data", filename: str = "bot_state.json"):
        self.data_dir = data_dir
        self.filename = filename
        self.filepath = os.path.join(data_dir, filename)
        os.makedirs(self.data_dir, exist_ok=True)

    def save_state(self, state: Dict[str, Any]) -> bool:
        """Save state dictionary to JSON file atomically."""
        try:
            temp_path = self.filepath + ".tmp"
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, default=str)
            os.replace(temp_path, self.filepath)
            return True
        except Exception as e:
            logger.error(f"Errore durante il salvataggio dello stato: {e}")
            return False

    def load_state(self) -> Optional[Dict[str, Any]]:
        """Load state dictionary from JSON file if present."""
        if not os.path.exists(self.filepath):
            return None

        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                state = json.load(f)
            logger.info(f"💾 Stato precedente recuperato con successo da {self.filepath}")
            return state
        except Exception as e:
            logger.warning(f"Impossibile leggere il file di stato precedente ({self.filepath}): {e}")
            return None
