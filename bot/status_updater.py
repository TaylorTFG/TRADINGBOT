#!/usr/bin/env python3
"""
Status Updater - Aggiorna file JSON di stato per dashboard
Separato da TelegramNotifier per funzionare anche senza Telegram
"""

import json
import logging
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
IT_TZ = ZoneInfo("Europe/Rome")


class StatusUpdater:
    """Aggiorna bot_status.json per dashboard."""

    def __init__(self, config: dict):
        self.config = config

    def update_status(self, status: str, reason: str = ""):
        """
        Aggiorna lo stato del bot nel file JSON.

        Args:
            status: 'started', 'stopped', 'paused', 'error'
            reason: Motivo opzionale
        """
        status_map = {
            'started': ('🟢', 'AVVIATO'),
            'stopped': ('🔴', 'FERMATO'),
            'paused': ('🟡', 'IN PAUSA'),
            'error': ('❌', 'ERRORE'),
        }
        emoji, status_it = status_map.get(status, ('ℹ️', status.upper()))

        status_data = {
            'status': status,
            'status_it': status_it,
            'timestamp': datetime.now(IT_TZ).isoformat(),
            'reason': reason,
            'mode': self.config.get('trading', {}).get('mode', 'paper')
        }

        status_file = Path('data/bot_status.json')
        try:
            status_file.parent.mkdir(parents=True, exist_ok=True)
            with open(status_file, 'w') as f:
                json.dump(status_data, f, indent=2, ensure_ascii=False)
            logger.debug(f"✓ Bot status updated: {status} → {status_it}")
        except Exception as e:
            logger.error(f"Errore salvando bot_status.json: {e}")
