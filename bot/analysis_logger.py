#!/usr/bin/env python3
# ============================================================
# ANALYSIS LOGGER - Salva i dettagli delle analisi in JSON
# Per visualizzare nella dashboard i segnali di trading
# ============================================================

import json
import logging
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from collections import deque

logger = logging.getLogger(__name__)
IT_TZ = ZoneInfo("Europe/Rome")

# File dove salviamo le analisi recenti
ANALYSIS_FILE = Path('data/recent_analysis.json')


class AnalysisLogger:
    """Logger per le analisi delle strategie."""

    def __init__(self, max_items: int = 100):
        self.max_items = max_items
        self.analyses = deque(maxlen=max_items)
        self._load_from_file()

    def _load_from_file(self):
        """Carica le analisi dal file."""
        try:
            if ANALYSIS_FILE.exists():
                with open(ANALYSIS_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.analyses = deque(data.get('analyses', []), maxlen=self.max_items)
        except Exception as e:
            logger.error(f"Errore caricamento analisi: {e}")

    def _save_to_file(self):
        """Salva le analisi nel file."""
        try:
            ANALYSIS_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(ANALYSIS_FILE, 'w', encoding='utf-8') as f:
                json.dump({
                    'analyses': list(self.analyses),
                    'total': len(self.analyses),
                    'last_update': datetime.now(IT_TZ).isoformat()
                }, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Errore salvataggio analisi: {e}")

    def log_analysis(self, symbol: str, signal: str, details: dict):
        """
        Logga un'analisi di strategia.

        Args:
            symbol: Simbolo (es. TSLA, SPY)
            signal: Segnale (HOLD, BUY, SELL)
            details: Dettagli aggiuntivi (voti, strategie, ecc.)
        """
        try:
            entry = {
                'timestamp': datetime.now(IT_TZ).isoformat(),
                'symbol': symbol,
                'signal': signal,
                'details': details
            }

            self.analyses.append(entry)
            self._save_to_file()

            # Logga anche nel logger standard
            logger.info(f"[{symbol}] {signal} - {details}")

        except Exception as e:
            logger.error(f"Errore log_analysis: {e}")

    def log_confluence(self, symbol: str, score: str, indicators: dict, vote: dict):
        """Logga analisi Confluence."""
        self.log_analysis(symbol, vote.get('signal', 'HOLD'), {
            'strategy': 'Confluence',
            'score': score,
            'indicators': indicators,
            'votes': vote
        })

    def log_meta_strategy(self, symbol: str, signal: str, votes: dict, reason: str = ""):
        """Logga MetaStrategy (voto finale)."""
        self.log_analysis(symbol, signal, {
            'strategy': 'MetaStrategy',
            'votes': votes,
            'reason': reason
        })

    def get_recent(self, limit: int = 50):
        """Ottiene le analisi recenti."""
        return list(self.analyses)[-limit:]


# Istanza globale
analysis_logger = AnalysisLogger(max_items=200)
