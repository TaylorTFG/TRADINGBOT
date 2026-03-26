# ============================================================
# STRATEGIA 5: RSI DIVERGENCE SCALPING (1min)
# Rileva divergenze RSI per segnali di reversal anticipatori
# ============================================================

import logging
import pandas as pd
import numpy as np
from typing import Optional, Dict
from datetime import datetime

logger = logging.getLogger(__name__)


class RSIDivergenceStrategy:
    """
    RSI Divergence Scalping Strategy.

    Rileva divergenze RSI — uno dei segnali di reversal più affidabili
    nel crypto scalping. Una divergenza bullish significa che il prezzo
    fa un nuovo minimo ma l'RSI non lo conferma (sta salendo), indicando
    che il momentum al ribasso si sta esaurendo.

    Segnali:
    - BULLISH DIVERGENCE: price LL (lower low) + RSI HL (higher low)
      → segnale BUY anticipatorio
    - BEARISH DIVERGENCE: price HH (higher high) + RSI LH (lower high)
      → segnale SELL anticipatorio

    Parametri:
    - RSI period: 14 (più stabile del 7 per divergenze)
    - Lookback per pivot: 5 candele a sinistra e destra
    - Min divergence strength: differenza RSI > 3 punti
    """

    def __init__(self, config: dict):
        """Inizializza la strategia RSI Divergence."""
        self.config = config
        self.strategy_config = config.get('strategy_rsi_divergence', {})
        self.enabled = self.strategy_config.get('enabled', True)

        # Parametri RSI
        self.rsi_period = self.strategy_config.get('rsi_period', 14)
        self.pivot_lookback = self.strategy_config.get('pivot_lookback', 5)
        self.min_div_strength = self.strategy_config.get('min_divergence_strength', 3.0)

        logger.info(f"RSIDivergenceStrategy inizializzata (period={self.rsi_period})")

    def calculate_rsi(self, close: pd.Series, period: int = 14) -> pd.Series:
        """Calcola RSI standard."""
        delta = close.diff()
        gain = delta.where(delta > 0, 0).rolling(period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
        rs = gain / loss.replace(0, 1e-10)
        return 100 - (100 / (1 + rs))

    def find_pivots(self, series: pd.Series, n: int = 5) -> tuple:
        """Trova pivot high e pivot low nella serie."""
        highs, lows = [], []
        for i in range(n, len(series) - n):
            window = series.iloc[i-n:i+n+1]
            if series.iloc[i] == window.max():
                highs.append(i)
            if series.iloc[i] == window.min():
                lows.append(i)
        return highs, lows

    def detect_divergence(self, df: pd.DataFrame) -> dict:
        """Rileva divergenza RSI sull'ultimo segmento di prezzo."""
        if len(df) < 50:
            return {'divergence': 'NONE', 'type': None, 'strength': 0}

        close = df['close']
        rsi = self.calculate_rsi(close, self.rsi_period)
        _, price_lows = self.find_pivots(close, self.pivot_lookback)
        _, rsi_lows = self.find_pivots(rsi, self.pivot_lookback)

        # Bullish divergence: ultimi 2 price lows e 2 rsi lows
        if len(price_lows) >= 2 and len(rsi_lows) >= 2:
            pl1, pl2 = price_lows[-2], price_lows[-1]
            rl1, rl2 = rsi_lows[-2], rsi_lows[-1]

            price_ll = close.iloc[pl2] < close.iloc[pl1]
            rsi_hl = rsi.iloc[rl2] > rsi.iloc[rl1]
            strength = abs(rsi.iloc[rl2] - rsi.iloc[rl1])

            # I pivot devono essere recenti (ultimi 30 bar)
            recency_ok = pl2 > len(df) - 30 and pl2 == max(price_lows[-2:])

            if price_ll and rsi_hl and strength >= self.min_div_strength and recency_ok:
                return {
                    'divergence': 'BULLISH',
                    'type': 'Regular',
                    'strength': round(strength, 1),
                    'price_pivot1': float(close.iloc[pl1]),
                    'price_pivot2': float(close.iloc[pl2]),
                    'rsi_pivot1': float(rsi.iloc[rl1]),
                    'rsi_pivot2': float(rsi.iloc[rl2]),
                }

        # Bearish divergence: analisi speculare su highs
        price_highs, _ = self.find_pivots(close, self.pivot_lookback)
        rsi_highs, _ = self.find_pivots(rsi, self.pivot_lookback)

        if len(price_highs) >= 2 and len(rsi_highs) >= 2:
            ph1, ph2 = price_highs[-2], price_highs[-1]
            rh1, rh2 = rsi_highs[-2], rsi_highs[-1]

            price_hh = close.iloc[ph2] > close.iloc[ph1]
            rsi_lh = rsi.iloc[rh2] < rsi.iloc[rh1]
            strength = abs(rsi.iloc[rh1] - rsi.iloc[rh2])
            recency_ok = ph2 > len(df) - 30

            if price_hh and rsi_lh and strength >= self.min_div_strength and recency_ok:
                return {
                    'divergence': 'BEARISH',
                    'type': 'Regular',
                    'strength': round(strength, 1),
                }

        return {'divergence': 'NONE', 'type': None, 'strength': 0}

    def analyze(self, df_1m: pd.DataFrame, symbol: str, df_1h=None) -> dict:
        """Analizza e genera segnale RSI Divergence."""
        if not self.enabled:
            return {
                'signal': 'HOLD',
                'strategy': 'rsi_divergence',
                'symbol': symbol,
                'score': 0,
                'reason': 'Strategia disabilitata'
            }

        if df_1m is None or len(df_1m) < 50:
            return {
                'signal': 'HOLD',
                'strategy': 'rsi_divergence',
                'symbol': symbol,
                'score': 0,
                'reason': 'Dati insufficienti'
            }

        div = self.detect_divergence(df_1m)
        close = float(df_1m['close'].iloc[-1])
        rsi_current = float(self.calculate_rsi(df_1m['close'], self.rsi_period).iloc[-1])

        # Filtro 1h bias
        bias_ok = True
        if df_1h is not None and len(df_1h) >= 50:
            ema50_1h = df_1h['close'].ewm(span=50).mean().iloc[-1]
            close_1h = df_1h['close'].iloc[-1]
            if div['divergence'] == 'BULLISH' and close_1h < ema50_1h * 0.985:
                bias_ok = False  # Downtrend forte su 1h, skip bullish div

        signal = 'HOLD'
        score = 0
        reason = f"RSI={rsi_current:.1f} | Div={div['divergence']}"

        if div['divergence'] == 'BULLISH' and bias_ok:
            if rsi_current < 45:  # Conferma che RSI è ancora in zona bassa
                signal = 'BUY'
                score = min(3, int(div['strength'] / 3))
                reason = f"Bullish div (strength={div['strength']}) RSI={rsi_current:.1f}"

        elif div['divergence'] == 'BEARISH':
            if rsi_current > 55:  # Conferma che RSI è ancora in zona alta
                signal = 'SELL'
                score = min(3, int(div['strength'] / 3))
                reason = f"Bearish div (strength={div['strength']}) RSI={rsi_current:.1f}"

        logger.info(f"[{symbol}] RSI Divergence: {signal} ({score}) | {reason}")

        return {
            'signal': signal,
            'score': score,
            'strategy': 'rsi_divergence',
            'symbol': symbol,
            'rsi_current': rsi_current,
            'divergence_info': div,
            'bias_ok': bias_ok,
            'reason': reason,
            'timestamp': datetime.now().isoformat()
        }
