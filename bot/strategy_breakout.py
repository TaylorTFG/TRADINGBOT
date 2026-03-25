# ============================================================
# STRATEGIA 2: BOLLINGER BAND SQUEEZE SCALPING (1min)
# Entra quando le Bollinger Bands si comprimono (squeeze)
# poi esce quando il prezzo rompe la banda con volume
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


class BreakoutStrategy:
    """
    Bollinger Band Squeeze Scalping Strategy.

    Su candele 1min:
    - Bollinger Bands periodo 20, std 2.0
    - Squeeze detection: bandwidth < 0.5%
    - Breakout: prezzo rompe BB_upper o BB_lower + volume spike
    - Mean reversion: prezzo tocca BB + RSI extreme

    Target: BB_middle (dynamic)
    """

    def __init__(self, config: dict):
        """Inizializza la strategia Bollinger Squeeze."""
        self.config = config
        self.strategy_config = config.get('strategy_breakout', {})
        self.enabled = self.strategy_config.get('enabled', True)

        # Parametri Bollinger Bands
        bb_cfg = self.strategy_config.get('bollinger', {})
        self.bb_period = bb_cfg.get('period', 20)
        self.bb_std = bb_cfg.get('std_dev', 2.0)

        # Squeeze threshold
        squeeze_cfg = self.strategy_config.get('squeeze', {})
        self.squeeze_threshold = squeeze_cfg.get('bandwidth_threshold', 0.005)  # 0.5%

        # Breakout confirmation
        breakout_cfg = self.strategy_config.get('breakout', {})
        self.breakout_volume_mult = breakout_cfg.get('volume_multiplier', 1.5)

        # Mean reversion RSI
        mean_rev = self.strategy_config.get('mean_reversion', {})
        self.rsi_oversold = mean_rev.get('rsi_oversold', 30)
        self.rsi_overbought = mean_rev.get('rsi_overbought', 70)

        logger.info(f"BreakoutStrategy (Bollinger Squeeze) inizializzata")

    def calculate_bollinger_squeeze(self, df: pd.DataFrame) -> Optional[pd.DataFrame]:
        """
        Calcola Bollinger Bands e metriche squeeze.

        Args:
            df: DataFrame con OHLCV

        Returns:
            DataFrame con BB e bandwidth
        """
        if df is None or len(df) < self.bb_period + 5:
            return None

        df = df.copy()
        close = df['close']

        try:
            if TA_AVAILABLE:
                bb = ta.volatility.BollingerBands(
                    close,
                    window=self.bb_period,
                    window_dev=self.bb_std
                )
                df.loc[:, 'bb_upper'] = bb.bollinger_hband()
                df.loc[:, 'bb_lower'] = bb.bollinger_lband()
                df.loc[:, 'bb_middle'] = bb.bollinger_mavg()
            else:
                # Bollinger Bands manuale
                df.loc[:, 'bb_middle'] = close.rolling(window=self.bb_period).mean()
                std = close.rolling(window=self.bb_period).std()
                df.loc[:, 'bb_upper'] = df['bb_middle'] + (std * self.bb_std)
                df.loc[:, 'bb_lower'] = df['bb_middle'] - (std * self.bb_std)

            # Calcola bandwidth (larghezza della banda)
            df.loc[:, 'bb_width'] = df['bb_upper'] - df['bb_lower']
            df.loc[:, 'bb_middle_safe'] = df['bb_middle'].replace(0, 1)
            df.loc[:, 'bandwidth_pct'] = df['bb_width'] / df['bb_middle_safe']

            # RSI per mean reversion
            delta = close.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=7).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=7).mean()
            rs = gain / loss.replace(0, np.finfo(float).eps)
            df.loc[:, 'rsi'] = 100 - (100 / (1 + rs))

            # Volume ratio
            df.loc[:, 'volume_ma'] = df['volume'].rolling(window=10).mean()
            df.loc[:, 'volume_ratio'] = df['volume'] / df['volume_ma'].replace(0, 1)

            return df

        except Exception as e:
            logger.error(f"Errore calcolo Bollinger Bands: {e}")
            return None

    def analyze(self, df_5min: pd.DataFrame, df_daily: pd.DataFrame, symbol: str) -> Dict:
        """
        Analizza squeeze e breakout Bollinger Bands.

        Logica:
        1. Squeeze detection: bandwidth < 0.5% → aspetta breakout
        2. Breakout: prezzo rompe BB + volume spike → entrata
        3. Mean reversion: prezzo tange BB + RSI extreme → entrata
        """
        if not self.enabled:
            return {'signal': 'HOLD', 'score': 0, 'reason': 'Strategia disabilitata'}

        # Usa il DataFrame passato (df_5min, che contiene dati 1min dall'engine)
        df = self.calculate_bollinger_squeeze(df_5min)

        if df is None or len(df) < 2:
            return {'signal': 'HOLD', 'score': 0, 'reason': 'Dati insufficienti'}

        last = df.iloc[-1]
        prev = df.iloc[-2]

        close = float(last.get('close', 0))
        bb_upper = float(last.get('bb_upper', 0))
        bb_lower = float(last.get('bb_lower', 0))
        bb_middle = float(last.get('bb_middle', 0))
        bandwidth_pct = float(last.get('bandwidth_pct', 1.0))
        rsi = float(last.get('rsi', 50))
        volume_ratio = float(last.get('volume_ratio', 1.0))

        prev_close = float(prev.get('close', 0))

        signal = 'HOLD'
        score = 0
        squeeze_status = 'NORMAL'
        details = {}

        # ---- 1. Squeeze Detection ----
        is_squeeze = bandwidth_pct < self.squeeze_threshold
        squeeze_status = f"SQUEEZE ({bandwidth_pct*100:.2f}%)" if is_squeeze else f"NORMAL ({bandwidth_pct*100:.2f}%)"
        details['squeeze_status'] = squeeze_status

        # ---- 2. Breakout (squeeze breakout oppure normale) ----
        # BUY: prezzo rompe sopra BB_upper + volume spike
        if close > bb_upper and prev_close <= bb_upper:
            details['breakout'] = f"BULLISH (price > BB_upper: {close:.2f} > {bb_upper:.2f})"

            # Volume confirmation
            if volume_ratio >= self.breakout_volume_mult:
                score += 2
                details['volume'] = f"OK ({volume_ratio:.2f}x)"
            else:
                score += 1
                details['volume'] = f"LOW ({volume_ratio:.2f}x)"

            # RSI check: non troppo overbought
            if rsi < self.rsi_overbought:
                score += 1
                details['rsi'] = f"OK ({rsi:.1f})"
            else:
                details['rsi'] = f"OVERBOUGHT ({rsi:.1f})"

            if score >= 2:
                signal = 'BUY'
                details['logic'] = "Breakout bullish + volume"

        # SELL: prezzo rompe sotto BB_lower + volume spike
        elif close < bb_lower and prev_close >= bb_lower:
            details['breakout'] = f"BEARISH (price < BB_lower: {close:.2f} < {bb_lower:.2f})"

            # Volume confirmation
            if volume_ratio >= self.breakout_volume_mult:
                score += 2
                details['volume'] = f"OK ({volume_ratio:.2f}x)"
            else:
                score += 1
                details['volume'] = f"LOW ({volume_ratio:.2f}x)"

            # RSI check: non troppo oversold
            if rsi > self.rsi_oversold:
                score += 1
                details['rsi'] = f"OK ({rsi:.1f})"
            else:
                details['rsi'] = f"OVERSOLD ({rsi:.1f})"

            if score >= 2:
                signal = 'SELL'
                details['logic'] = "Breakdown bearish + volume"

        # ---- 3. Mean Reversion (se no breakout) ----
        else:
            # BUY: prezzo tocca BB_lower + RSI oversold (rimbalzo dal basso)
            if (close <= bb_lower * 1.005 and  # Entro 0.5% da BB_lower
                    rsi < self.rsi_oversold and
                    volume_ratio >= 1.0):
                score = 2
                signal = 'BUY'
                details['logic'] = "Mean reversion: BB_lower touch + oversold RSI"
                details['rsi'] = f"OVERSOLD ({rsi:.1f})"

            # SELL: prezzo tocca BB_upper + RSI overbought (rimbalzo dal alto)
            elif (close >= bb_upper * 0.995 and  # Entro 0.5% da BB_upper
                    rsi > self.rsi_overbought and
                    volume_ratio >= 1.0):
                score = 2
                signal = 'SELL'
                details['logic'] = "Mean reversion: BB_upper touch + overbought RSI"
                details['rsi'] = f"OVERBOUGHT ({rsi:.1f})"

            # No signal
            else:
                if close > bb_lower and close < bb_upper:
                    bb_pct = (close - bb_lower) / (bb_upper - bb_lower) if (bb_upper - bb_lower) > 0 else 0.5
                    details['position'] = f"Middle zone ({bb_pct*100:.0f}%)"
                else:
                    details['position'] = "Outside BB bands"

        result = {
            'signal': signal,
            'score': score,
            'strategy': 'breakout',
            'symbol': symbol,
            'timestamp': datetime.now().isoformat(),
            'details': details,
            'indicators': {
                'close': close,
                'bb_upper': bb_upper,
                'bb_middle': bb_middle,
                'bb_lower': bb_lower,
                'bandwidth_pct': bandwidth_pct,
                'squeeze_detected': is_squeeze,
                'rsi': rsi,
                'volume_ratio': volume_ratio,
            }
        }

        logger.info(
            f"[{symbol}] Bollinger Squeeze: {signal} ({score}) | "
            f"Price={close:.2f} | Squeeze={squeeze_status} | RSI={rsi:.1f}"
        )
        return result
