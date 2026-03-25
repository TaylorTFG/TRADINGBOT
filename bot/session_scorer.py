# ============================================================
# SESSION SCORER - Daily Trading Quality Assessment
# Calcola punteggio 0-10 della qualità di una sessione di trading
# ============================================================

import logging
from datetime import datetime, date
from typing import Dict, Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
IT_TZ = ZoneInfo("Europe/Rome")


class SessionScorer:
    """
    Valuta la qualità della sessione di trading odierna (0-10).

    Score è basato su:
    1. Volatility Percentile (40% weight): ATR medio vs storico
    2. Volume Percentile (30% weight): Volume medio vs storico
    3. Win Rate Percentile (30% weight): % vittorie ultimi giorni

    Utilizzo:
    - Score >= 9: Condizioni OTTIMALI → size +20% (1.2x)
    - Score 6-9: Condizioni NORMALI → size standard (1.0x)
    - Score < 6: Condizioni POVERE → size -50% (0.5x)

    Logica:
    - Sessioni con alta volatilità e volume permettono scalping più aggressivo
    - Sessioni con win rate alta su ultimi giorni = momentum positivo
    - Combinazione di questi fattori = score più alto = più capitale allocato

    Razionale:
    - In condizioni ottimali, la probabilità di successo aumenta
    - In condizioni povere, riduciamo exposure per proteggere capitale
    - Questo adatta il position sizing alla "salute" del mercato
    """

    def __init__(self, config: dict, database):
        """Inizializza Session Scorer."""
        self.config = config
        self.db = database
        self.percentile_window = 60  # Ultimi 60 giorni per storico

        # Metriche di sessione (risettiamo ogni giorno)
        self._session_date: Optional[date] = None
        self._session_score: Optional[float] = None
        self._session_multiplier: Optional[float] = None

        logger.info(f"SessionScorer inizializzato (window={self.percentile_window} days)")

    def calculate_session_score(self) -> Dict:
        """
        Calcola lo score della sessione odierna (0-10).

        Ritorna un dizionario con:
        {
            'session_score': float (0-10),
            'volatility_pct': float (0-100 percentile),
            'volume_pct': float (0-100 percentile),
            'winrate_pct': float (0-100 percentile),
            'size_multiplier': float (0.5, 1.0, 1.2),
            'reason': str,
            'timestamp': str
        }
        """
        today = datetime.now(IT_TZ).date()

        # Cache: Se già calcolato oggi, riusa lo stesso score
        if self._session_date == today and self._session_score is not None:
            return {
                'session_score': self._session_score,
                'volatility_pct': self._volatility_pct,
                'volume_pct': self._volume_pct,
                'winrate_pct': self._winrate_pct,
                'size_multiplier': self._session_multiplier,
                'reason': 'Cached from earlier today',
                'timestamp': datetime.now(IT_TZ).isoformat(),
                'cached': True
            }

        try:
            # ---- METRIC 1: Volatility Percentile ----
            # (usare ATR medio del giorno vs storico)
            volatility_pct = self._calculate_volatility_percentile()

            # ---- METRIC 2: Volume Percentile ----
            # (usare volume medio del giorno vs storico)
            volume_pct = self._calculate_volume_percentile()

            # ---- METRIC 3: Win Rate Percentile ----
            # (% victorie ultimi 60 giorni vs media storica)
            winrate_pct = self._calculate_winrate_percentile()

            # ---- COMBINE METRICS ----
            # Score = (vol*0.4 + vol*0.3 + wr*0.3) / 10
            # Ritorna valore 0-10
            session_score = (
                volatility_pct * 0.4 +
                volume_pct * 0.3 +
                winrate_pct * 0.3
            ) / 10.0

            session_score = min(10.0, max(0.0, session_score))

            # ---- SIZE MULTIPLIER ----
            size_multiplier = self._get_size_multiplier(session_score)

            # Cache per il giorno
            self._session_date = today
            self._session_score = session_score
            self._session_multiplier = size_multiplier
            self._volatility_pct = volatility_pct
            self._volume_pct = volume_pct
            self._winrate_pct = winrate_pct

            reason = (
                f"VOL={volatility_pct:.0f}% + VOL={volume_pct:.0f}% + WR={winrate_pct:.0f}% "
                f"= Score {session_score:.1f}/10 → {size_multiplier}x"
            )

            result = {
                'session_score': round(session_score, 1),
                'volatility_pct': round(volatility_pct, 1),
                'volume_pct': round(volume_pct, 1),
                'winrate_pct': round(winrate_pct, 1),
                'size_multiplier': size_multiplier,
                'reason': reason,
                'timestamp': datetime.now(IT_TZ).isoformat(),
                'cached': False
            }

            logger.info(f"Session Score: {session_score:.1f}/10 (mult={size_multiplier}x) | {reason}")
            return result

        except Exception as e:
            logger.error(f"Errore calcolo session score: {e}")
            # Default: score neutro
            return {
                'session_score': 5.0,
                'volatility_pct': 50.0,
                'volume_pct': 50.0,
                'winrate_pct': 50.0,
                'size_multiplier': 1.0,
                'reason': f'Errore: {str(e)}',
                'timestamp': datetime.now(IT_TZ).isoformat(),
                'cached': False
            }

    def _calculate_volatility_percentile(self) -> float:
        """
        Calcola percentile di volatilità odierna vs ultimi 60 giorni.

        Ritorna 0-100 (0 = meno volatile del 100%, 100 = più volatile del 100%)
        """
        try:
            # TODO: Richiedere ATR medio odierno dal database o broker
            # Per ora, ritorniamo 50 (neutro)
            # In realtà dovremmo:
            # 1. Calcolare ATR medio su trades odierni
            # 2. Confrontare con media ATR degli ultimi 60 giorni
            # 3. Ritornare percentile

            # Placeholder
            return 50.0

        except Exception as e:
            logger.warning(f"Errore calcolo volatility percentile: {e}")
            return 50.0

    def _calculate_volume_percentile(self) -> float:
        """
        Calcola percentile di volume odierno vs ultimi 60 giorni.

        Ritorna 0-100 (0 = meno volume del 100%, 100 = più volume del 100%)
        """
        try:
            # TODO: Richiedere volume medio odierno dal database
            # In realtà dovremmo:
            # 1. Calcolare volume medio su trades odierni
            # 2. Confrontare con media volume degli ultimi 60 giorni
            # 3. Ritornare percentile

            # Placeholder
            return 50.0

        except Exception as e:
            logger.warning(f"Errore calcolo volume percentile: {e}")
            return 50.0

    def _calculate_winrate_percentile(self) -> float:
        """
        Calcola percentile di win rate storica.

        Prende i dati degli ultimi 60 giorni e ritorna:
        - 100 se win rate odierno è nel 100° percentile (altissimo)
        - 50 se win rate odierno è nella media
        - 0 se win rate odierno è nel 0° percentile (bassissimo)
        """
        try:
            # Prendi i trade odierni
            today = datetime.now(IT_TZ).date()
            today_trades = self.db.get_trade_history_by_date(today)

            if not today_trades or len(today_trades) < 1:
                # Se no trade oggi, usa media storica (50° percentile)
                return 50.0

            # Calcola win rate odierno
            wins = len([t for t in today_trades if t.get('pnl', 0) > 0])
            today_wr = wins / len(today_trades) if today_trades else 0.0

            # Prendi media storica (ultimi 60 giorni)
            historical_trades = self.db.get_trade_history(limit=500)  # ~60 giorni
            if historical_trades:
                hist_wins = len([t for t in historical_trades if t.get('pnl', 0) > 0])
                hist_wr = hist_wins / len(historical_trades)
            else:
                hist_wr = 0.5

            # Calcola percentile
            # Se today_wr > hist_wr, score aumenta
            # Se today_wr < hist_wr, score diminuisce
            if hist_wr > 0:
                percentile = (today_wr / hist_wr) * 100
                percentile = min(100, percentile)  # Cap a 100
            else:
                percentile = 50.0

            return percentile

        except Exception as e:
            logger.warning(f"Errore calcolo winrate percentile: {e}")
            return 50.0

    @staticmethod
    def _get_size_multiplier(score: float) -> float:
        """
        Ritorna moltiplicatore di position sizing basato su score.

        Score 0-10 → Multiplier 0.5x a 1.2x

        Mapping:
        - Score 0-5: 0.5x (condizioni povere, riduci size)
        - Score 5-7: 0.75x a 1.0x
        - Score 7-9: 1.0x (size normale)
        - Score 9-10: 1.2x (condizioni ottimali, aumenta size)
        """
        if score >= 9:
            return 1.2  # +20% in condizioni ottimali
        elif score >= 6:
            return 1.0  # Size normale
        elif score >= 5:
            return 0.75  # -25% in condizioni moderate
        else:
            return 0.5  # -50% in condizioni povere

    def reset_daily_cache(self) -> None:
        """Reset cache daily (chiamare a inizio giorno)."""
        self._session_date = None
        self._session_score = None
        self._session_multiplier = None
        logger.debug("SessionScorer cache resetted for new day")
