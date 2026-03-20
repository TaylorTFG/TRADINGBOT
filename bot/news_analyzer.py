# ============================================================
# NEWS ANALYZER - ANALISI NLP DEL SENTIMENT DELLE NOTIZIE
# Recupera news da NewsAPI, RSS feed e analizza il sentiment
# con VADER (ottimizzato per testo finanziario)
# ============================================================

import logging
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
IT_TZ = ZoneInfo("Europe/Rome")
UTC_TZ = ZoneInfo("UTC")

# Dizionario per mappare simboli a parole chiave di ricerca
SYMBOL_KEYWORDS = {
    'SPY': ['S&P 500', 'SP500', 'stock market', 'wall street', 'equities'],
    'QQQ': ['Nasdaq', 'NASDAQ 100', 'tech stocks', 'technology stocks'],
    'IWM': ['Russell 2000', 'small cap', 'small-cap stocks'],
    'AAPL': ['Apple', 'AAPL', 'iPhone', 'Tim Cook'],
    'MSFT': ['Microsoft', 'MSFT', 'Azure', 'Satya Nadella'],
    'NVDA': ['Nvidia', 'NVDA', 'GPU', 'AI chips', 'Jensen Huang'],
    'TSLA': ['Tesla', 'TSLA', 'Elon Musk', 'electric vehicle', 'EV'],
    'AMZN': ['Amazon', 'AMZN', 'AWS', 'Andy Jassy'],
    'BTC/USD': ['Bitcoin', 'BTC', 'cryptocurrency', 'crypto'],
    'ETH/USD': ['Ethereum', 'ETH', 'crypto', 'DeFi'],
}


