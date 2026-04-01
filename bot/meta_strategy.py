# ============================================================
# META-STRATEGY - SISTEMA DI VOTO PESATO CON 6 STRATEGIE
# Combina i segnali con pesi differenziati per qualità
# ============================================================

import logging
import pandas as pd
from typing import Dict, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class MetaStrategy:
    """
    Sistema di voto pesato che combina 6 strategie.

    Strategie e pesi:
    1. Confluence (EMA Crossover) - 1.0x
    2. Breakout (Bollinger Squeeze) - 0.8x
    3. Sentiment (VWAP Momentum) - 0.8x
    4. RSI Divergence - 1.2x
    5. S/R Bounce - 1.0x
    6. MTF Confluence - 2.0x (peso doppio — qualità massima)

    Regime-based routing:
    - TRENDING: abilita confluence, sentiment, rsi_div, mtf → min_weighted_score = 1.5
    - RANGING: abilita breakout, sr_bounce, rsi_div → min_weighted_score = 1.5
    - UNDEFINED: tutti → min_weighted_score = 2.5
    """

    # Pesi per strategia (determina importanza nel voting)
    STRATEGY_WEIGHTS = {
        'confluence': 1.0,
        'breakout': 0.8,
        'sentiment': 0.8,
        'rsi_divergence': 1.2,
        'sr_bounce': 1.0,
        'mtf_confluence': 2.0,  # Peso doppio — massima qualità
    }

    def __init__(self, config: dict):
        """Inizializza il meta-strategy."""
        self.config = config
        self._trend_cache = {}

    def vote(
        self,
        confluence_signal: Dict,
        breakout_signal: Dict,
        sentiment_signal: Dict,
        rsi_div_signal: Dict,
        sr_bounce_signal: Dict,
        mtf_signal: Dict,
        symbol: str,
        df_1m=None,
        df_15m=None,
        df_1h=None,
        strategy_mask: Optional[List[bool]] = None,
        regime_info: Optional[Dict] = None
    ) -> Dict:
        """
        Raccoglie i voti dalle 6 strategie e calcola il segnale finale con pesi.

        Args:
            confluence_signal, breakout_signal, sentiment_signal,
            rsi_div_signal, sr_bounce_signal, mtf_signal: Segnali strategie
            symbol: Simbolo in analisi
            df_1m, df_15m, df_1h: DataFrame multi-timeframe
            strategy_mask: List[bool] (6 elementi) - strategie attive per regime
            regime_info: Dict con info regime (regime, confidence, strategy_mask)

        Returns:
            Dizionario con final_signal, weighted_score, votes, details
        """

        # Estrai i voti dalle 6 strategie
        votes = {
            'confluence': confluence_signal.get('signal', 'HOLD'),
            'breakout': breakout_signal.get('signal', 'HOLD'),
            'sentiment': sentiment_signal.get('signal', 'HOLD'),
            'rsi_divergence': rsi_div_signal.get('signal', 'HOLD'),
            'sr_bounce': sr_bounce_signal.get('signal', 'HOLD'),
            'mtf_confluence': mtf_signal.get('signal', 'HOLD'),
        }

        # ---- APPLICA STRATEGY MASK (REGIME DETECTION) ----
        if strategy_mask is None:
            strategy_mask = [True] * 6

        strategy_names = ['confluence', 'breakout', 'sentiment', 'rsi_divergence', 'sr_bounce', 'mtf_confluence']
        regime_str = regime_info.get('regime', 'UNDEFINED') if regime_info else 'UNDEFINED'

        # Disabilita strategie non rilevanti per il regime
        for i, (strategy_name, enabled) in enumerate(zip(strategy_names, strategy_mask)):
            if not enabled:
                logger.debug(f"[{symbol}] Strategia {strategy_name} disabilitata in regime {regime_str}")
                votes[strategy_name] = 'HOLD'

        # ---- CALCOLO WEIGHTED SIGNAL ----
        # Somma i pesi per BUY e SELL (non conta voti)
        buy_weight = sum(
            self.STRATEGY_WEIGHTS[s] for s in strategy_names
            if votes.get(s) == 'BUY'
        )
        sell_weight = sum(
            self.STRATEGY_WEIGHTS[s] for s in strategy_names
            if votes.get(s) == 'SELL'
        )

        # Determina soglia minima in base al regime
        if regime_info:
            regime = regime_info.get('regime', 'UNDEFINED')
            if regime == 'TRENDING':
                min_weighted_score = 1.2  # MTF(2.0) + EMA(1.0) = 3.2, ma anche solo MTF(2.0) >= 1.2
            elif regime == 'RANGING':
                min_weighted_score = 1.0  # BB(0.8) + SR(1.0) = 1.8 >= 1.0; singolo SR(1.0) >= 1.0
            else:  # UNDEFINED
                min_weighted_score = 2.0  # Ridotto da 2.5 per più opportunità
        else:
            min_weighted_score = 2.0

        # Determina il segnale finale
        final_signal = 'HOLD'
        weighted_score = 0
        buy_votes = sum(1 for v in votes.values() if v == 'BUY')
        sell_votes = sum(1 for v in votes.values() if v == 'SELL')
        reason = ''

        if buy_weight >= min_weighted_score:
            final_signal = 'BUY'
            weighted_score = buy_weight
            reason = f'{buy_votes} strategie BUY (peso={buy_weight:.1f}) → entrata'
        elif sell_weight >= min_weighted_score:
            final_signal = 'SELL'
            weighted_score = sell_weight
            reason = f'{sell_votes} strategie SELL (peso={sell_weight:.1f}) → uscita'
        else:
            final_signal = 'HOLD'
            reason = f'Consenso insufficiente: BUY-peso={buy_weight:.1f}, SELL-peso={sell_weight:.1f} (min={min_weighted_score:.1f})'

        # Calcola score medio delle strategie che hanno votato
        confidences = []
        for name, signal_dict in [
            ('confluence', confluence_signal),
            ('breakout', breakout_signal),
            ('sentiment', sentiment_signal),
            ('rsi_divergence', rsi_div_signal),
            ('sr_bounce', sr_bounce_signal),
            ('mtf_confluence', mtf_signal)
        ]:
            conf = signal_dict.get('score', signal_dict.get('confidence', 0))
            if conf is not None:
                confidences.append(float(conf) if conf else 0)

        avg_confidence = sum(confidences) / len(confidences) if confidences else 0

        # Costruisci il risultato
        result = {
            'final_signal': final_signal,
            'weighted_score': weighted_score,
            'buy_votes': buy_votes,
            'sell_votes': sell_votes,
            'hold_votes': 6 - buy_votes - sell_votes,
            'min_weighted_score': min_weighted_score,
            'buy_weight': buy_weight,
            'sell_weight': sell_weight,
            'reason': reason,
            'avg_confidence': avg_confidence,
            'symbol': symbol,
            'timestamp': datetime.now().isoformat(),
            'votes': votes,
            'regime_info': regime_info,
            'signal_details': {
                'confluence': {
                    'vote': votes['confluence'],
                    'score': confluence_signal.get('score', 0),
                    'weight': self.STRATEGY_WEIGHTS['confluence'],
                },
                'breakout': {
                    'vote': votes['breakout'],
                    'score': breakout_signal.get('score', 0),
                    'weight': self.STRATEGY_WEIGHTS['breakout'],
                },
                'sentiment': {
                    'vote': votes['sentiment'],
                    'score': sentiment_signal.get('sentiment_score', sentiment_signal.get('score', 0)),
                    'weight': self.STRATEGY_WEIGHTS['sentiment'],
                },
                'rsi_divergence': {
                    'vote': votes['rsi_divergence'],
                    'score': rsi_div_signal.get('score', 0),
                    'weight': self.STRATEGY_WEIGHTS['rsi_divergence'],
                },
                'sr_bounce': {
                    'vote': votes['sr_bounce'],
                    'score': sr_bounce_signal.get('score', 0),
                    'weight': self.STRATEGY_WEIGHTS['sr_bounce'],
                },
                'mtf_confluence': {
                    'vote': votes['mtf_confluence'],
                    'score': mtf_signal.get('score', 0),
                    'weight': self.STRATEGY_WEIGHTS['mtf_confluence'],
                }
            }
        }

        logger.info(
            f"[{symbol}] MetaStrategy: {final_signal} (score={weighted_score:.1f}) | "
            f"Voti: BUY={buy_votes} SELL={sell_votes} HOLD={6-buy_votes-sell_votes} | "
            f"{reason}"
        )

        return result

    def should_close_position(
        self,
        position: Dict,
        current_signals: Dict
    ) -> Dict:
        """
        Verifica se una posizione aperta dovrebbe essere chiusa
        basandosi sui nuovi segnali.
        """
        final_signal = current_signals.get('final_signal', 'HOLD')
        position_side = position.get('side', 'buy')

        # Posizione long + segnale SELL → chiudi
        if position_side == 'buy' and final_signal == 'SELL':
            return {
                'should_close': True,
                'reason': f'Segnale SELL ricevuto (voti: {current_signals.get("sell_votes", 0)}/6)'
            }

        # Posizione short + segnale BUY → chiudi
        if position_side == 'sell' and final_signal == 'BUY':
            return {
                'should_close': True,
                'reason': f'Segnale BUY ricevuto su posizione short'
            }

        return {'should_close': False, 'reason': ''}
