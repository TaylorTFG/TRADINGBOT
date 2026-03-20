# ============================================================
# STRATEGIA 2: BREAKOUT + MOMENTUM
# Entra quando il prezzo rompe livelli chiave con volume forte
# Usa ADX per filtrare i falsi segnali in mercati laterali
# ============================================================

import logging
import pandas as pd
import numpy as np
from typing import Optional, Dict, List, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)


class BreakoutStrategy:
    """
    Strategia di breakout con filtro momentum.

    Logica:
    1. Calcola supporti e resistenze sugli ultimi 20 giorni
    2. Identifica breakout quando il prezzo supera la resistenza
    3. Conferma con volume > 200% della media
    4. Filtra con ADX > 25 (trend forte, no laterale)
    5. Usa ATR per target e stop dinamici
    6. Anti falso breakout: aspetta chiusura candela sopra il livello
    """

    def __init__(self, config: dict):
        """
        Inizializza la strategia di breakout.

        Args:
            config: Configurazione dal config.yaml
        """
        self.config = config
        self.strategy_config = config.get('strategy_breakout', {})
        self.enabled = self.strategy_config.get('enabled', True)

        self.lookback_days = self.strategy_config.get('lookback_days', 20)
        self.volume_multiplier = self.strategy_config.get('volume_multiplier', 2.0)
        self.adx_min = self.strategy_config.get('adx_min', 25)
        self.atr_period = self.strategy_config.get('atr_period', 14)
        self.wait_candle_close = self.strategy_config.get('wait_candle_close', True)

        logger.info(f"BreakoutStrategy inizializzata (ADX min: {self.adx_min}, Vol: {self.volume_multiplier}x)")

    def find_support_resistance(self, df_daily: pd.DataFrame) -> Dict:
        """
        Calcola livelli chiave di supporto e resistenza.

        Usa due metodi:
        1. Massimi e minimi locali (pivot points)
        2. Livelli di prezzo ad alto volume (Volume Profile semplificato)

        Args:
            df_daily: DataFrame con dati giornalieri

        Returns:
            Dizionario con levels, support, resistance
        """
        if df_daily is None or len(df_daily) < 5:
            return {'support': [], 'resistance': [], 'levels': []}

        df = df_daily.tail(self.lookback_days).copy()

        # Metodo 1: Pivot Points (massimi e minimi locali)
        pivot_levels = []
        for i in range(2, len(df) - 2):
            # Massimo locale (resistenza)
            if (df['high'].iloc[i] > df['high'].iloc[i-1] and
                    df['high'].iloc[i] > df['high'].iloc[i-2] and
                    df['high'].iloc[i] > df['high'].iloc[i+1] and
                    df['high'].iloc[i] > df['high'].iloc[i+2]):
                pivot_levels.append({
                    'price': float(df['high'].iloc[i]),
                    'type': 'resistance',
                    'strength': 1
                })

            # Minimo locale (supporto)
            if (df['low'].iloc[i] < df['low'].iloc[i-1] and
                    df['low'].iloc[i] < df['low'].iloc[i-2] and
                    df['low'].iloc[i] < df['low'].iloc[i+1] and
                    df['low'].iloc[i] < df['low'].iloc[i+2]):
                pivot_levels.append({
                    'price': float(df['low'].iloc[i]),
                    'type': 'support',
                    'strength': 1
                })

        # Aggiungi high e low del periodo come livelli chiave
        period_high = float(df['high'].max())
        period_low = float(df['low'].min())
        current_price = float(df['close'].iloc[-1])

        pivot_levels.append({'price': period_high, 'type': 'resistance', 'strength': 2})
        pivot_levels.append({'price': period_low, 'type': 'support', 'strength': 2})

        # Separa support e resistance in base al prezzo attuale
        support_levels = sorted(
            [l['price'] for l in pivot_levels if l['price'] < current_price],
            reverse=True
        )[:5]  # Prendi i 5 più vicini sopra

        resistance_levels = sorted(
            [l['price'] for l in pivot_levels if l['price'] > current_price]
        )[:5]  # Prendi i 5 più vicini sotto

        return {
            'support': support_levels,
            'resistance': resistance_levels,
            'period_high': period_high,
            'period_low': period_low,
            'current_price': current_price,
            'all_levels': pivot_levels
        }

    def calculate_adx(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """
        Calcola ADX (Average Directional Index) manualmente.

        Args:
            df: DataFrame con OHLCV
            period: Periodo per il calcolo ADX

        Returns:
            Serie pandas con valori ADX
        """
        high = df['high']
        low = df['low']
        close = df['close']

        # True Range
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()

        # Directional Movement
        up_move = high - high.shift(1)
        down_move = low.shift(1) - low

        # +DM e -DM
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)

        plus_dm_series = pd.Series(plus_dm, index=df.index)
        minus_dm_series = pd.Series(minus_dm, index=df.index)

        # Smoothed +DM, -DM
        plus_di = 100 * plus_dm_series.rolling(window=period).mean() / atr.replace(0, np.finfo(float).eps)
        minus_di = 100 * minus_dm_series.rolling(window=period).mean() / atr.replace(0, np.finfo(float).eps)

        # DX e ADX
        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.finfo(float).eps)
        adx = dx.rolling(window=period).mean()

        return adx

    def detect_breakout(
        self,
        df_5min: pd.DataFrame,
        df_daily: pd.DataFrame,
        symbol: str
    ) -> Dict:
        """
        Rileva un breakout dal livello di resistenza o supporto.

        Args:
            df_5min: Dati su timeframe 5 minuti (per il segnale)
            df_daily: Dati giornalieri (per supporti/resistenze)
            symbol: Simbolo dell'asset

        Returns:
            Dizionario con signal, type (breakout/breakdown), details
        """
        if not self.enabled:
            return {'signal': 'HOLD', 'reason': 'Strategia disabilitata'}

        if df_5min is None or df_daily is None:
            return {'signal': 'HOLD', 'reason': 'Dati insufficienti'}

        if len(df_5min) < 30 or len(df_daily) < self.lookback_days:
            return {'signal': 'HOLD', 'reason': 'Dati storici insufficienti'}

        # Recupera i livelli chiave
        levels = self.find_support_resistance(df_daily)
        if not levels:
            return {'signal': 'HOLD', 'reason': 'Nessun livello trovato'}

        # Calcola ADX per verificare trend forte
        try:
            adx_series = self.calculate_adx(df_5min, self.atr_period)
            adx_current = float(adx_series.iloc[-1]) if not adx_series.empty else 0
        except Exception as e:
            logger.warning(f"Errore calcolo ADX: {e}")
            adx_current = 0

        # Calcola ATR
        try:
            tr = pd.concat([
                df_5min['high'] - df_5min['low'],
                (df_5min['high'] - df_5min['close'].shift(1)).abs(),
                (df_5min['low'] - df_5min['close'].shift(1)).abs()
            ], axis=1).max(axis=1)
            atr = float(tr.rolling(14).mean().iloc[-1])
        except Exception:
            atr = float(df_5min['close'].iloc[-1]) * 0.01  # 1% come fallback

        # Volume ratio
        volume_ma = df_5min['volume'].rolling(20).mean()
        current_volume = float(df_5min['volume'].iloc[-1])
        avg_volume = float(volume_ma.iloc[-1])
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1

        # Prezzi attuali
        current_close = float(df_5min['close'].iloc[-1])
        current_open = float(df_5min['open'].iloc[-1])
        prev_close = float(df_5min['close'].iloc[-2])

        # ---- VERIFICA BREAKOUT RIALZISTA ----
        signal = 'HOLD'
        breakout_type = None
        target_level = None
        details = {}

        for resistance in levels['resistance'][:3]:  # Controlla i 3 livelli più vicini
            # Il prezzo ha superato la resistenza?
            if current_close > resistance and prev_close <= resistance:
                # Conferma volume
                volume_confirmed = volume_ratio >= self.volume_multiplier

                # Filtro ADX (trend forte)
                adx_confirmed = adx_current >= self.adx_min

                # Anti falso breakout: la candela deve chiudersi sopra il livello
                candle_confirmed = current_close > resistance if self.wait_candle_close else True

                if volume_confirmed and candle_confirmed:
                    signal = 'BUY'
                    breakout_type = 'breakout_up'
                    target_level = resistance

                    details = {
                        'type': 'BREAKOUT RIALZISTA',
                        'level_broken': resistance,
                        'close': current_close,
                        'volume_ratio': volume_ratio,
                        'adx': adx_current,
                        'adx_ok': adx_confirmed,
                        'volume_ok': volume_confirmed,
                    }
                    logger.info(f"[{symbol}] BREAKOUT UP: {current_close:.2f} > {resistance:.2f} | Vol: {volume_ratio:.1f}x | ADX: {adx_current:.1f}")
                    break

        # ---- VERIFICA BREAKDOWN RIBASSISTA ----
        if signal == 'HOLD':
            for support in levels['support'][:3]:
                if current_close < support and prev_close >= support:
                    volume_confirmed = volume_ratio >= self.volume_multiplier
                    candle_confirmed = current_close < support if self.wait_candle_close else True

                    if volume_confirmed and candle_confirmed:
                        signal = 'SELL'
                        breakout_type = 'breakdown'
                        target_level = support

                        details = {
                            'type': 'BREAKDOWN RIBASSISTA',
                            'level_broken': support,
                            'close': current_close,
                            'volume_ratio': volume_ratio,
                            'adx': adx_current,
                        }
                        logger.info(f"[{symbol}] BREAKDOWN: {current_close:.2f} < {support:.2f} | Vol: {volume_ratio:.1f}x")
                        break

        # Calcola target e stop dinamici basati su ATR
        stop_loss = None
        take_profit = None

        if signal == 'BUY' and target_level:
            stop_loss = current_close - (atr * 2)  # 2x ATR come stop
            take_profit = current_close + (atr * 3)  # 3x ATR come target

        elif signal == 'SELL' and target_level:
            stop_loss = current_close + (atr * 2)
            take_profit = current_close - (atr * 3)

        # Aggiungi ADX al filtro di qualità del segnale
        adx_warning = None
        if signal != 'HOLD' and adx_current < self.adx_min:
            adx_warning = f"ADX basso ({adx_current:.1f} < {self.adx_min}): trend debole"
            logger.warning(f"[{symbol}] {adx_warning}")

        return {
            'signal': signal,
            'strategy': 'breakout',
            'symbol': symbol,
            'timestamp': datetime.now().isoformat(),
            'breakout_type': breakout_type,
            'level': target_level,
            'stop_loss_atr': round(stop_loss, 4) if stop_loss else None,
            'take_profit_atr': round(take_profit, 4) if take_profit else None,
            'atr': atr,
            'adx': adx_current,
            'volume_ratio': volume_ratio,
            'adx_warning': adx_warning,
            'levels': levels,
            'details': details,
        }

    def analyze(self, df_5min: pd.DataFrame, df_daily: pd.DataFrame, symbol: str) -> Dict:
        """
        Punto di entrata principale per l'analisi breakout.

        Args:
            df_5min: Dati 5 minuti
            df_daily: Dati giornalieri per supporti/resistenze
            symbol: Simbolo

        Returns:
            Segnale di trading
        """
        return self.detect_breakout(df_5min, df_daily, symbol)
