# ============================================================
# STRATEGIA 6: SUPPORT/RESISTANCE BOUNCE SCALPING (1min)
# Identifica livelli S/R e attende bounce con conferma
# ============================================================

import logging
import pandas as pd
import numpy as np
from typing import Optional, Dict
from datetime import datetime

logger = logging.getLogger(__name__)


class SRBounceStrategy:
    """
    Support/Resistance Bounce Strategy.

    1. Identifica S/R chiave su 1h (ultimi 50 candles):
       - Support = media dei 3 minimi più bassi nell'ultimo range
       - Resistance = media dei 3 massimi più alti nell'ultimo range
       - Key levels = massimi/minimi con almeno 2 tocchi (confluenza)

    2. Attende che il prezzo su 1m si avvicini a un livello (entro 0.15%)

    3. Conferma con:
       - Candela di rigetto (lower wick > 2× body per BUY)
       - Volume > 150% media
       - MFI(9) nella direzione giusta (>45 per BUY, <55 per SELL)

    Target: livello S/R opposto
    """

    def __init__(self, config: dict):
        """Inizializza la strategia S/R Bounce."""
        self.config = config
        self.strategy_config = config.get('strategy_sr_bounce', {})
        self.enabled = self.strategy_config.get('enabled', True)

        # Parametri
        self.proximity_pct = self.strategy_config.get('proximity_pct', 0.0015)
        self.mfi_period = self.strategy_config.get('mfi_period', 9)
        self.volume_multiplier = self.strategy_config.get('volume_multiplier', 1.5)
        self.min_wick_ratio = self.strategy_config.get('min_wick_ratio', 2.0)

        logger.info(f"SRBounceStrategy inizializzata (proximity={self.proximity_pct*100:.2f}%)")

    def identify_sr_levels(self, df_1h: pd.DataFrame) -> dict:
        """Identifica livelli S/R chiave sul timeframe 1h."""
        if df_1h is None or len(df_1h) < 20:
            return {'supports': [], 'resistances': []}

        # Usa ultimi 50 bar 1h = circa 2 giorni
        df = df_1h.tail(50)
        highs = df['high'].values
        lows = df['low'].values

        # Trova livelli con almeno 2 tocchi (entro 0.3%)
        supports = []
        resistances = []
        tolerance = 0.003  # 0.3%

        # Raggruppa massimi vicini
        for i, h in enumerate(highs):
            touches = sum(1 for other_h in highs if abs(other_h - h) / h < tolerance)
            if touches >= 2:
                resistances.append(h)

        # Raggruppa minimi vicini
        for i, l in enumerate(lows):
            touches = sum(1 for other_l in lows if abs(other_l - l) / l < tolerance)
            if touches >= 2:
                supports.append(l)

        # Deduplica e prendi i livelli più recenti
        def deduplicate(levels, tol):
            if not levels:
                return []
            levels = sorted(set(levels))
            result = [levels[0]]
            for l in levels[1:]:
                if abs(l - result[-1]) / result[-1] > tol:
                    result.append(l)
            return result[-5:]  # Massimo 5 livelli

        return {
            'supports': deduplicate(supports, tolerance),
            'resistances': deduplicate(resistances, tolerance),
            'range_high': float(df['high'].max()),
            'range_low': float(df['low'].min()),
        }

    def calculate_mfi(self, df: pd.DataFrame, period: int = 9) -> float:
        """Calcola MFI su df e ritorna valore corrente."""
        if len(df) < period + 5:
            return 50.0

        tp = (df['high'] + df['low'] + df['close']) / 3
        rmf = tp * df['volume']
        prev_tp = tp.shift(1)
        pos = rmf.where(tp > prev_tp, 0)
        neg = rmf.where(tp < prev_tp, 0)
        pos_sum = pos.rolling(period).sum()
        neg_sum = neg.rolling(period).sum()
        mfr = pos_sum / neg_sum.replace(0, 1e-10)
        mfi = 100 - (100 / (1 + mfr))
        val = float(mfi.iloc[-1])
        return max(0, min(100, val)) if not np.isnan(val) else 50.0

    def check_rejection_candle(self, last_candle, side: str) -> bool:
        """Verifica se l'ultima candela è una candela di rigetto."""
        body = abs(float(last_candle['close']) - float(last_candle['open']))
        if body < 1e-8:
            body = 1e-8

        if side == 'BUY':
            lower_wick = float(last_candle['open']) - float(last_candle['low'])
            lower_wick = max(0, lower_wick)
            return lower_wick >= self.min_wick_ratio * body
        else:
            upper_wick = float(last_candle['high']) - float(last_candle['open'])
            upper_wick = max(0, upper_wick)
            return upper_wick >= self.min_wick_ratio * body

    def analyze(self, df_1m: pd.DataFrame, df_1h: pd.DataFrame, symbol: str) -> dict:
        """Analizza S/R bounce e genera segnale."""
        if not self.enabled:
            return {
                'signal': 'HOLD',
                'strategy': 'sr_bounce',
                'symbol': symbol,
                'score': 0,
                'reason': 'Strategia disabilitata'
            }

        if df_1m is None or len(df_1m) < 30:
            return {
                'signal': 'HOLD',
                'strategy': 'sr_bounce',
                'symbol': symbol,
                'score': 0,
                'reason': 'Dati insufficienti'
            }

        sr = self.identify_sr_levels(df_1h)
        current = float(df_1m['close'].iloc[-1])
        mfi = self.calculate_mfi(df_1m, self.mfi_period)
        last = df_1m.iloc[-1]

        # Volume check
        vol_ma = df_1m['volume'].rolling(10).mean().iloc[-1]
        vol_ratio = float(df_1m['volume'].iloc[-1]) / max(vol_ma, 1e-10)
        vol_ok = vol_ratio >= self.volume_multiplier

        signal = 'HOLD'
        score = 0
        reason = ''

        # Check supporti → BUY bounce
        for support in sr['supports']:
            proximity = abs(current - support) / support
            if proximity <= self.proximity_pct and current >= support:
                rejection = self.check_rejection_candle(last, 'BUY')
                if mfi > 45 and (vol_ok or rejection):
                    score = 2 if (rejection and vol_ok) else 1
                    signal = 'BUY'
                    reason = f"S/R bounce BUY @ {support:.2f} (prox={proximity*100:.3f}%, MFI={mfi:.1f})"
                    break

        # Check resistenze → SELL bounce
        if signal == 'HOLD':
            for resistance in sr['resistances']:
                proximity = abs(current - resistance) / resistance
                if proximity <= self.proximity_pct and current <= resistance:
                    rejection = self.check_rejection_candle(last, 'SELL')
                    if mfi < 55 and (vol_ok or rejection):
                        score = 2 if (rejection and vol_ok) else 1
                        signal = 'SELL'
                        reason = f"S/R bounce SELL @ {resistance:.2f} (prox={proximity*100:.3f}%, MFI={mfi:.1f})"
                        break

        if not reason:
            reason = f"No bounce | Price={current:.2f} | MFI={mfi:.1f} | Supports={[f'{s:.2f}' for s in sr['supports']]} | Res={[f'{r:.2f}' for r in sr['resistances']]}"

        logger.info(f"[{symbol}] S/R Bounce: {signal} ({score}) | {reason}")

        return {
            'signal': signal,
            'score': score,
            'strategy': 'sr_bounce',
            'symbol': symbol,
            'mfi': mfi,
            'vol_ratio': vol_ratio,
            'sr_levels': sr,
            'reason': reason,
            'timestamp': datetime.now().isoformat()
        }
