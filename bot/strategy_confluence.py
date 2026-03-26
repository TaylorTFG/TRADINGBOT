# ============================================================
# STRATEGIA 1: EMA CROSSOVER SCALPING (1min)
# Optimized for crypto scalping: fast MA crosses with RSI confirmation
# ============================================================

import logging
import pandas as pd
import numpy as np
import warnings
from typing import Optional, Dict
from datetime import datetime

# Silenzio FutureWarning di Pandas (ChainedAssignment) per log puliti
warnings.filterwarnings('ignore', category=FutureWarning)

try:
    import ta
    TA_AVAILABLE = True
except ImportError:
    TA_AVAILABLE = False
    logging.warning("Libreria 'ta' non disponibile. Calcoli manuali attivati.")

logger = logging.getLogger(__name__)


class ConfluenceStrategy:
    """
    EMA Crossover Scalping Strategy.

    Per candele 1min:
    - EMA 5 (molto veloce)
    - EMA 13 (veloce)
    - EMA 50 (trend general)
    - RSI periodo 7 (molto reattivo)
    - ATR per escludere mercati piatti (<0.05%)
    - Volume: >120% media 10 periodi

    Segnali:
    - BUY: EMA5 incrocia sopra EMA13 + RSI < 35 + Volume > 120%
    - SELL: EMA5 incrocia sotto EMA13 + RSI > 65 + Volume > 120%
    - HOLD: Nessun crossover valido
    """

    def __init__(self, config: dict):
        """Inizializza la strategia EMA Crossover."""
        self.config = config
        self.strategy_config = config.get('strategy_confluence', {})
        self.min_score = self.strategy_config.get('min_score', 2)
        self.enabled = self.strategy_config.get('enabled', True)

        # Parametri RSI (SCALPING: periodo 7, molto reattivo)
        rsi_cfg = self.strategy_config.get('rsi', {})
        self.rsi_period = rsi_cfg.get('period', 7)
        self.rsi_oversold = rsi_cfg.get('oversold', 35)
        self.rsi_overbought = rsi_cfg.get('overbought', 65)

        # Parametri EMA (per scalping 1min)
        ema_cfg = self.strategy_config.get('ema', {})
        self.ema_fast = ema_cfg.get('fast_period', 5)        # EMA5 velocissima
        self.ema_mid = ema_cfg.get('slow_period', 13)        # EMA13 secondaria
        self.ema_trend = ema_cfg.get('trend_period', 50)     # EMA50 trend filter

        # Parametri ATR (per escludere mercati piatti)
        atr_cfg = self.strategy_config.get('atr', {})
        self.atr_period = atr_cfg.get('period', 7)
        self.min_volatility_pct = atr_cfg.get('min_volatility_pct', 0.0005)  # 0.05%

        # Parametri Volume
        vol_cfg = self.strategy_config.get('volume', {})
        self.vol_period = vol_cfg.get('lookback_period', 10)
        self.vol_multiplier = vol_cfg.get('multiplier', 1.2)   # 120%

        logger.info(f"ConfluenceStrategy (EMA Crossover) inizializzata")

    def calculate_indicators(self, df: pd.DataFrame) -> Optional[pd.DataFrame]:
        """Calcola indicatori per EMA Crossover Scalping."""
        if df is None or len(df) < max(self.ema_trend, self.vol_period) + 10:
            logger.warning("Dati insufficienti per calcolare gli indicatori")
            return None

        df = df.copy()

        try:
            close = df['close']
            high = df['high']
            low = df['low']
            volume = df['volume']

            # ---- EMA (core della strategia) ----
            df[f'ema_{self.ema_fast}'] = close.ewm(span=self.ema_fast, adjust=False).mean()
            df[f'ema_{self.ema_mid}'] = close.ewm(span=self.ema_mid, adjust=False).mean()
            df[f'ema_{self.ema_trend}'] = close.ewm(span=self.ema_trend, adjust=False).mean()

            # ---- RSI (confirmazione) ----
            if TA_AVAILABLE:
                df['rsi'] = ta.momentum.RSIIndicator(close, window=self.rsi_period).rsi()
            else:
                # RSI manuale
                delta = close.diff()
                gain = (delta.where(delta > 0, 0)).rolling(window=self.rsi_period).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(window=self.rsi_period).mean()
                rs = gain / loss.replace(0, np.finfo(float).eps)
                df['rsi'] = 100 - (100 / (1 + rs))

            # ---- ATR (per escludere mercati piatti) ----
            if TA_AVAILABLE:
                df['atr'] = ta.volatility.AverageTrueRange(
                    high, low, close, window=self.atr_period
                ).average_true_range()
            else:
                # ATR manuale
                tr1 = high - low
                tr2 = (high - close.shift(1)).abs()
                tr3 = (low - close.shift(1)).abs()
                true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
                df['atr'] = true_range.rolling(window=self.atr_period).mean()

            # ---- Volume (confirmazione segnale) ----
            df['volume_ma'] = volume.rolling(window=self.vol_period).mean()
            df['volume_ratio'] = volume / df['volume_ma'].replace(0, 1)

            return df

        except Exception as e:
            logger.error(f"Errore calcolo indicatori: {e}")
            return None

    def analyze(self, df: pd.DataFrame, symbol: str) -> Dict:
        """
        Analizza il crossover EMA con confirmazione RSI.

        Logica SCALPING:
        - BUY: EMA5 incrocia sopra EMA13 + RSI < 35 + Volume > 120% + ATR > min_vol
        - SELL: EMA5 incrocia sotto EMA13 + RSI > 65 + Volume > 120% + ATR > min_vol
        """
        if not self.enabled:
            return {'signal': 'HOLD', 'score': 0, 'reason': 'Strategia disabilitata'}

        # Calcola indicatori
        df = self.calculate_indicators(df)
        if df is None or df.empty or len(df) < 2:
            return {'signal': 'HOLD', 'score': 0, 'reason': 'Dati insufficienti'}

        # Prendi ultime 2 righe per crossover detection
        last = df.iloc[-1]
        prev = df.iloc[-2]

        close = float(last.get('close', 0))
        ema_fast = float(last.get(f'ema_{self.ema_fast}', 0))
        ema_mid = float(last.get(f'ema_{self.ema_mid}', 0))
        ema_trend = float(last.get(f'ema_{self.ema_trend}', 0))
        rsi = float(last.get('rsi', 50))
        atr = float(last.get('atr', 0))
        volume_ratio = float(last.get('volume_ratio', 1))

        prev_ema_fast = float(prev.get(f'ema_{self.ema_fast}', 0))
        prev_ema_mid = float(prev.get(f'ema_{self.ema_mid}', 0))

        details = {}
        signal = 'HOLD'
        score = 0
        buy_score = 0
        sell_score = 0

        # ---- 1. Check: Mercato non piatto (ATR > 0.05%) ----
        atr_pct = (atr / close * 100) if close > 0 else 0
        if atr_pct < (self.min_volatility_pct * 100):
            details['atr'] = f"SKIP (mercato piatto: {atr_pct:.3f}% < {self.min_volatility_pct*100:.3f}%)"
            return {
                'signal': 'HOLD',
                'score': 0,
                'reason': 'Mercato piatto - ATR insufficiente',
                'details': details
            }

        details['atr'] = f"OK ({atr_pct:.3f}%)"

        # ---- 2. Check: Volume (>120% media) ----
        # Check se volume_ratio è valido (non 0, non NaN)
        import numpy as np
        if (volume_ratio is None or volume_ratio == 0 or
            np.isnan(float(volume_ratio)) if isinstance(volume_ratio, (int, float)) else False):
            logger.warning(f"[{symbol}] Volume data missing or invalid ({volume_ratio}), skipping volume filter")
            details['volume'] = "SKIPPED (no volume data)"
            vol_ok = True  # Skip filter, assume OK
        elif volume_ratio < self.vol_multiplier:
            details['volume'] = f"LOW ({volume_ratio:.2f}x media)"
            # Se volume basso, riduci score
            vol_ok = False
        else:
            details['volume'] = f"OK ({volume_ratio:.2f}x media)"
            vol_ok = True

        # ---- 3. Crossover Detection ----
        bullish_cross = (prev_ema_fast <= prev_ema_mid) and (ema_fast > ema_mid)
        bearish_cross = (prev_ema_fast >= prev_ema_mid) and (ema_fast < ema_mid)

        # ---- BUY Signal ----
        if bullish_cross:
            details['crossover'] = f"BUY (EMA{self.ema_fast} > EMA{self.ema_mid})"

            if rsi < self.rsi_oversold:
                buy_score += 2
                details['rsi'] = f"BUY ({rsi:.1f} < {self.rsi_oversold})"
            elif rsi < 50:
                buy_score += 1
                details['rsi'] = f"NEUTRAL-BUY ({rsi:.1f})"
            else:
                buy_score += 0.5
                details['rsi'] = f"NEUTRAL ({rsi:.1f})"

            if vol_ok:
                buy_score += 1

            # Filtro trend: se EMA5 > EMA50, il trend è rialzista
            if ema_fast > ema_trend:
                buy_score += 0.5
                details['trend'] = "BULLISH"
            else:
                details['trend'] = "BEARISH (warning)"

            if buy_score >= self.min_score:
                signal = 'BUY'
                score = int(buy_score)

        # ---- SELL Signal ----
        elif bearish_cross:
            details['crossover'] = f"SELL (EMA{self.ema_fast} < EMA{self.ema_mid})"

            if rsi > self.rsi_overbought:
                sell_score += 2
                details['rsi'] = f"SELL ({rsi:.1f} > {self.rsi_overbought})"
            elif rsi > 50:
                sell_score += 1
                details['rsi'] = f"NEUTRAL-SELL ({rsi:.1f})"
            else:
                sell_score += 0.5
                details['rsi'] = f"NEUTRAL ({rsi:.1f})"

            if vol_ok:
                sell_score += 1

            # Filtro trend: se EMA5 < EMA50, il trend è ribassista
            if ema_fast < ema_trend:
                sell_score += 0.5
                details['trend'] = "BEARISH"
            else:
                details['trend'] = "BULLISH (warning)"

            if sell_score >= self.min_score:
                signal = 'SELL'
                score = int(sell_score)

        else:
            # Nessun crossover
            details['crossover'] = "NO_CROSS"
            if ema_fast > ema_mid:
                details['trend_direction'] = f"EMA{self.ema_fast} > EMA{self.ema_mid} (bullish trend, waiting for pullback)"
            else:
                details['trend_direction'] = f"EMA{self.ema_fast} < EMA{self.ema_mid} (bearish trend, waiting for bounce)"

        result = {
            'signal': signal,
            'score': score,
            'buy_score': buy_score,
            'sell_score': sell_score,
            'symbol': symbol,
            'strategy': 'confluence',
            'timestamp': datetime.now().isoformat(),
            'details': details,
            'indicators': {
                'ema_fast': ema_fast,
                'ema_mid': ema_mid,
                'ema_trend': ema_trend,
                'rsi': rsi,
                'atr_pct': atr_pct,
                'volume_ratio': volume_ratio,
                'close': close,
                'bullish_cross': bullish_cross,
                'bearish_cross': bearish_cross,
            }
        }

        logger.info(f"[{symbol}] EMA Crossover: {signal} ({score}) - {details.get('crossover', 'NO_CROSS')} | RSI={rsi:.1f} | Vol={volume_ratio:.2f}x")
        return result
