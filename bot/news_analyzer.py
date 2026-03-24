# ============================================================
# NEWS ANALYZER - DISABILITATO PER SCALPING CRYPTO H24
# Le notizie sono troppo lente per scalping 1min
# Questo file restituisce sempre sentiment neutro
# ============================================================

import logging
from datetime import datetime
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)


class NewsAnalyzer:
    """
    News Analyzer disabilitato per scalping.
    Restituisce sempre sentiment_score = 0 (neutro).
    """

    def __init__(self, config: dict):
        """Inizializza il news analyzer (disabilitato)."""
        self.config = config
        logger.info("NewsAnalyzer disabilitato - scalping crypto non usa notizie")

    def get_sentiment(self, symbol: str) -> Dict:
        """
        Restituisce sempre sentiment neutro per scalping.

        Args:
            symbol: Simbolo dell'asset

        Returns:
            Dizionario con score = 0 (neutro)
        """
        return {
            'score': 0.0,  # Sentiment neutro
            'confidence': 0.0,
            'classification': 'NEUTRAL',
            'article_count': 0,
            'recent_count': 0,
            'recent_score': 0.0,
            'older_score': 0.0,
            'symbol': symbol,
            'timestamp': datetime.now().isoformat(),
            'sources': [],
            'note': 'News analyzer disabled for crypto scalping (1min analysis)'
        }

    def fetch_newsapi(self, symbol: str, hours: int) -> List[Dict]:
        """Restituisce lista vuota (disabilitato)."""
        return []

    def fetch_rss_feeds(self, symbol: str) -> List[Dict]:
        """Restituisce lista vuota (disabilitato)."""
        return []

    def analyze_text(self, text: str) -> float:
        """Restituisce sempre 0 (disabilitato)."""
        return 0.0

    def calculate_weighted_sentiment(self, articles: List[Dict]) -> Dict:
        """Restituisce sentiment neutro (disabilitato)."""
        return {'score': 0.0, 'confidence': 0.0}

    def _is_cache_valid(self, key: str) -> bool:
        """Restituisce False (nessun cache)."""
        return False

    def filter_by_sentiment_threshold(self, threshold: float) -> Optional[str]:
        """Restituisce None (disabilitato)."""
        return None
