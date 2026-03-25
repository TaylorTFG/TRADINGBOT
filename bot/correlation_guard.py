# ============================================================
# CORRELATION GUARD - Prevent Correlated Positions
# Evita aperture multiple su asset altamente correlati
# ============================================================

import logging
from typing import Dict, List, Tuple, Optional

logger = logging.getLogger(__name__)


class CorrelationGuard:
    """
    Evita posizioni multiple su asset altamente correlati per ridurre
    l'esposizione di portafoglio e migliorare la diversificazione.

    Cluster (basati su correlazione storica):
    - Cluster CRYPTO: [BTC/USD, ETH/USD, SOL/USD, XRP/USD] (corr 0.7+)
    - Cluster TECH: [NVDA, AMD] (corr 0.6+)
    - Cluster BROAD: [SPY, TSLA] (corr 0.3-0.5, ma moved together spesso)

    Regole di Filtering:
    1. Max 1 posizione per cluster NELLA STESSA DIREZIONE (BUY o SELL)
       Esempio: Se abbiamo BTC/USD LONG, non possiamo aprire ETH/USD LONG
       Ma possiamo aprire ETH/USD SHORT (direzione opposta)

    2. Max 2 crypto + 2 stocks simultaneamente
       Questo limita l'esposizione a 4 posizioni max, mantenendo diversificazione

    Razionale:
    - Correlated assets spesso si muovono insieme
    - Aprire multipli LONG su asset correlati = rischio concentrato
    - Questo guard forza diversificazione di direzione o asset diversi
    """

    def __init__(self):
        """Inizializza Correlation Guard con cluster predefiniti."""
        self.clusters = {
            'crypto': ['BTC/USD', 'ETH/USD', 'SOL/USD', 'XRP/USD'],
            'tech': ['NVDA', 'AMD'],
            'broad': ['SPY', 'TSLA']
        }
        logger.info(f"CorrelationGuard inizializzato: {len(self.clusters)} cluster")

    def can_open_position(
        self,
        symbol: str,
        side: str,
        open_positions: List[Dict]
    ) -> Tuple[bool, str]:
        """
        Verifica se è possibile aprire una nuova posizione su 'symbol' con 'side'.

        Args:
            symbol: Simbolo dell'asset (es. "BTC/USD", "NVDA")
            side: 'BUY' o 'SELL'
            open_positions: Lista delle posizioni aperte {'symbol': str, 'side': str, ...}

        Returns:
            (allowed: bool, reason: str)
            - allowed=True: posizione può essere aperta
            - allowed=False: posizione è bloccata dal correlation guard + motivo
        """

        # ---- CHECK 1: Cluster Correlation ----
        cluster = self._find_cluster(symbol)
        if cluster:
            # Controlla se c'è già una posizione nello stesso cluster con lo stesso side
            cluster_same_side = [
                p for p in open_positions
                if self._find_cluster(p['symbol']) == cluster and p['side'] == side
            ]

            if cluster_same_side:
                existing_symbol = cluster_same_side[0]['symbol']
                return False, (
                    f"Cluster guard: {symbol} è correlato a {existing_symbol} "
                    f"(cluster {cluster}). Max 1 {side} per cluster."
                )

        # ---- CHECK 2: Asset Count (crypto vs stocks) ----
        is_crypto = '/' in symbol
        crypto_count = len([p for p in open_positions if '/' in p['symbol']])
        stock_count = len([p for p in open_positions if '/' not in p['symbol']])

        if is_crypto and crypto_count >= 2:
            return False, (
                f"Max crypto limit: già {crypto_count} crypto aperte "
                f"({', '.join([p['symbol'] for p in open_positions if '/' in p['symbol']])}). "
                f"Max 2 crypto simultanee."
            )

        if not is_crypto and stock_count >= 2:
            return False, (
                f"Max stock limit: già {stock_count} stock aperte "
                f"({', '.join([p['symbol'] for p in open_positions if '/' not in p['symbol']])}). "
                f"Max 2 stock simultanee."
            )

        # ---- CHECK 3: Total Position Limit ----
        if len(open_positions) >= 4:
            return False, (
                f"Max total limit: già 4 posizioni aperte. "
                f"Chiudi una posizione prima di aprirne una nuova."
            )

        # ---- ALLOWED ----
        return True, "OK - Posizione consentita"

    def get_cluster_status(self, open_positions: List[Dict]) -> Dict:
        """
        Ritorna uno snapshot dello stato dei cluster.

        Utile per diagnostica e logging.

        Returns:
            {
                'cluster_name': {
                    'positions': List[symbols],
                    'buy_count': int,
                    'sell_count': int,
                    'available_slots': int
                }
            }
        """
        status = {}

        for cluster_name, symbols in self.clusters.items():
            cluster_pos = [p for p in open_positions
                          if self._find_cluster(p['symbol']) == cluster_name]

            buy_pos = [p for p in cluster_pos if p['side'] == 'BUY']
            sell_pos = [p for p in cluster_pos if p['side'] == 'SELL']

            # Available slots: se hai 1 BUY, puoi aprire 1 SELL
            available_slots = (
                2 - len(buy_pos) if len(sell_pos) == 0 else
                (2 - len(sell_pos) if len(buy_pos) == 0 else 0)
            )

            status[cluster_name] = {
                'symbols': symbols,
                'positions': [(p['symbol'], p['side']) for p in cluster_pos],
                'buy_count': len(buy_pos),
                'sell_count': len(sell_pos),
                'available_slots': available_slots
            }

        return status

    def _find_cluster(self, symbol: str) -> Optional[str]:
        """
        Ritorna il nome del cluster a cui appartiene il simbolo.

        Args:
            symbol: Es. "BTC/USD", "NVDA", "SPY"

        Returns:
            Nome cluster o None se non trovato
        """
        for cluster_name, symbols in self.clusters.items():
            if symbol in symbols:
                return cluster_name
        return None

    def log_cluster_status(self, open_positions: List[Dict]) -> None:
        """Stampa uno snapshot dello stato dei cluster per diagnostica."""
        status = self.get_cluster_status(open_positions)
        logger.info("=== CLUSTER STATUS ===")
        for cluster_name, info in status.items():
            logger.info(
                f"{cluster_name.upper()}: {info['positions']} "
                f"(BUY={info['buy_count']}, SELL={info['sell_count']}, "
                f"available={info['available_slots']})"
            )
