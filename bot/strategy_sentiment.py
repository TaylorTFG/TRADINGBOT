# ============================================================
# STRATEGIA 3: VWAP MOMENTUM SCALPING (1min)
# Incrocia il prezzo con VWAP per identificare momentum
# Conferma con MACD veloce (5,13,5)
# ============================================================

import logging
import pandas as pd
import numpy as np
import warnings
from typing import Optional, Dict
from datetime import datetime

# Silenzio FutureWarning di Pandas (ChainedAssignment) per log puliti
warnings.filterwarnings('ignore', category=FutureWarning)

logger = logging.getLogger(__name__)


class SentimentStrategy:
    """
    VWAP Momentum Scalping Strategy.

    Su candele 1min:
    - VWAP calcolato su tutta la giornata (reset ogni inizio giornata)
    - MACD(5,13,5) per momentum bullish/bearish
    - Zone proximity: operare solo se price entro 0.3% VWAP

    Segnali:
    - BUY: Prezzo sale da sotto VWAP a sopra VWAP + MACD bullish
    - SELL: Prezzo scende da sopra VWAP a sotto VWAP + MACD bearish
    """

    def __init__(self, news_analyzer, config: dict):
        """Inizializza la strategia VWAP Momentum."""
        self.news_analyzer = news_analyzer  # Mantenuto per compatibilità API
        self.config = config
        self.strategy_config = config.get('strategy_sentiment', {})
        self.enabled = self.strategy_config.get('enabled', True)

        # Parametri VWAP
        vwap_cfg = self.strategy_config.get('vwap', {})
        self.reset_daily = vwap_cfg.get('reset_daily', True)
        self.price_proximity_pct = vwap_cfg.get('price_proximity_pct', 0.003)  # 0.3%

        # Parametri MACD (veloce per scalping)
        macd_cfg = self.strategy_config.get('macd', {})
        self.macd_fast = macd_cfg.get('fast_period', 5)
        self.macd_slow = macd_cfg.get('slow_period', 13)
        self.macd_signal = macd_cfg.get('signal_period', 5)

        # Soglie momentum
        self.bullish_threshold = self.strategy_config.get('bullish_threshold', 0.1)
        self.bearish_threshold = self.strategy_config.get('bearish_threshold', -0.1)

        logger.info(f"SentimentStrategy (VWAP Momentum) inizializzata")

    def calculate_vwap(self, df: pd.DataFrame) -> Optional[pd.Series]:
        """
        Calcola SESSION VWAP (Volume Weighted Average Price).

        Per crypto: sessione = da 00:00 UTC ogni giorno
        VWAP = cumsum(close * volume) / cumsum(volume)

        Args:
            df: DataFrame con OHLCV e timestamp index

        Returns:
            Serie pandas con valori VWAP, reindexed al df originale
        """
        if df is None or len(df) < 2:
            return None

        try:
            df = df.copy()

            # Filtra per includere solo candele dalla sessione corrente (00:00 UTC)
            from datetime import datetime
            from zoneinfo import ZoneInfo

            session_start = datetime.now(ZoneInfo('UTC')).replace(
                hour=0, minute=0, second=0, microsecond=0
            )

            session_df = df[df.index >= session_start] if hasattr(df.index, 'tz_localize') or df.index.tz else df

            # Fallback: se sessione insufficiente (<5 candele), usa ultime 120 candele (2 ore)
            if len(session_df) < 5:
                session_df = df.tail(120)

            # Calcola VWAP su session_df
            typical_price = (session_df['high'] + session_df['low'] + session_df['close']) / 3
            vwap_values = (typical_price * session_df['volume']).cumsum() / session_df['volume'].cumsum()

            # Reindex al df originale con forward fill per allineamento
            vwap = vwap_values.reindex(df.index, method='ffill')

            return vwap

        except Exception as e:
            logger.error(f"Errore calcolo session VWAP: {e}")
            # Fallback: VWAP su tutto il df
            try:
                df = df.copy()
                typical_price = (df['high'] + df['low'] + df['close']) / 3
                vwap = (typical_price * df['volume']).cumsum() / df['volume'].cumsum()
                return vwap
            except:
                return None

    def calculate_macd(self, df: pd.DataFrame) -> Dict:
        """
        Calcola MACD veloce (5,13,5) per momentum.

        Args:
            df: DataFrame con OHLCV

        Returns:
            Dizionario con macd, signal, histogram, direction
        """
        if df is None or len(df) < max(self.macd_slow, self.macd_signal) + 5:
            return {'macd': None, 'signal': None, 'hist': None, 'direction': 'NEUTRAL'}

        try:
            close = df['close']

            # MACD manuale
            ema_fast = close.ewm(span=self.macd_fast, adjust=False).mean()
            ema_slow = close.ewm(span=self.macd_slow, adjust=False).mean()
            macd = ema_fast - ema_slow
            signal = macd.ewm(span=self.macd_signal, adjust=False).mean()
            histogram = macd - signal

            # Valori attuali
            macd_val = float(macd.iloc[-1]) if pd.notna(macd.iloc[-1]) else 0
            signal_val = float(signal.iloc[-1]) if pd.notna(signal.iloc[-1]) else 0
            hist_val = float(histogram.iloc[-1]) if pd.notna(histogram.iloc[-1]) else 0

            # Crossover detection
            macd_prev = float(macd.iloc[-2]) if len(macd) > 1 and pd.notna(macd.iloc[-2]) else 0
            signal_prev = float(signal.iloc[-2]) if len(signal) > 1 and pd.notna(signal.iloc[-2]) else 0

            bullish_cross = (macd_prev <= signal_prev) and (macd_val > signal_val)
            bearish_cross = (macd_prev >= signal_prev) and (macd_val < signal_val)

            # Direction
            if bullish_cross:
                direction = 'BULLISH_CROSS'
            elif bearish_cross:
                direction = 'BEARISH_CROSS'
            elif macd_val > signal_val:
                direction = 'BULLISH'
            elif macd_val < signal_val:
                direction = 'BEARISH'
            else:
                direction = 'NEUTRAL'

            return {
                'macd': macd_val,
                'signal': signal_val,
                'hist': hist_val,
                'direction': direction,
                'bullish_cross': bullish_cross,
                'bearish_cross': bearish_cross,
            }

        except Exception as e:
            logger.error(f"Errore calcolo MACD: {e}")
            return {'macd': None, 'signal': None, 'hist': None, 'direction': 'NEUTRAL'}

    def analyze(self, df: pd.DataFrame, symbol: str) -> Dict:
        """
        Analizza VWAP crossover con confirma MACD.

        Logica SCALPING:
        - BUY: Prezzo sopra VWAP + MACD bullish + prezzo entro 0.3% VWAP
        - SELL: Prezzo sotto VWAP + MACD bearish + prezzo entro 0.3% VWAP
        """
        if not self.enabled:
            return {
                'signal': 'HOLD',
                'strategy': 'sentiment',
                'symbol': symbol,
                'reason': 'Strategia disabilitata'
            }

        if df is None or len(df) < 2:
            return {
                'signal': 'HOLD',
                'strategy': 'sentiment',
                'symbol': symbol,
                'sentiment_score': 0,
                'reason': 'Dati insufficienti'
            }

        # ---- Calcola VWAP ----
        vwap_series = self.calculate_vwap(df)
        if vwap_series is None or vwap_series.empty:
            return {
                'signal': 'HOLD',
                'strategy': 'sentiment',
                'symbol': symbol,
                'sentiment_score': 0,
                'reason': 'Impossibile calcolare VWAP'
            }

        last = df.iloc[-1]
        prev = df.iloc[-2]

        close = float(last.get('close', 0))
        prev_close = float(prev.get('close', 0))
        vwap = float(vwap_series.iloc[-1])
        prev_vwap = float(vwap_series.iloc[-2])

        # ---- Calcola MACD ----
        macd_result = self.calculate_macd(df)

        # ---- Proximity Filter ----
        # Operare solo se prezzo è entro 0.3% dal VWAP
        proximity = abs(close - vwap) / vwap if vwap > 0 else 1.0
        proximity_ok = proximity <= self.price_proximity_pct

        details = {
            'vwap': f"{vwap:.2f}",
            'proximity': f"{proximity*100:.3f}%",
            'proximity_ok': proximity_ok,
            'macd': macd_result['direction'],
        }

        # ---- SEGNALE ----
        signal = 'HOLD'
        sentiment_score = 0
        reason = ''

        if not proximity_ok:
            # Prezzo troppo lontano da VWAP
            reason = f"Price too far from VWAP ({proximity*100:.3f}% > {self.price_proximity_pct*100:.3f}%)"
            details['reason'] = reason
            return {
                'signal': 'HOLD',
                'strategy': 'sentiment',
                'symbol': symbol,
                'sentiment_score': 0,
                'reason': reason,
                'details': details,
                'timestamp': datetime.now().isoformat()
            }

        # ---- BUY: Prezzo sopra VWAP + MACD bullish ----
        if close > vwap:  # Prezzo è sopra VWAP
            if macd_result['direction'] in ['BULLISH', 'BULLISH_CROSS']:
                signal = 'BUY'
                sentiment_score = 0.5 if macd_result['direction'] == 'BULLISH_CROSS' else 0.3
                reason = "VWAP bullish crossover + MACD momentum"

                # Bonus se è un crossover
                if macd_result['bullish_cross']:
                    sentiment_score = 0.8
                    details['strength'] = 'STRONG (crossover detected)'

        # ---- SELL: Prezzo sotto VWAP + MACD bearish ----
        elif close < vwap:  # Prezzo è sotto VWAP
            if macd_result['direction'] in ['BEARISH', 'BEARISH_CROSS']:
                signal = 'SELL'
                sentiment_score = -0.5 if macd_result['direction'] == 'BEARISH_CROSS' else -0.3
                reason = "VWAP bearish crossover + MACD momentum"

                # Bonus se è un crossover
                if macd_result['bearish_cross']:
                    sentiment_score = -0.8
                    details['strength'] = 'STRONG (crossover detected)'

        else:
            # Prezzo approssimativamente al VWAP
            reason = "Price at VWAP level - awaiting crossover"

        logger.info(
            f"[{symbol}] VWAP Momentum: {signal} | "
            f"Price={close:.2f}, VWAP={vwap:.2f} | "
            f"MACD={macd_result['direction']} | Proximity={proximity*100:.3f}%"
        )

        return {
            'signal': signal,
            'strategy': 'sentiment',
            'symbol': symbol,
            'timestamp': datetime.now().isoformat(),
            'sentiment_score': sentiment_score,
            'sentiment_classification': 'VWAP_MOMENTUM',
            'article_count': 0,  # N/A per VWAP
            'confidence': min(0.9, abs(sentiment_score) + 0.1),
            'reason': reason,
            'details': details,
            'indicators': {
                'vwap': vwap,
                'close': close,
                'distance_from_vwap': proximity,
                'macd': macd_result['macd'],
                'macd_signal': macd_result['signal'],
                'macd_histogram': macd_result['hist'],
            }
        }
