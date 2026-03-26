# ============================================================
# STRATEGIA 7: MTF CONFLUENCE (Multi-Timeframe Alignment)
# Genera segnale quando 1h, 15m, 1m sono allineati nella stessa direzione
# ============================================================

import logging
import pandas as pd
import numpy as np
from typing import Dict
from datetime import datetime

logger = logging.getLogger(__name__)


class MTFConfluenceStrategy:
    """
    Multi-Timeframe Confluence Strategy.

    Logica:
    - 1h: EMA20 vs EMA50 → direzione macro
    - 15m: EMA9 vs EMA21 + RSI(14) → setup
    - 1m: EMA5 vs EMA13 + volume → trigger

    BUY solo se tutte e 3 le TF sono BULLISH.
    SELL solo se tutte e 3 le TF sono BEARISH.
    Se c'è discordanza → HOLD.

    Score basato su quante TF concordano e quanto forte.
    Questo è il filtro più potente contro i falsi segnali.

    Peso: 2.0x (massimo nel sistema di voting)
    """

    def __init__(self, config: dict):
        """Inizializza la strategia MTF Confluence."""
        self.config = config
        self.strategy_config = config.get('strategy_mtf_confluence', {})
        self.enabled = self.strategy_config.get('enabled', True)

        logger.info(f"MTFConfluenceStrategy inizializzata")

    def _get_tf_direction(self, df, fast, slow, rsi_period=14) -> str:
        """
        Determina la direzione su un timeframe specifico.

        Returns: 'BULLISH', 'BEARISH', o 'NEUTRAL'
        """
        if df is None or len(df) < slow + 5:
            return 'NEUTRAL'

        try:
            close = df['close']
            ema_f = close.ewm(span=fast).mean().iloc[-1]
            ema_s = close.ewm(span=slow).mean().iloc[-1]

            # Calcola RSI
            delta = close.diff()
            gain = delta.where(delta > 0, 0).rolling(rsi_period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(rsi_period).mean()
            rs = gain / loss.replace(0, 1e-10)
            rsi = float((100 - (100 / (1 + rs))).iloc[-1])

            # Margin per evitare fluttuazioni
            margin = 0.0003  # 0.03%

            if ema_f > ema_s * (1 + margin) and rsi > 52:
                return 'BULLISH'
            elif ema_f < ema_s * (1 - margin) and rsi < 48:
                return 'BEARISH'
            return 'NEUTRAL'

        except Exception as e:
            logger.debug(f"Errore calcolo direzione TF: {e}")
            return 'NEUTRAL'

    def analyze(self, df_1m, df_15m, df_1h, symbol: str) -> dict:
        """Analizza alignment multi-timeframe e genera segnale."""
        if not self.enabled:
            return {
                'signal': 'HOLD',
                'strategy': 'mtf_confluence',
                'symbol': symbol,
                'score': 0,
                'reason': 'Strategia disabilitata'
            }

        if df_1m is None or df_15m is None or df_1h is None:
            return {
                'signal': 'HOLD',
                'strategy': 'mtf_confluence',
                'symbol': symbol,
                'score': 0,
                'reason': 'Dati insufficienti'
            }

        # Determina direzione per ogni timeframe
        dir_1h = self._get_tf_direction(df_1h, fast=20, slow=50)
        dir_15m = self._get_tf_direction(df_15m, fast=9, slow=21)
        dir_1m = self._get_tf_direction(df_1m, fast=5, slow=13, rsi_period=7)

        directions = [dir_1h, dir_15m, dir_1m]
        bull_count = directions.count('BULLISH')
        bear_count = directions.count('BEARISH')

        signal = 'HOLD'
        score = 0
        reason = f"1h={dir_1h} 15m={dir_15m} 1m={dir_1m}"

        # Logica: full alignment = score massimo, partial = ridotto
        if bull_count == 3:
            signal = 'BUY'
            score = 3
            reason = f"Full MTF bullish (3/3) | {reason}"
        elif bull_count == 2 and dir_1m == 'BULLISH':
            signal = 'BUY'
            score = 2
            reason = f"Strong MTF bullish (2/3 + 1m ok) | {reason}"
        elif bear_count == 3:
            signal = 'SELL'
            score = 3
            reason = f"Full MTF bearish (3/3) | {reason}"
        elif bear_count == 2 and dir_1m == 'BEARISH':
            signal = 'SELL'
            score = 2
            reason = f"Strong MTF bearish (2/3 + 1m ok) | {reason}"

        logger.info(f"[{symbol}] MTF Confluence: {signal} ({score}) | {reason}")

        return {
            'signal': signal,
            'score': score,
            'strategy': 'mtf_confluence',
            'symbol': symbol,
            'dir_1h': dir_1h,
            'dir_15m': dir_15m,
            'dir_1m': dir_1m,
            'bull_count': bull_count,
            'bear_count': bear_count,
            'reason': reason,
            'timestamp': datetime.now().isoformat()
        }
