# ============================================================
# STRATEGIA 3: NEWS SENTIMENT + ANALISI TECNICA
# Combina sentiment delle notizie con conferma tecnica
# ============================================================

import logging
import pandas as pd
from typing import Optional, Dict
from datetime import datetime

logger = logging.getLogger(__name__)


class SentimentStrategy:
    """
    Strategia basata sul sentiment delle notizie.

    Logica:
    1. Recupera sentiment score da NewsAPI e RSS feed (-1 a +1)
    2. Se sentiment > +0.6 e tecnica concorda → segnale BUY forte
    3. Se sentiment < -0.6 → blocca acquisti, valuta short
    4. Peso recente: ultime 2 ore = 60%, ultime 24 ore = 40%

    Trigger speciali:
    - Earnings annunci
    - Fed meetings
    - Dati macro (CPI, NFP)
    """

    def __init__(self, news_analyzer, config: dict):
        """
        Inizializza la strategia sentiment.

        Args:
            news_analyzer: Istanza del NewsAnalyzer
            config: Configurazione dal config.yaml
        """
        self.news_analyzer = news_analyzer
        self.config = config
        self.strategy_config = config.get('strategy_sentiment', {})
        self.enabled = self.strategy_config.get('enabled', True)

        # Soglie sentiment
        self.bullish_threshold = self.strategy_config.get('bullish_threshold', 0.6)
        self.bearish_threshold = self.strategy_config.get('bearish_threshold', -0.6)

        logger.info(
            f"SentimentStrategy inizializzata "
            f"(bull: >{self.bullish_threshold}, bear: <{self.bearish_threshold})"
        )

    def check_technical_confirmation(self, df: pd.DataFrame) -> Dict:
        """
        Verifica la conferma tecnica semplificata per il sentiment.

        Usa:
        - Trend EMA (20 vs 50)
        - RSI (non in zona opposta)
        - Momentum (prezzo sopra/sotto la media)

        Args:
            df: DataFrame con dati OHLCV e indicatori

        Returns:
            Dizionario con confirmed, direction, details
        """
        if df is None or df.empty:
            return {'confirmed': False, 'direction': 'NEUTRAL', 'details': {}}

        last = df.iloc[-1]

        # EMA trend
        ema_fast = last.get('ema_20', last.get('close', 0))
        ema_slow = last.get('ema_50', last.get('close', 0))
        close = last.get('close', 0)
        rsi = last.get('rsi', 50)

        details = {}
        bullish_signals = 0
        bearish_signals = 0

        # Verifica EMA
        if ema_fast and ema_slow and ema_fast > 0 and ema_slow > 0:
            if ema_fast > ema_slow:
                bullish_signals += 1
                details['ema'] = 'bullish'
            else:
                bearish_signals += 1
                details['ema'] = 'bearish'

        # Verifica RSI (non ipercomprato per buy, non ipervenduto per sell)
        if pd.notna(rsi):
            if rsi < 70:  # Non overbought per buy
                bullish_signals += 1
                details['rsi'] = f'ok_for_buy ({rsi:.1f})'
            if rsi > 30:  # Non oversold per sell
                bearish_signals += 1
                details['rsi'] = f'ok_for_sell ({rsi:.1f})'

        # Momentum (prezzo vs EMA200)
        ema200 = last.get('ema200', 0)
        if ema200 and close and close > 0:
            if close > ema200:
                bullish_signals += 1
                details['momentum'] = 'above_ema200'
            else:
                bearish_signals += 1
                details['momentum'] = 'below_ema200'

        if bullish_signals > bearish_signals:
            direction = 'BULLISH'
            confirmed = bullish_signals >= 2
        elif bearish_signals > bullish_signals:
            direction = 'BEARISH'
            confirmed = bearish_signals >= 2
        else:
            direction = 'NEUTRAL'
            confirmed = False

        return {
            'confirmed': confirmed,
            'direction': direction,
            'bullish_signals': bullish_signals,
            'bearish_signals': bearish_signals,
            'details': details
        }

    def analyze(self, df: pd.DataFrame, symbol: str) -> Dict:
        """
        Analizza sentiment e tecnica per generare un segnale.

        Args:
            df: DataFrame con dati OHLCV e indicatori tecnici
            symbol: Simbolo dell'asset

        Returns:
            Dizionario con signal, sentiment_score, technical_confirmation, details
        """
        if not self.enabled:
            return {
                'signal': 'HOLD',
                'strategy': 'sentiment',
                'symbol': symbol,
                'reason': 'Strategia disabilitata'
            }

        # Recupera sentiment dalle notizie
        sentiment_data = self.news_analyzer.get_sentiment(symbol)
        sentiment_score = sentiment_data.get('score', 0.0)
        article_count = sentiment_data.get('article_count', 0)
        classification = sentiment_data.get('classification', 'NEUTRAL')

        # Se non ci sono notizie rilevanti, segnale neutro
        if article_count == 0:
            return {
                'signal': 'HOLD',
                'strategy': 'sentiment',
                'symbol': symbol,
                'sentiment_score': 0,
                'article_count': 0,
                'reason': 'Nessuna notizia trovata',
                'timestamp': datetime.now().isoformat()
            }

        # Verifica conferma tecnica
        technical = self.check_technical_confirmation(df)

        # ---- LOGICA DEL SEGNALE ----
        signal = 'HOLD'
        reason = ''
        confidence = 0.0

        # Segnale BUY forte: sentiment molto positivo + tecnica concorde
        if sentiment_score > self.bullish_threshold:
            if technical['direction'] == 'BULLISH' and technical['confirmed']:
                signal = 'BUY'
                confidence = min(0.95, (sentiment_score + 0.5) * 0.7)
                reason = f"Sentiment fortemente positivo ({sentiment_score:.2f}) + conferma tecnica"
            elif technical['direction'] != 'BEARISH':
                signal = 'BUY'
                confidence = min(0.75, sentiment_score * 0.7)
                reason = f"Sentiment positivo ({sentiment_score:.2f}), tecnica neutrale"

        # Segnale SELL / blocco acquisti: sentiment molto negativo
        elif sentiment_score < self.bearish_threshold:
            if technical['direction'] == 'BEARISH' or technical['direction'] == 'NEUTRAL':
                signal = 'SELL'
                confidence = min(0.90, abs(sentiment_score) * 0.7)
                reason = f"Sentiment molto negativo ({sentiment_score:.2f})"
            else:
                signal = 'HOLD'  # Tecnica positiva contraddice il sentiment bearish
                reason = f"Sentiment negativo ma tecnica bullish - HOLD"

        # Sentiment moderato - segui la tecnica
        elif sentiment_score > 0.15 and technical['direction'] == 'BULLISH':
            signal = 'HOLD'  # Non abbastanza forte per un segnale
            reason = f"Sentiment moderato ({sentiment_score:.2f}), attendo segnale più forte"
        else:
            reason = f"Sentiment neutro ({sentiment_score:.2f})"

        logger.info(
            f"[{symbol}] Sentiment: {signal} | "
            f"Score: {sentiment_score:.3f} ({classification}) | "
            f"Articoli: {article_count} | "
            f"Tecnica: {technical['direction']}"
        )

        return {
            'signal': signal,
            'strategy': 'sentiment',
            'symbol': symbol,
            'timestamp': datetime.now().isoformat(),
            'sentiment_score': sentiment_score,
            'sentiment_classification': classification,
            'article_count': article_count,
            'recent_count': sentiment_data.get('recent_count', 0),
            'confidence': confidence,
            'technical_confirmation': technical,
            'reason': reason,
            'details': {
                'recent_sentiment': sentiment_data.get('recent_score', 0),
                'older_sentiment': sentiment_data.get('older_score', 0),
            }
        }
