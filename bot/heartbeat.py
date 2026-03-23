#!/usr/bin/env python3
# ============================================================
# BOT HEARTBEAT - Verifica che il bot stia girando
# Aggiorna un file JSON ogni ciclo di analisi
# ============================================================

import json
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

IT_TZ = ZoneInfo("Europe/Rome")
HEARTBEAT_FILE = Path('data/bot_heartbeat.json')


def update_heartbeat(action: str = "analyzing", symbol: str = "", details: str = ""):
    """Aggiorna il heartbeat del bot."""
    try:
        HEARTBEAT_FILE.parent.mkdir(parents=True, exist_ok=True)

        data = {
            'timestamp': datetime.now(IT_TZ).isoformat(),
            'action': action,
            'symbol': symbol,
            'details': details,
            'alive': True
        }

        with open(HEARTBEAT_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    except Exception as e:
        print(f"Errore heartbeat: {e}")


def get_heartbeat():
    """Legge l'ultimo heartbeat."""
    try:
        if HEARTBEAT_FILE.exists():
            with open(HEARTBEAT_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return None
