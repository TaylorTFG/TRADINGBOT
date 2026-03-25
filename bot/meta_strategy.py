# ============================================================
# META-STRATEGY - SISTEMA DI VOTO COMBINATO
# Combina i segnali delle 3 strategie per prendere
# la decisione finale di trading
# ============================================================

import logging
import pandas as pd
from typing import Dict, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class MetaStrategy:
    """
    Sistema di voto che combina 4 strategie con filtro trend 5min.

    Regole (per 4 strategie):
    - 3/4 o 4/4 concordano BUY → entrata con size massima (2.5% capitale)
    - 2/4 concordano BUY → entrata con size ridotta (1.25% capitale)
    - <2 → nessuna operazione (HOLD)

    Filtro Trend 5min (protegge da falsi segnali):
    - Se trend 5min è BEARISH → blocca segnali BUY 1min
    - Se trend 5min è BULLISH → blocca segnali SELL 1min

    Strategie:
    1. Confluence (EMA Crossover)
    2. Breakout (Bollinger Squeeze)
    3. Sentiment (VWAP Momentum)
    4. Liquidity Hunt (Sweep Detection + MFI)
    """

    def __init__(self, config: dict):
        """
        Inizializza il meta-strategy.

        Args:
            config: Configurazione dal config.yaml
        """
        self.config = config

        # Cache per trend 5min (evita ricalcolo)
        self._trend_cache = {}  # {symbol: {'trend': ..., 'timestamp': ...}}

    def calculate_ema_200_filter(self, df_daily) -> Optional[float]:
        """
        Calcola EMA 200 su daily timeframe per trend globale.

        Usato come filtro contestuale:
        - BUY solo se price > EMA 200 (trend rialzista globale)
        - SELL solo se price < EMA 200 (trend ribassista globale)

        Args:
            df_daily: DataFrame daily con OHLCV

        Returns:
            EMA 200 value, oppure None se dati insufficienti
        """
        if df_daily is None or len(df_daily) < 250:  # Serve minimo 250 candele daily
            return None

        try:
            close = df_daily['close']
            ema_200 = close.ewm(span=200, adjust=False).mean()
            return float(ema_200.iloc[-1])
        except Exception as e:
            logger.warning(f"Errore calcolo EMA 200: {e}")
            return None

    def calculate_5min_trend(self, df_5min) -> str:
        """
        Calcola il trend su timeframe 5min usando EMA 20.

        Usa EMA 20 vs close:
        - Se close > EMA20 → trend BULLISH
        - Se close < EMA20 → trend BEARISH
        - Altrimenti → NEUTRAL

        Args:
            df_5min: DataFrame 5min con OHLCV

        Returns:
            String: 'BULLISH', 'BEARISH', o 'NEUTRAL'
        """
        if df_5min is None or len(df_5min) < 25:
            return 'NEUTRAL'

        try:
            close = df_5min['close']
            ema20 = close.ewm(span=20, adjust=False).mean()

            last_close = float(close.iloc[-1])
            last_ema20 = float(ema20.iloc[-1])

            if pd.notna(last_ema20) and last_ema20 > 0:
                if last_close > last_ema20 * 1.0005:  # Margine 0.05% per evitare fluttuazioni
                    return 'BULLISH'
                elif last_close < last_ema20 * 0.9995:
                    return 'BEARISH'

            return 'NEUTRAL'
        except Exception as e:
            logger.warning(f"Errore calcolo trend 5min: {e}")
            return 'NEUTRAL'

    def vote(
        self,
        confluence_signal: Dict,
        breakout_signal: Dict,
        sentiment_signal: Dict,
        liquidity_signal: Dict,
        symbol: str,
        df_5min=None,
        df_daily=None,
        current_price: Optional[float] = None
    ) -> Dict:
        """
        Raccoglie i voti dalle 4 strategie e calcola il segnale finale.

        Applica filtri contestuali:
        - Trend 5min (EMA 20) per protezione breve termine
        - EMA 200 daily (trend globale) per direzione operazioni

        Args:
            confluence_signal: Segnale dalla Strategia 1 (confluenza EMA)
            breakout_signal: Segnale dalla Strategia 2 (breakout Bollinger)
            sentiment_signal: Segnale dalla Strategia 3 (sentiment VWAP)
            liquidity_signal: Segnale dalla Strategia 4 (liquidity hunt)
            symbol: Simbolo in analisi
            df_5min: DataFrame 5min per filtro trend 5min
            df_daily: DataFrame daily per filtro EMA 200
            current_price: Prezzo corrente per validazione EMA 200

        Returns:
            Dizionario con final_signal, vote_score, action, details
        """
        # ---- FILTRO TREND 5min ----
        # Questo filtro protegge da falsi segnali contro il trend di breve periodo
        trend_5min = self.calculate_5min_trend(df_5min) if df_5min is not None else 'NEUTRAL'

        # ---- FILTRO EMA 200 DAILY (CONTEXTUAL) ----
        # Filtro globale di trend: BUY solo se price > EMA200, SELL solo se price < EMA200
        ema_200 = self.calculate_ema_200_filter(df_daily) if df_daily is not None else None
        contextual_filter_applied = False

        # Estrai i voti dalle 4 strategie
        votes = {
            'confluence': confluence_signal.get('signal', 'HOLD'),
            'breakout': breakout_signal.get('signal', 'HOLD'),
            'sentiment': sentiment_signal.get('signal', 'HOLD'),
            'liquidity': liquidity_signal.get('signal', 'HOLD'),
        }

        # ---- APPLICA FILTRO TREND 5min ----
        # Se trend 5min è BEARISH, blocca i segnali BUY (aspetta un segnale SELL prima)
        for strategy_name in ['confluence', 'breakout', 'sentiment', 'liquidity']:
            if trend_5min == 'BEARISH' and votes[strategy_name] == 'BUY':
                votes[strategy_name] = 'HOLD'
                logger.debug(f"[{symbol}] Segnale BUY bloccato ({strategy_name}): trend 5min è BEARISH")

            if trend_5min == 'BULLISH' and votes[strategy_name] == 'SELL':
                votes[strategy_name] = 'HOLD'
                logger.debug(f"[{symbol}] Segnale SELL bloccato ({strategy_name}): trend 5min è BULLISH")

        # ---- APPLICA FILTRO EMA 200 (Contextual Filter) ----
        # EMA 200 determina la direzione operativa principale
        if ema_200 is not None and current_price is not None:
            if current_price < ema_200:
                # Sotto EMA 200 = trend BEARISH globale → blocca BUY
                for strategy_name in ['confluence', 'breakout', 'sentiment', 'liquidity']:
                    if votes[strategy_name] == 'BUY':
                        votes[strategy_name] = 'HOLD'
                        logger.debug(f"[{symbol}] Segnale BUY bloccato ({strategy_name}): price < EMA200")
                        contextual_filter_applied = True
            elif current_price > ema_200:
                # Sopra EMA 200 = trend BULLISH globale → blocca SELL
                for strategy_name in ['confluence', 'breakout', 'sentiment', 'liquidity']:
                    if votes[strategy_name] == 'SELL':
                        votes[strategy_name] = 'HOLD'
                        logger.debug(f"[{symbol}] Segnale SELL bloccato ({strategy_name}): price > EMA200")
                        contextual_filter_applied = True

        # Conta i voti per BUY, SELL, HOLD
        buy_votes = sum(1 for v in votes.values() if v == 'BUY')
        sell_votes = sum(1 for v in votes.values() if v == 'SELL')
        hold_votes = sum(1 for v in votes.values() if v == 'HOLD')

        # Determina il segnale finale (logica per 4 strategie)
        final_signal = 'HOLD'
        vote_score = 0
        size_type = 'none'
        action = 'none'
        reason = ''

        # Con 4 strategie: 3/4 o 4/4 = full, 2/4 = half, <2 = HOLD
        if buy_votes >= 3:
            final_signal = 'BUY'
            vote_score = buy_votes
            size_type = 'full'  # 2.5% capitale (scalato per €2500)
            action = 'open_full'
            reason = f'{buy_votes}/4 strategie concordano BUY → entrata con size massima'

        elif buy_votes == 2:
            final_signal = 'BUY'
            vote_score = 2
            size_type = 'half'  # 1.25% capitale (scalato per €2500)
            action = 'open_half'
            reason = f'{buy_votes}/4 strategie concordano BUY → entrata con size ridotta'

        elif sell_votes >= 3:
            final_signal = 'SELL'
            vote_score = -sell_votes
            size_type = 'full'
            action = 'close_or_short'
            reason = f'{sell_votes}/4 strategie concordano SELL → uscita/short'

        elif sell_votes == 2:
            final_signal = 'SELL'
            vote_score = -2
            size_type = 'half'
            action = 'close'
            reason = f'{sell_votes}/4 strategie concordano SELL → considera uscita'

        elif sell_votes == 1:
            final_signal = 'HOLD'
            vote_score = -1
            action = 'watch'
            reason = '1/4 strategie SELL → monitora posizioni aperte'

        else:
            final_signal = 'HOLD'
            vote_score = 0
            action = 'none'
            reason = 'Nessun consenso raggiunto'

        # Calcola confidence media delle strategie che hanno votato
        confidences = []
        if buy_votes > 0 or sell_votes > 0:
            for name, signal_dict in [
                ('confluence', confluence_signal),
                ('breakout', breakout_signal),
                ('sentiment', sentiment_signal),
                ('liquidity', liquidity_signal)
            ]:
                conf = signal_dict.get('confidence', signal_dict.get('score', 0))
                if conf is not None:
                    confidences.append(float(conf) if conf else 0)

        avg_confidence = sum(confidences) / len(confidences) if confidences else 0

        # Raccoglie i dettagli dei singoli segnali (4 strategie)
        signal_details = {
            'confluence': {
                'vote': votes['confluence'],
                'score': confluence_signal.get('score', 0),
                'buy_score': confluence_signal.get('buy_score', 0),
                'sell_score': confluence_signal.get('sell_score', 0),
                'details': confluence_signal.get('details', {}),
            },
            'breakout': {
                'vote': votes['breakout'],
                'level': breakout_signal.get('level'),
                'volume_ratio': breakout_signal.get('volume_ratio', 1),
                'adx': breakout_signal.get('adx', 0),
                'details': breakout_signal.get('details', {}),
            },
            'sentiment': {
                'vote': votes['sentiment'],
                'score': sentiment_signal.get('sentiment_score', 0),
                'classification': sentiment_signal.get('sentiment_classification', 'NEUTRAL'),
                'article_count': sentiment_signal.get('article_count', 0),
                'details': sentiment_signal.get('details', {}),
            },
            'liquidity': {
                'vote': votes['liquidity'],
                'score': liquidity_signal.get('score', 0),
                'mfi': liquidity_signal.get('indicators', {}).get('mfi', 0),
                'sweep_type': liquidity_signal.get('details', {}).get('sweep_type', 'NONE'),
                'details': liquidity_signal.get('details', {}),
            }
        }

        result = {
            'final_signal': final_signal,
            'vote_score': vote_score,
            'buy_votes': buy_votes,
            'sell_votes': sell_votes,
            'hold_votes': hold_votes,
            'size_type': size_type,
            'action': action,
            'reason': reason,
            'avg_confidence': avg_confidence,
            'symbol': symbol,
            'timestamp': datetime.now().isoformat(),
            'votes': votes,
            'trend_5min': trend_5min,  # Aggiungi il trend 5min ai risultati
            'signal_details': signal_details,
            'strategy_name': self._get_leading_strategy(votes, confluence_signal, breakout_signal, sentiment_signal)
        }

        logger.info(
            f"[{symbol}] MetaStrategy: {final_signal} | "
            f"Voti: BUY={buy_votes}, SELL={sell_votes}, HOLD={hold_votes} | "
            f"{reason}"
        )

        return result

    def _get_leading_strategy(
        self,
        votes: Dict,
        confluence_signal: Dict,
        breakout_signal: Dict,
        sentiment_signal: Dict
    ) -> str:
        """
        Identifica la strategia principale che ha generato il segnale.

        Returns:
            Nome della strategia con confidence più alta
        """
        # Mappa segnali a confidence
        scores = {}

        conf_score = confluence_signal.get('score', 0) or 0
        break_score = 1 if breakout_signal.get('signal') != 'HOLD' else 0
        sent_score = abs(sentiment_signal.get('sentiment_score', 0) or 0)

        if votes.get('confluence') != 'HOLD':
            scores['confluence'] = conf_score
        if votes.get('breakout') != 'HOLD':
            scores['breakout'] = break_score
        if votes.get('sentiment') != 'HOLD':
            scores['sentiment'] = sent_score

        if not scores:
            return 'none'

        return max(scores, key=scores.get)

    def should_close_position(
        self,
        position: Dict,
        current_signals: Dict
    ) -> Dict:
        """
        Verifica se una posizione aperta dovrebbe essere chiusa
        basandosi sui nuovi segnali.

        Args:
            position: Dati della posizione aperta
            current_signals: Dizionario con i segnali attuali per il simbolo

        Returns:
            Dizionario con should_close, reason
        """
        vote_score = current_signals.get('vote_score', 0)
        final_signal = current_signals.get('final_signal', 'HOLD')
        position_side = position.get('side', 'buy')

        # Posizione long + segnale SELL → chiudi
        if position_side == 'buy' and final_signal == 'SELL':
            return {
                'should_close': True,
                'reason': f'Segnale SELL ricevuto (voti: {current_signals.get("sell_votes", 0)}/3)'
            }

        # Posizione short + segnale BUY → chiudi
        if position_side == 'sell' and final_signal == 'BUY':
            return {
                'should_close': True,
                'reason': f'Segnale BUY ricevuto su posizione short'
            }

        # Anche 1 voto SELL su posizione long → attenzione
        if position_side == 'buy' and current_signals.get('sell_votes', 0) >= 2:
            return {
                'should_close': True,
                'reason': f'2+ voti SELL su posizione long'
            }

        return {'should_close': False, 'reason': ''}
