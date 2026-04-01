# ============================================================
# REGIME DETECTOR - Market Structure Classification
# Classifica il mercato in TRENDING / RANGING / UNDEFINED
# Usa ADX (Average Directional Index) + Choppiness Index
# ============================================================

import logging
import pandas as pd
import numpy as np
from typing import Dict, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class RegimeDetector:
    """
    Classifica il mercato in 3 regimi per adattare strategia e sizing.

    Regimi:
    1. TRENDING: ADX > 25 AND Choppiness < 50
       → Usa EMA Crossover + VWAP Momentum
       → Disabilita Bollinger Squeeze e Liquidity Hunt

    2. RANGING: ADX < 20 OR Choppiness > 61.8
       → Usa SOLO Bollinger Squeeze (mean reversion)
       → Disabilita EMA, VWAP, Liquidity Hunt

    3. UNDEFINED: Nessuna condizione sopra
       → Attiva tutti, ma richiede 2/3 min voting (conservativo)
       → Score minimo aumentato per caution
    """

    def __init__(self, config: dict):
        """Inizializza Regime Detector"""
        self.config = config
        self.adx_period = 14
        self.choppiness_period = 14

        logger.info("RegimeDetector inizializzato (ADX period 14, Choppiness period 14)")

    def calculate_adx(self, df: pd.DataFrame) -> float:
        """
        Calcola Average Directional Index (ADX).

        ADX misura la forza di un trend (0-100):
        - ADX > 25: Trend forte (TRENDING)
        - ADX < 20: Trend debole o assente (RANGING)
        - 20-25: Zona grigia

        Implementazione:
        1. Calcola +DI (Positive Directional Indicator)
        2. Calcola -DI (Negative Directional Indicator)
        3. DX = |+DI - -DI| / (+DI + -DI) * 100
        4. ADX = media mobile del DX
        """
        if df is None or len(df) < self.adx_period + 10:
            return 20.0  # Default: neutral

        try:
            high = df['high'].values
            low = df['low'].values
            close = df['close'].values

            # Calcola up move e down move
            up_move = np.zeros(len(df))
            down_move = np.zeros(len(df))

            for i in range(1, len(df)):
                up = high[i] - high[i-1]
                down = low[i-1] - low[i]

                if up > down and up > 0:
                    up_move[i] = up
                if down > up and down > 0:
                    down_move[i] = down

            # Calcola True Range
            tr1 = high - low
            tr2 = np.abs(high - np.roll(close, 1))
            tr3 = np.abs(low - np.roll(close, 1))
            true_range = np.maximum(tr1, np.maximum(tr2, tr3))

            # Smooth con RMA (Welles Wilder)
            plus_di = 100 * self._rma(pd.Series(up_move), self.adx_period) / \
                      self._rma(pd.Series(true_range), self.adx_period)
            minus_di = 100 * self._rma(pd.Series(down_move), self.adx_period) / \
                       self._rma(pd.Series(true_range), self.adx_period)

            # DX
            di_sum = plus_di + minus_di
            di_sum = di_sum.replace(0, 0.001)  # Evita divisione per zero
            dx = 100 * np.abs(plus_di - minus_di) / di_sum

            # ADX = media mobile di DX
            adx = self._rma(dx, self.adx_period)

            adx_value = float(adx.iloc[-1]) if pd.notna(adx.iloc[-1]) else 20.0
            return max(0, min(100, adx_value))

        except Exception as e:
            logger.error(f"Errore calcolo ADX: {e}")
            return 20.0

    def calculate_choppiness(self, df: pd.DataFrame) -> float:
        """
        Calcola Choppiness Index.

        CI misura quanto "choppy" è il mercato (pianezza vs trend):
        CI = 100 * LOG10(SUM(ATR, 14) / (MAX(HIGH, 14) - MIN(LOW, 14))) / LOG10(14)

        - CI < 38.2: Forte downtrend
        - CI 38.2-61.8: Ranging
        - CI > 61.8: Forte uptrend

        Per regime detection usiamo:
        - CI < 50: TRENDING (mercato ha direzione)
        - CI > 61.8: RANGING (mercato piatto/consolidation)
        """
        if df is None or len(df) < self.choppiness_period + 5:
            return 50.0  # Default: neutral

        try:
            high = df['high']
            low = df['low']
            close = df['close']

            # Calcola ATR
            tr1 = high - low
            tr2 = (high - close.shift(1)).abs()
            tr3 = (low - close.shift(1)).abs()
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            atr_sum = tr.rolling(window=self.choppiness_period).sum()

            # Calcola HIGH e LOW range
            high_max = high.rolling(window=self.choppiness_period).max()
            low_min = low.rolling(window=self.choppiness_period).min()
            hl_range = high_max - low_min

            # Choppiness Index
            ci = 100 * np.log10(atr_sum / hl_range) / np.log10(self.choppiness_period)

            ci_value = float(ci.iloc[-1]) if pd.notna(ci.iloc[-1]) else 50.0
            return max(0, min(100, ci_value))

        except Exception as e:
            logger.error(f"Errore calcolo Choppiness: {e}")
            return 50.0

    def detect_regime(self, df_1min: pd.DataFrame) -> Dict:
        """
        Rileva il regime di mercato (TRENDING / RANGING / UNDEFINED).

        Ritorna:
        {
            'regime': str ('TRENDING' | 'RANGING' | 'UNDEFINED'),
            'adx': float,
            'choppiness': float,
            'confidence': float (0-1),
            'strategy_mask': List[bool, bool, bool, bool],
                # [confluence/EMA, breakout/BB, sentiment/VWAP, liquidity/hunt]
            'timestamp': str (ISO format)
        }
        """
        if df_1min is None or len(df_1min) < 50:
            return {
                'regime': 'UNDEFINED',
                'adx': 20.0,
                'choppiness': 50.0,
                'confidence': 0.0,
                'strategy_mask': [True, True, True, True, True, True],  # Tutti attivi (6 elementi)
                'timestamp': datetime.now().isoformat(),
                'reason': 'Dati insufficienti'
            }

        # Calcola ADX e Choppiness
        adx = self.calculate_adx(df_1min)
        choppiness = self.calculate_choppiness(df_1min)

        # Classificazione regime
        # Strategy order: [confluence, breakout, sentiment, rsi_divergence, sr_bounce, mtf_confluence]
        if adx > 25 and choppiness < 50:
            regime = 'TRENDING'
            # TRENDING: EMA + VWAP + RSI-Div + MTF
            strategy_mask = [True, False, True, True, False, True]
            confidence = min(0.95, (adx - 20) / 30)  # Aumenta con ADX

        elif adx < 20 or choppiness > 61.8:
            regime = 'RANGING'
            # RANGING: BB + S/R Bounce (mean reversion)
            strategy_mask = [False, True, False, False, True, False]
            if adx < 20:
                confidence = (20 - adx) / 20
            else:
                confidence = (choppiness - 61.8) / (100 - 61.8)
            confidence = min(0.95, confidence)

        else:
            regime = 'UNDEFINED'
            # Tutti attivi (6 elementi)
            strategy_mask = [True, True, True, True, True, True]
            # Confidence basato su quanto siamo lontani dalle soglie
            adx_dist = min(abs(adx - 25), abs(adx - 20))
            choppiness_dist = min(abs(choppiness - 50), abs(choppiness - 61.8))
            confidence = min(0.5, (adx_dist + choppiness_dist) / 100)

        result = {
            'regime': regime,
            'adx': round(adx, 2),
            'choppiness': round(choppiness, 2),
            'confidence': round(confidence, 3),
            'strategy_mask': strategy_mask,
            'timestamp': datetime.now().isoformat(),
            'reason': f"{regime} (ADX={adx:.1f}, CI={choppiness:.1f})"
        }

        logger.info(f"Regime: {regime} | ADX={adx:.1f} | Choppiness={choppiness:.1f} | "
                   f"Confidence={confidence:.3f} | Mask={strategy_mask}")

        return result

    @staticmethod
    def _rma(series: pd.Series, period: int) -> pd.Series:
        """
        Calcola RMA (Relative Moving Average) - Welles Wilder smoothing.
        Usato per ADX calculation.

        RMA = (RMA_prev * (period - 1) + value) / period
        """
        rma = pd.Series(0.0, index=series.index)
        rma.iloc[period - 1] = series.iloc[:period].mean()

        for i in range(period, len(series)):
            rma.iloc[i] = (rma.iloc[i-1] * (period - 1) + series.iloc[i]) / period

        return rma
