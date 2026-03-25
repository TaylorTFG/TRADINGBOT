# ============================================================
# STRATEGIA 4: LIQUIDITY HUNT SCALPING (1min)
# Identifica Liquidity Sweeps e caccia agli stop
# Usa Money Flow Index (MFI) a 9 periodi per validazione volume
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


class LiquidityHuntStrategy:
    """
    Liquidity Hunt Strategy per Market Structure Trading.

    Su candele 1min:
    - Identifica Support/Resistance (High/Low ultimi 60 minuti)
    - Rileva Liquidity Sweeps (prezzo buca il livello e recupera)
    - Valida con Money Flow Index (MFI) a 9 periodi
    - Usa VWAP come target dinamico per Take Profit

    Logica:
    1. BUY Sweep: Price < Support → Close > Support + MFI > 40
    2. SELL Sweep: Price > Resistance → Close < Resistance + MFI < 60
    3. Score: 1 (sweep semplice), 2 (sweep + MFI forte)
    """

    def __init__(self, config: dict):
        """Inizializza la strategia Liquidity Hunt."""
        self.config = config
        self.strategy_config = config.get('strategy_liquidity', {})
        self.enabled = self.strategy_config.get('enabled', True)

        # Parametri Liquidity Hunt
        self.lookback_mins = self.strategy_config.get('lookback_mins', 60)  # Massimi/minimi ultimi 60 min
        self.sweep_confirmation_distance = self.strategy_config.get('sweep_confirmation_distance', 0.005)  # 0.5%

        # MFI (Money Flow Index) - 9 periodi
        self.mfi_period = self.strategy_config.get('mfi_period', 9)
        self.mfi_buy_threshold = self.strategy_config.get('mfi_buy_threshold', 40)  # MFI > 40 per BUY
        self.mfi_sell_threshold = self.strategy_config.get('mfi_sell_threshold', 60)  # MFI < 60 per SELL

        logger.info(f"LiquidityHuntStrategy inizializzata (lookback={self.lookback_mins}min, MFI period={self.mfi_period})")

    def calculate_mfi(self, df: pd.DataFrame, period: int = 9) -> Optional[pd.Series]:
        """
        Calcola Money Flow Index (MFI) a N periodi.

        MFI è simile a RSI ma pesa anche il volume.
        MFI = 100 - (100 / (1 + Money Flow Ratio))

        Dove:
        - Money Flow = (Close + High + Low) / 3 * Volume
        - Positive Money Flow = somma di Money Flow quando close > close precedente
        - Negative Money Flow = somma di Money Flow quando close < close precedente
        - Money Flow Ratio = Σ(Positive MF) / Σ(Negative MF) nei periodi

        Args:
            df: DataFrame con OHLCV
            period: Periodo MFI (default 9)

        Returns:
            Series con MFI values
        """
        if df is None or len(df) < period + 5:
            return None

        df = df.copy()
        close = df['close'].values
        high = df['high'].values
        low = df['low'].values
        volume = df['volume'].values

        # Calcola Typical Price (TP) = (Close + High + Low) / 3
        tp = (close + high + low) / 3

        # Calcola Raw Money Flow (RMF) = TP * Volume
        rmf = tp * volume

        # Determina se positive o negative money flow
        positive_flow = np.zeros(len(df))
        negative_flow = np.zeros(len(df))

        for i in range(1, len(df)):
            if close[i] > close[i-1]:
                positive_flow[i] = rmf[i]
            elif close[i] < close[i-1]:
                negative_flow[i] = rmf[i]
            # Se close == close precedente, no flow

        # Somma positive e negative flow su periodo
        positive_sum = pd.Series(positive_flow).rolling(window=period).sum()
        negative_sum = pd.Series(negative_flow).rolling(window=period).sum()

        # Calcola Money Flow Ratio e MFI
        mfr = positive_sum / negative_sum.replace(0, 1)  # Evita divisione per zero
        mfi = 100 - (100 / (1 + mfr))

        return mfi

    def identify_support_resistance(self, df: pd.DataFrame) -> Dict[str, float]:
        """
        Identifica Support e Resistance dai massimi/minimi degli ultimi N minuti.

        Logica:
        - Support: minimo più basso degli ultimi 60 minuti
        - Resistance: massimo più alto degli ultimi 60 minuti

        Args:
            df: DataFrame con OHLCV (1min)

        Returns:
            {'support': float, 'resistance': float}
        """
        if df is None or len(df) < 5:
            return {'support': 0, 'resistance': 0, 'range': 0}

        # Prendi gli ultimi N candles (60 minuti = 60 candele da 1min)
        lookback = min(self.lookback_mins, len(df))
        recent = df.iloc[-lookback:]

        support = recent['low'].min()
        resistance = recent['high'].max()
        range_price = resistance - support

        return {
            'support': support,
            'resistance': resistance,
            'range': range_price
        }

    def detect_liquidity_sweep(self, df: pd.DataFrame, support: float, resistance: float) -> Dict:
        """
        Rileva Liquidity Sweeps.

        Un liquidity sweep è quando il prezzo:
        1. "Buca" un livello (support o resistance)
        2. "Recupera" (close dall'altra parte del livello)

        Questo significa che gli stop loss accumulati ai livelli sono stati "spazzati" via,
        e il prezzo sta tornando nella direzione originale.

        BUY Sweep:
        - Prezzo scende sotto Support (low < support)
        - Close rimane sopra Support (close > support)
        - Non necessariamente chiude a livello support, ma deve essere confermato da MFI

        SELL Sweep:
        - Prezzo sale sopra Resistance (high > resistance)
        - Close rimane sotto Resistance (close < resistance)
        - Non necessariamente chiude a livello resistance, ma deve essere confermato da MFI

        Returns:
            {'buy_sweep': bool, 'sell_sweep': bool, 'sweep_type': str}
        """
        if len(df) < 2:
            return {'buy_sweep': False, 'sell_sweep': False, 'sweep_type': 'NONE'}

        current = df.iloc[-1]
        previous = df.iloc[-2]

        current_close = float(current['close'])
        current_low = float(current['low'])
        current_high = float(current['high'])

        prev_close = float(previous['close'])

        buy_sweep = False
        sell_sweep = False
        sweep_type = 'NONE'

        # ---- BUY SWEEP ----
        # Condizioni:
        # 1. Low < Support (prezzo buca al ribasso)
        # 2. Close > Support (recupera)
        # 3. Close > prev_close (momentum rialzista)
        if current_low < support and current_close > support and current_close > prev_close:
            buy_sweep = True
            sweep_type = 'BUY_SWEEP'

        # ---- SELL SWEEP ----
        # Condizioni:
        # 1. High > Resistance (prezzo buca al rialzo)
        # 2. Close < Resistance (recupera)
        # 3. Close < prev_close (momentum ribassista)
        elif current_high > resistance and current_close < resistance and current_close < prev_close:
            sell_sweep = True
            sweep_type = 'SELL_SWEEP'

        return {
            'buy_sweep': buy_sweep,
            'sell_sweep': sell_sweep,
            'sweep_type': sweep_type
        }

    def analyze(self, df_1min: pd.DataFrame, df_5min: pd.DataFrame, symbol: str) -> Dict:
        """
        Analizza Liquidity Hunt.

        Logica:
        1. Identifica Support/Resistance (High/Low ultimi 60min)
        2. Rileva Liquidity Sweep (prezzo buca e recupera)
        3. Valida con MFI(9)
        4. Ritorna segnale con score

        Args:
            df_1min: DataFrame 1min per sweep detection e MFI
            df_5min: DataFrame 5min (opzionale, non usato al momento)
            symbol: Simbolo (es. "BTC/USD")

        Returns:
            {'signal': 'BUY'|'SELL'|'HOLD', 'score': 0-2, 'mfi': float, ...}
        """
        if not self.enabled:
            return {'signal': 'HOLD', 'score': 0, 'reason': 'Strategia disabilitata'}

        if df_1min is None or len(df_1min) < 65:  # Serve minimo 60 candele + buffer
            return {'signal': 'HOLD', 'score': 0, 'reason': 'Dati insufficienti (serve 65+ candele)'}

        # ---- STEP 1: Identifica Support/Resistance ----
        sr = self.identify_support_resistance(df_1min)
        support = sr['support']
        resistance = sr['resistance']

        # ---- STEP 2: Calcola MFI ----
        mfi_series = self.calculate_mfi(df_1min, self.mfi_period)
        if mfi_series is None or len(mfi_series) == 0:
            return {'signal': 'HOLD', 'score': 0, 'reason': 'MFI non calcolato'}

        mfi_current = float(mfi_series.iloc[-1])

        # ---- STEP 3: Rileva Liquidity Sweep ----
        sweep_result = self.detect_liquidity_sweep(df_1min, support, resistance)

        # ---- STEP 4: Valida con MFI ----
        signal = 'HOLD'
        score = 0
        reason = ''
        mfi_confirmation = ''

        current_price = float(df_1min.iloc[-1]['close'])

        if sweep_result['buy_sweep']:
            # BUY Sweep: MFI deve essere rialzista (> 40)
            if mfi_current > self.mfi_buy_threshold:
                score = 2  # Sweep + MFI forte
                reason = f"Buy Sweep confermato da MFI forte ({mfi_current:.1f} > {self.mfi_buy_threshold})"
                mfi_confirmation = "STRONG"
            else:
                score = 1  # Sweep ma MFI debole
                reason = f"Buy Sweep rilevato, ma MFI debole ({mfi_current:.1f} < {self.mfi_buy_threshold})"
                mfi_confirmation = "WEAK"

            signal = 'BUY'

        elif sweep_result['sell_sweep']:
            # SELL Sweep: MFI deve essere ribassista (< 60)
            if mfi_current < self.mfi_sell_threshold:
                score = 2  # Sweep + MFI forte
                reason = f"Sell Sweep confermato da MFI forte ({mfi_current:.1f} < {self.mfi_sell_threshold})"
                mfi_confirmation = "STRONG"
            else:
                score = 1  # Sweep ma MFI debole
                reason = f"Sell Sweep rilevato, ma MFI debole ({mfi_current:.1f} > {self.mfi_sell_threshold})"
                mfi_confirmation = "WEAK"

            signal = 'SELL'

        else:
            # No sweep rilevato
            reason = f"No sweep rilevato. Support={support:.2f}, Resistance={resistance:.2f}, Price={current_price:.2f}, MFI={mfi_current:.1f}"

        result = {
            'signal': signal,
            'score': score,
            'strategy': 'liquidity_hunt',
            'symbol': symbol,
            'timestamp': datetime.now().isoformat(),
            'details': {
                'reason': reason,
                'support': support,
                'resistance': resistance,
                'current_price': current_price,
                'mfi_confirmation': mfi_confirmation,
                'sweep_type': sweep_result['sweep_type'],
            },
            'indicators': {
                'mfi': mfi_current,
                'support': support,
                'resistance': resistance,
                'current_price': current_price,
                'range': sr['range'],
            }
        }

        logger.info(
            f"[{symbol}] Liquidity Hunt: {signal} ({score}) | "
            f"Price={current_price:.2f} | Support={support:.2f} | Resistance={resistance:.2f} | "
            f"MFI={mfi_current:.1f} | {sweep_result['sweep_type']}"
        )

        return result