class NewsAnalyzer:
    """
    Analizza il sentiment delle notizie finanziarie.

    Fonti:
    - NewsAPI: notizie in tempo reale
    - RSS Feed: Reuters, Bloomberg, CNBC
    - Alpha Vantage: sentiment e earnings calendar

    Analisi:
    - VADER Sentiment Analysis (ottimizzato per social/finance)
    - Peso temporale: ultime 2 ore pesano di più
    """

    def __init__(self, config: dict):
        """
        Inizializza il news analyzer.

        Args:
            config: Configurazione dal config.yaml
        """
        self.config = config
        self.sentiment_config = config.get('strategy_sentiment', {})
        self.api_config = config.get('external_apis', {})
        self.enabled = config.get('strategy_sentiment', {}).get('enabled', True)

        # Pesi temporali
        self.recent_weight = self.sentiment_config.get('recent_news_weight', 0.6)
        self.older_weight = self.sentiment_config.get('older_news_weight', 0.4)
        self.news_window_hours = self.sentiment_config.get('news_window_hours', 24)

        # NewsAPI
        self.newsapi_key = self.api_config.get('newsapi', {}).get('api_key', '')
        self.newsapi_enabled = self.api_config.get('newsapi', {}).get('enabled', True)

        # Alpha Vantage
        self.av_key = self.api_config.get('alpha_vantage', {}).get('api_key', '')
        self.av_enabled = self.api_config.get('alpha_vantage', {}).get('enabled', True)

        # Cache per evitare troppe chiamate API
        self._cache: Dict = {}
        self._cache_duration = 600  # 10 minuti

        # Inizializza VADER
        self._vader = None
        self._init_vader()

        logger.info("NewsAnalyzer inizializzato")

    def _init_vader(self):
        """Inizializza VADER Sentiment Analyzer."""
        try:
            from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
            self._vader = SentimentIntensityAnalyzer()
            logger.debug("VADER Sentiment Analyzer caricato")
        except ImportError:
            try:
                import nltk
                try:
                    from nltk.sentiment.vader import SentimentIntensityAnalyzer
                    self._vader = SentimentIntensityAnalyzer()
                except Exception:
                    nltk.download('vader_lexicon', quiet=True)
                    from nltk.sentiment.vader import SentimentIntensityAnalyzer
                    self._vader = SentimentIntensityAnalyzer()
            except Exception as e:
                logger.warning(f"VADER non disponibile: {e}. Usando sentiment neutro.")

    def analyze_text(self, text: str) -> float:
        """
        Analizza il sentiment di un testo.

        Args:
            text: Testo da analizzare

        Returns:
            Score sentiment da -1 (molto negativo) a +1 (molto positivo)
        """
        if not text:
            return 0.0

        if self._vader:
            try:
                scores = self._vader.polarity_scores(text)
                return scores['compound']  # Valore tra -1 e +1
            except Exception as e:
                logger.debug(f"Errore VADER: {e}")

        # Fallback: analisi delle parole chiave finanziarie
        return self._keyword_sentiment(text)

    def _keyword_sentiment(self, text: str) -> float:
        """
        Analisi sentiment semplificata basata su parole chiave.
        Usata come fallback se VADER non è disponibile.
        """
        text_lower = text.lower()

        bullish_words = [
            'buy', 'bullish', 'upgrade', 'outperform', 'beat', 'strong',
            'growth', 'profit', 'gain', 'rally', 'surge', 'jump', 'rise',
            'positive', 'record', 'breakthrough', 'acquisition', 'partnership'
        ]
        bearish_words = [
            'sell', 'bearish', 'downgrade', 'underperform', 'miss', 'weak',
            'loss', 'decline', 'fall', 'drop', 'crash', 'plunge', 'negative',
            'concern', 'risk', 'lawsuit', 'fraud', 'investigation', 'layoff'
        ]

        bull_count = sum(1 for w in bullish_words if w in text_lower)
        bear_count = sum(1 for w in bearish_words if w in text_lower)
        total = bull_count + bear_count

        if total == 0:
            return 0.0

        return (bull_count - bear_count) / total

    def _is_cache_valid(self, key: str) -> bool:
        """Verifica se il risultato in cache è ancora valido."""
        if key not in self._cache:
            return False
        return (time.time() - self._cache[key]['timestamp']) < self._cache_duration

    def fetch_newsapi(self, symbol: str, hours: int = 24) -> List[Dict]:
        """
        Recupera notizie da NewsAPI.

        Args:
            symbol: Simbolo dell'asset
            hours: Ore di notizie da recuperare

        Returns:
            Lista di articoli con titolo, descrizione, data
        """
        if not self.newsapi_enabled or not self.newsapi_key or self.newsapi_key == 'YOUR_NEWSAPI_KEY':
            return []

        cache_key = f"newsapi_{symbol}_{hours}"
        if self._is_cache_valid(cache_key):
            return self._cache[cache_key]['data']

        try:
            import requests

            keywords = SYMBOL_KEYWORDS.get(symbol, [symbol])
            query = ' OR '.join(f'"{kw}"' for kw in keywords[:3])

            from_time = (datetime.now(UTC_TZ) - timedelta(hours=hours)).isoformat()

            response = requests.get(
                'https://newsapi.org/v2/everything',
                params={
                    'q': query,
                    'from': from_time,
                    'language': 'en',
                    'sortBy': 'publishedAt',
                    'apiKey': self.newsapi_key,
                    'pageSize': 20
                },
                timeout=10
            )

            if response.status_code == 200:
                articles = response.json().get('articles', [])
                result = []
                for art in articles:
                    result.append({
                        'title': art.get('title', ''),
                        'description': art.get('description', ''),
                        'content': art.get('content', ''),
                        'published_at': art.get('publishedAt', ''),
                        'source': art.get('source', {}).get('name', ''),
                        'url': art.get('url', '')
                    })

                self._cache[cache_key] = {'data': result, 'timestamp': time.time()}
                logger.debug(f"NewsAPI: {len(result)} articoli per {symbol}")
                return result
            else:
                logger.warning(f"NewsAPI errore {response.status_code} per {symbol}")

        except Exception as e:
            logger.error(f"Errore NewsAPI per {symbol}: {e}")

        return []

    def fetch_rss_feeds(self, symbol: str) -> List[Dict]:
        """
        Recupera notizie da feed RSS di fonti finanziarie.

        Args:
            symbol: Simbolo dell'asset

        Returns:
            Lista di articoli
        """
        # Feed RSS delle principali fonti finanziarie
        feeds = [
            "https://feeds.reuters.com/reuters/businessNews",
            "https://feeds.finance.yahoo.com/rss/2.0/headline",
            "https://www.cnbc.com/id/10001147/device/rss/rss.html",
        ]

        keywords = SYMBOL_KEYWORDS.get(symbol, [symbol.replace('/USD', '')])
        articles = []

        try:
            import feedparser

            for feed_url in feeds:
                try:
                    feed = feedparser.parse(feed_url)

                    for entry in feed.entries[:10]:
                        title = getattr(entry, 'title', '')
                        summary = getattr(entry, 'summary', '')

                        # Filtra per rilevanza
                        text = (title + ' ' + summary).lower()
                        if any(kw.lower() in text for kw in keywords):
                            published = getattr(entry, 'published', datetime.now().isoformat())
                            articles.append({
                                'title': title,
                                'description': summary,
                                'content': summary,
                                'published_at': published,
                                'source': feed.feed.get('title', 'RSS'),
                                'url': getattr(entry, 'link', '')
                            })

                except Exception as e:
                    logger.debug(f"Errore RSS feed {feed_url}: {e}")

        except ImportError:
            logger.debug("feedparser non disponibile per RSS")

        return articles[:15]  # Limita a 15 articoli per fonte RSS

    def calculate_weighted_sentiment(self, articles: List[Dict]) -> Dict:
        """
        Calcola il sentiment pesato in base alla recenza degli articoli.

        Ultimi 2 ore: peso 60%
        Ultime 24 ore: peso 40%

        Args:
            articles: Lista di articoli con timestamp

        Returns:
            Dizionario con score, recent_score, older_score, article_count
        """
        if not articles:
            return {
                'score': 0.0,
                'recent_score': 0.0,
                'older_score': 0.0,
                'article_count': 0,
                'recent_count': 0,
                'older_count': 0
            }

        now = datetime.now(UTC_TZ)
        two_hours_ago = now - timedelta(hours=2)

        recent_scores = []
        older_scores = []

        for article in articles:
            # Combina titolo e descrizione per l'analisi
            text = f"{article.get('title', '')} {article.get('description', '')}"
            score = self.analyze_text(text)

            # Determina se è recente o meno
            try:
                from dateutil import parser as dateparser
                pub_date = dateparser.parse(article.get('published_at', '')).replace(tzinfo=UTC_TZ)
                if pub_date > two_hours_ago:
                    recent_scores.append(score)
                else:
                    older_scores.append(score)
            except Exception:
                older_scores.append(score)

        # Calcola medie
        recent_avg = sum(recent_scores) / len(recent_scores) if recent_scores else 0
        older_avg = sum(older_scores) / len(older_scores) if older_scores else 0

        # Calcola score pesato
        if recent_scores and older_scores:
            weighted_score = (recent_avg * self.recent_weight) + (older_avg * self.older_weight)
        elif recent_scores:
            weighted_score = recent_avg
        elif older_scores:
            weighted_score = older_avg
        else:
            weighted_score = 0.0

        return {
            'score': round(weighted_score, 4),
            'recent_score': round(recent_avg, 4),
            'older_score': round(older_avg, 4),
            'article_count': len(articles),
            'recent_count': len(recent_scores),
            'older_count': len(older_scores)
        }

    def get_sentiment(self, symbol: str) -> Dict:
        """
        Recupera e analizza il sentiment per un simbolo.

        Args:
            symbol: Simbolo dell'asset

        Returns:
            Dizionario con score e dettagli
        """
        cache_key = f"sentiment_{symbol}"
        if self._is_cache_valid(cache_key):
            return self._cache[cache_key]['data']

        # Recupera notizie da tutte le fonti
        articles = []

        newsapi_articles = self.fetch_newsapi(symbol, self.news_window_hours)
        articles.extend(newsapi_articles)

        rss_articles = self.fetch_rss_feeds(symbol)
        articles.extend(rss_articles)

        # Rimuovi duplicati basandosi sul titolo
        seen_titles = set()
        unique_articles = []
        for art in articles:
            title = art.get('title', '')
            if title and title not in seen_titles:
                seen_titles.add(title)
                unique_articles.append(art)

        # Calcola sentiment pesato
        sentiment = self.calculate_weighted_sentiment(unique_articles)
        sentiment['symbol'] = symbol
        sentiment['timestamp'] = datetime.now().isoformat()
        sentiment['sources_count'] = len(unique_articles)

        # Classifica il sentiment
        score = sentiment['score']
        if score > 0.4:
            sentiment['classification'] = 'VERY_BULLISH'
        elif score > 0.15:
            sentiment['classification'] = 'BULLISH'
        elif score > -0.15:
            sentiment['classification'] = 'NEUTRAL'
        elif score > -0.4:
            sentiment['classification'] = 'BEARISH'
        else:
            sentiment['classification'] = 'VERY_BEARISH'

        self._cache[cache_key] = {'data': sentiment, 'timestamp': time.time()}

        logger.debug(f"[{symbol}] Sentiment: {score:.3f} ({sentiment['classification']}) - {len(unique_articles)} articoli")
        return sentiment
