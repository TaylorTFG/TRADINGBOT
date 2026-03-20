# ============================================================
# STRATEGIA 1: MULTI-INDICATOR CONFLUENCE
# Opera solo quando almeno 3 indicatori su 5 concordano:
# RSI, MACD, Bollinger Bands, EMA crossover, Volume
# ============================================================

import logging
import pandas as pd
import numpy as np
from typing import Optional, Dict, Tuple
from datetime import datetime

try:
    import ta
    TA_AVAILABLE = True
except ImportError:
    TA_AVAILABLE = False
    logging.warning("Libreria 'ta' non disponibile. Calcoli manuali attivati.")

logger = logging.getLogger(__name__)


class ConfluenceStrategy:
    """
    Strategia di confluenza multi-indicatore.

    Calcola un punteggio da 0 a 5 basato su:
    - RSI(14): ipervenduto/ipercomprato
    - MACD(12,26,9): crossover bullish/bearish
    - Bollinger Bands(20,2): prezzo fuori banda
    - EMA crossover (20/50): trend rialzista/ribassista
    - Volume: conferma con volume superiore alla media

    Opera solo se il punteggio >= soglia minima (default 3/5)
    """

    def __init__(self, config: dict):
        """
        Inizializza la strategia di confluenza.

        Args:
            config: Configurazione dal config.yaml
        """
        self.config = config
        self.strategy_config = config.get('strategy_confluence', {})
        self.min_score = self.strategy_config.get('min_score', 3)
        self.enabled = self.strategy_config.get('enabled', True)

        # Parametri RSI
        rsi_cfg = self.strategy_config.get('rsi', {})
        self.rsi_period = rsi_cfg.get('period', 14)
        self.rsi_oversold = rsi_cfg.get('oversold', 30)
        self.rsi_overbought = rsi_cfg.get('overbought', 70)

        # Parametri MACD
        macd_cfg = self.strategy_config.get('macd', {})
        self.macd_fast = macd_cfg.get('fast_period', 12)
        self.macd_slow = macd_cfg.get('slow_period', 26)
        self.macd_signal = macd_cfg.get('signal_period', 9)

        # Parametri Bollinger Bands
        bb_cfg = self.strategy_config.get('bollinger', {})
        self.bb_period = bb_cfg.get('period', 20)
        self.bb_std = bb_cfg.get('std_dev', 2)

        # Parametri EMA
        ema_cfg = self.strategy_config.get('ema', {})
        self.ema_fast = ema_cfg.get('fast_period', 20)
        self.ema_slow = ema_cfg.get('slow_period', 50)

        # Parametri Volume
        vol_cfg = self.strategy_config.get('volume', {})
        self.vol_period = vol_cfg.get('lookback_period', 20)
        self.vol_multiplier = vol_cfg.get('multiplier', 1.5)

        logger.info(f"ConfluenceStrategy inizializzata (soglia: {self.min_score}/5)")

    def calculate_indicators(self, df: pd.DataFrame) -> Optional[pd.DataFrame]:
        """
        Calcola tutti gli indicatori tecnici sul DataFrame.

        Args:
            df: DataFrame con colonne OHLCV (open, high, low, close, volume)

        Returns:
            DataFrame con gli indicatori calcolati
        """
        if df is None or len(df) < max(self.ema_slow, self.bb_period, self.vol_period) + 10:
            logger.warning("Dati insufficienti per calcolare gli indicatori")
            return None

        df = df.copy()

        try:
            close = df['close']
            high = df['high']
            low = df['low']
            volume = df['volume']

            if TA_AVAILABLE:
                # RSI usando libreria ta
                df['rsi'] = ta.momentum.RSIIndicator(close, window=self.rsi_period).rsi()

                # MACD
                macd = ta.trend.MACD(
                    close,
                    window_fast=self.macd_fast,
                    window_slow=self.macd_slow,
                    window_sign=self.macd_signal
                )
                df['macd'] = macd.macd()
                df['macd_signal'] = macd.macd_signal()
                df['macd_hist'] = macd.macd_diff()

                # Bollinger Bands
                bb = ta.volatility.BollingerBands(
                    close,
                    window=self.bb_period,
                    window_dev=self.bb_std
                )
                df['bb_upper'] = bb.bollinger_hband()
                df['bb_middle'] = bb.bollinger_mavg()
                df['bb_lower'] = bb.bollinger_lband()

                # ATR (per risk management)
                df['atr'] = ta.volatility.AverageTrueRange(
                    high, low, close, window=14
                ).average_true_range()

                # ADX (per breakout strategy)
                adx = ta.trend.ADXIndicator(high, low, close, window=14)
                df['adx'] = adx.adx()

            else:
                # Calcoli manuali come fallback
                df = self._calculate_manual(df)

            # EMA calcolata sempre manualmente (più semplice)
            df[f'ema_{self.ema_fast}'] = close.ewm(span=self.ema_fast, adjust=False).mean()
            df[f'ema_{self.ema_slow}'] = close.ewm(span=self.ema_slow, adjust=False).mean()
            df['ema200'] = close.ewm(span=200, adjust=False).mean()

            # Volume media mobile
            df['volume_ma'] = volume.rolling(window=self.vol_period).mean()
            df['volume_ratio'] = volume / df['volume_ma']

            return df

        except Exception as e:
            logger.error(f"Errore calcolo indicatori: {e}")
            return None

    def _calculate_manual(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calcolo manuale degli indicatori senza libreria ta."""
        close = df['close']
        high = df['high']
        low = df['low']

        # RSI manuale
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=self.rsi_period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=self.rsi_period).mean()
        rs = gain / loss.replace(0, np.finfo(float).eps)
        df['rsi'] = 100 - (100 / (1 + rs))

        # MACD manuale
        ema_fast = close.ewm(span=self.macd_fast, adjust=False).mean()
        ema_slow = close.ewm(span=self.macd_slow, adjust=False).mean()
        df['macd'] = ema_fast - ema_slow
        df['macd_signal'] = df['macd'].ewm(span=self.macd_signal, adjust=False).mean()
        df['macd_hist'] = df['macd'] - df['macd_signal']

        # Bollinger Bands manuale
        df['bb_middle'] = close.rolling(window=self.bb_period).mean()
        std = close.rolling(window=self.bb_period).std()
        df['bb_upper'] = df['bb_middle'] + (std * self.bb_std)
        df['bb_lower'] = df['bb_middle'] - (std * self.bb_std)

        # ATR manuale
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df['atr'] = true_range.rolling(window=14).mean()

        # ADX semplificato
        df['adx'] = 25.0  # Valore neutro se non calcolabile

        return df

    def analyze(self, df: pd.DataFrame, symbol: str) -> Dict:
        """
        Analizza i dati e genera il segnale di trading.

        Args:
            df: DataFrame con dati OHLCV
            symbol: Simbolo dell'asset

        Returns:
            Dizionario con signal, score, details
        """
        if not self.enabled:
            return {'signal': 'HOLD', 'score': 0, 'reason': 'Strategia disabilitata'}

        # Calcola indicatori
        df = self.calculate_indicators(df)
        if df is None or df.empty:
            return {'signal': 'HOLD', 'score': 0, 'reason': 'Dati insufficienti'}

        # Prendi l'ultima riga
        last = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else last

        # Calcola punteggio BUY e SELL
        buy_score = 0
        sell_score = 0
        details = {}

        # ---- INDICATORE 1: RSI ----
        rsi = last.get('rsi', 50)
        if pd.notna(rsi):
            if rsi < self.rsi_oversold:
                buy_score += 1
                details['rsi'] = f"BUY ({rsi:.1f} < {self.rsi_oversold})"
            elif rsi > self.rsi_overbought:
                sell_score += 1
                details['rsi'] = f"SELL ({rsi:.1f} > {self.rsi_overbought})"
            else:
                details['rsi'] = f"NEUTRAL ({rsi:.1f})"
        else:
            details['rsi'] = "N/A"

        # ---- INDICATORE 2: MACD ----
        macd = last.get('macd', 0)
        macd_sig = last.get('macd_signal', 0)
        prev_macd = prev.get('macd', 0)
        prev_macd_sig = prev.get('macd_signal', 0)

        if pd.notna(macd) and pd.notna(macd_sig):
            # Crossover bullish: MACD passa da sotto a sopra la linea signal
            bullish_cross = (prev_macd <= prev_macd_sig) and (macd > macd_sig)
            bearish_cross = (prev_macd >= prev_macd_sig) and (macd < macd_sig)

            if bullish_cross:
                buy_score += 1
                details['macd'] = f"BUY (crossover rialzista)"
            elif bearish_cross:
                sell_score += 1
                details['macd'] = f"SELL (crossover ribassista)"
            elif macd > macd_sig:
                buy_score += 0.5
                details['macd'] = f"BULLISH ({macd:.4f} > {macd_sig:.4f})"
            else:
                details['macd'] = f"NEUTRAL ({macd:.4f})"
        else:
            details['macd'] = "N/A"

        # ---- INDICATORE 3: BOLLINGER BANDS ----
        close = last.get('close', 0)
        bb_lower = last.get('bb_lower', 0)
        bb_upper = last.get('bb_upper', 0)
        bb_middle = last.get('bb_middle', 0)

        if pd.notna(bb_lower) and pd.notna(bb_upper) and close > 0:
            if close < bb_lower:
                buy_score += 1
                details['bollinger'] = f"BUY (sotto banda inf: {close:.2f} < {bb_lower:.2f})"
            elif close > bb_upper:
                sell_score += 1
                details['bollinger'] = f"SELL (sopra banda sup: {close:.2f} > {bb_upper:.2f})"
            else:
                bb_pct = (close - bb_lower) / (bb_upper - bb_lower) if (bb_upper - bb_lower) > 0 else 0.5
                details['bollinger'] = f"NEUTRAL (posizione: {bb_pct:.1%})"
        else:
            details['bollinger'] = "N/A"

        # ---- INDICATORE 4: EMA CROSSOVER ----
        ema_fast_val = last.get(f'ema_{self.ema_fast}', 0)
        ema_slow_val = last.get(f'ema_{self.ema_slow}', 0)
        prev_ema_fast = prev.get(f'ema_{self.ema_fast}', 0)
        prev_ema_slow = prev.get(f'ema_{self.ema_slow}', 0)

        if pd.notna(ema_fast_val) and pd.notna(ema_slow_val) and ema_fast_val > 0:
            if ema_fast_val > ema_slow_val:
                buy_score += 1
                details['ema'] = f"BUY (EMA{self.ema_fast} > EMA{self.ema_slow})"
            else:
                sell_score += 1
                details['ema'] = f"SELL (EMA{self.ema_fast} < EMA{self.ema_slow})"
        else:
            details['ema'] = "N/A"

        # ---- INDICATORE 5: VOLUME ----
        volume_ratio = last.get('volume_ratio', 1)
        if pd.notna(volume_ratio):
            if volume_ratio > self.vol_multiplier:
                # Volume alto: amplifica il segnale dominante
                if buy_score > sell_score:
                    buy_score += 1
                    details['volume'] = f"BUY CONFIRM ({volume_ratio:.1f}x media)"
                elif sell_score > buy_score:
                    sell_score += 1
                    details['volume'] = f"SELL CONFIRM ({volume_ratio:.1f}x media)"
                else:
                    details['volume'] = f"HIGH ({volume_ratio:.1f}x media)"
            else:
                details['volume'] = f"LOW ({volume_ratio:.1f}x media)"
        else:
            details['volume'] = "N/A"

        # ---- DECISIONE FINALE ----
        buy_score = round(buy_score)
        sell_score = round(sell_score)

        if buy_score >= self.min_score and buy_score > sell_score:
            signal = 'BUY'
            score = buy_score
        elif sell_score >= self.min_score and sell_score > buy_score:
            signal = 'SELL'
            score = sell_score
        else:
            signal = 'HOLD'
            score = max(buy_score, sell_score)

        result = {
            'signal': signal,
            'score': score,
            'buy_score': buy_score,
            'sell_score': sell_score,
            'max_score': 5,
            'min_required': self.min_score,
            'symbol': symbol,
            'strategy': 'confluence',
            'timestamp': datetime.now().isoformat(),
            'details': details,
            'indicators': {
                'rsi': float(rsi) if pd.notna(rsi) else None,
                'macd': float(macd) if pd.notna(macd) else None,
                'bb_pct': float((close - bb_lower) / (bb_upper - bb_lower)) if (bb_upper and bb_lower and bb_upper != bb_lower) else None,
                'ema_trend': 'up' if (ema_fast_val and ema_slow_val and ema_fast_val > ema_slow_val) else 'down',
                'volume_ratio': float(volume_ratio) if pd.notna(volume_ratio) else None,
                'atr': float(last.get('atr', 0)) if pd.notna(last.get('atr', 0)) else None,
                'adx': float(last.get('adx', 0)) if pd.notna(last.get('adx', 0)) else None,
                'close': float(close),
            }
        }

        logger.info(f"[{symbol}] Confluence: {signal} ({score}/5) - {', '.join([f'{k}:{v[:10]}' for k,v in details.items()])}")
        return result
