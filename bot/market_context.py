# ============================================================
# MARKET CONTEXT - ANALISI CONTESTO MACRO
# Monitora VIX, correlazioni SP500, oro/obbligazioni
# per determinare il regime di mercato attuale
# ============================================================

import logging
from datetime import datetime, timedelta
from typing import Optional, Dict
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
IT_TZ = ZoneInfo("Europe/Rome")


class MarketContextAnalyzer:
    """
    Analizza il contesto macro del mercato per filtrare i segnali.

    Monitora:
    - VIX: indice della paura (>30 = risk-off estremo)
    - SP500: trend giornaliero (-2% = stop nuovi acquisti)
    - Safe Haven: correlazione oro/obbligazioni (risk-off/risk-on)
    """

    def __init__(self, broker, config: dict):
        """
        Inizializza l'analizzatore di contesto macro.

        Args:
            broker: Istanza del BrokerClient per recuperare dati
            config: Configurazione dal config.yaml
        """
        self.broker = broker
        self.config = config
        self.macro_config = config.get('market_context', {})

        # Soglie di configurazione
        self.vix_high_threshold = self.macro_config.get('vix', {}).get('high_threshold', 30)
        self.sp500_max_drop = self.macro_config.get('sp500', {}).get('max_daily_drop_pct', 0.02)
        self.gold_symbol = self.macro_config.get('safe_haven', {}).get('gold_symbol', 'GLD')
        self.bonds_symbol = self.macro_config.get('safe_haven', {}).get('bonds_symbol', 'TLT')

        # Cache per evitare troppe chiamate API
        self._cache = {}
        self._cache_duration = 300  # 5 minuti

    def _is_cache_valid(self, key: str) -> bool:
        """Verifica se la cache è ancora valida."""
        if key not in self._cache:
            return False
        cached_at = self._cache[key].get('timestamp', 0)
        return (datetime.now().timestamp() - cached_at) < self._cache_duration

    def _get_cached_or_fetch(self, key: str, fetch_func):
        """Restituisce il valore dalla cache o lo recupera frescos."""
        if self._is_cache_valid(key):
            return self._cache[key]['value']

        try:
            value = fetch_func()
            self._cache[key] = {
                'value': value,
                'timestamp': datetime.now().timestamp()
            }
            return value
        except Exception as e:
            logger.error(f"Errore recupero {key}: {e}")
            return None

    # ----------------------------------------------------------------
    # VIX - VOLATILITY INDEX
    # ----------------------------------------------------------------

    def get_vix_level(self) -> Optional[float]:
        """
        Recupera il livello attuale del VIX.

        Returns:
            Livello VIX attuale o None in caso di errore
        """
        def fetch():
            bars = self.broker.get_recent_bars('VIXY', '1d', 5)
            if bars is not None and not bars.empty:
                return float(bars['close'].iloc[-1])
            # Fallback su SPY volatilità implicita
            return None

        return self._get_cached_or_fetch('vix', fetch)

    def is_high_vix(self) -> bool:
        """
        Verifica se il VIX è ad un livello di paura elevata.

        Returns:
            True se VIX > soglia configurata (default 30)
        """
        if not self.macro_config.get('vix', {}).get('enabled', True):
            return False

        vix = self.get_vix_level()
        if vix is None:
            return False  # In caso di dubbio, non bloccare

        is_high = vix > self.vix_high_threshold
        if is_high:
            logger.warning(f"VIX alto: {vix:.2f} > {self.vix_high_threshold}")
        return is_high

    def get_vix_regime(self) -> str:
        """
        Classifica il regime di volatilità attuale.

        Returns:
            'low' (<15), 'medium' (15-25), 'high' (25-35), 'extreme' (>35)
        """
        vix = self.get_vix_level()
        if vix is None:
            return 'unknown'

        if vix < 15:
            return 'low'
        elif vix < 25:
            return 'medium'
        elif vix < 35:
            return 'high'
        else:
            return 'extreme'

    def get_size_multiplier(self) -> float:
        """
        Calcola il moltiplicatore della size in base al VIX.
        Per crypto-only mode: VIX azionario non applicabile.

        Returns:
            1.0 = size normale, 0.5 = size dimezzata
        """
        # Per crypto-only mode: VIX azionario non applicabile
        assets_config = self.config.get('assets', {})
        only_crypto = (
            not assets_config.get('etf', {}).get('enabled', False) and
            not assets_config.get('stocks', {}).get('enabled', False) and
            assets_config.get('crypto', {}).get('enabled', True)
        )
        if only_crypto:
            return 1.0  # VIX non applicabile per crypto-only scalping

        # Logica originale per modalità misto stock+crypto
        vix = self.get_vix_level()
        if vix is None:
            return 1.0

        if vix > self.vix_high_threshold:
            logger.info(f"VIX={vix:.2f}: size dimezzata (modalità mista)")
            return 0.5
        return 1.0

    # ----------------------------------------------------------------
    # SP500 - TREND GIORNALIERO
    # ----------------------------------------------------------------

    def get_sp500_daily_change(self) -> Optional[float]:
        """
        Recupera la variazione percentuale giornaliera dell'SP500.

        Returns:
            Variazione percentuale (es. -0.025 = -2.5%)
        """
        def fetch():
            bars = self.broker.get_recent_bars('SPY', '1d', 5)
            if bars is not None and len(bars) >= 2:
                today_close = float(bars['close'].iloc[-1])
                yesterday_close = float(bars['close'].iloc[-2])
                return (today_close - yesterday_close) / yesterday_close
            return None

        return self._get_cached_or_fetch('sp500_change', fetch)

    def is_sp500_crash(self) -> bool:
        """
        Verifica se SP500 ha perso più del 2% oggi.

        Returns:
            True se il calo supera la soglia → stop nuovi acquisti
        """
        if not self.macro_config.get('sp500', {}).get('enabled', True):
            return False

        change = self.get_sp500_daily_change()
        if change is None:
            return False

        is_crash = change <= -self.sp500_max_drop
        if is_crash:
            logger.warning(f"SP500 in calo: {change:.2%} - Stop nuovi acquisti")
        return is_crash

    # ----------------------------------------------------------------
    # SAFE HAVEN - ORO E OBBLIGAZIONI
    # ----------------------------------------------------------------

    def get_safe_haven_status(self) -> Dict:
        """
        Analizza il movimento di oro e obbligazioni per determinare
        se il mercato è in modalità risk-off.

        Returns:
            Dizionario con gold_change, bonds_change, is_risk_off
        """
        if not self.macro_config.get('safe_haven', {}).get('enabled', True):
            return {'is_risk_off': False}

        def fetch_gold():
            bars = self.broker.get_recent_bars(self.gold_symbol, '1d', 5)
            if bars is not None and len(bars) >= 2:
                return (float(bars['close'].iloc[-1]) - float(bars['close'].iloc[-2])) / float(bars['close'].iloc[-2])
            return None

        def fetch_bonds():
            bars = self.broker.get_recent_bars(self.bonds_symbol, '1d', 5)
            if bars is not None and len(bars) >= 2:
                return (float(bars['close'].iloc[-1]) - float(bars['close'].iloc[-2])) / float(bars['close'].iloc[-2])
            return None

        gold_change = self._get_cached_or_fetch('gold_change', fetch_gold)
        bonds_change = self._get_cached_or_fetch('bonds_change', fetch_bonds)

        # Risk-off: oro e obbligazioni salgono entrambi
        is_risk_off = False
        if gold_change is not None and bonds_change is not None:
            is_risk_off = gold_change > 0.005 and bonds_change > 0.005  # Entrambi su >0.5%

        if is_risk_off:
            logger.warning(f"Risk-off: Oro +{gold_change:.2%}, Bond +{bonds_change:.2%}")

        return {
            'gold_change': gold_change,
            'bonds_change': bonds_change,
            'is_risk_off': is_risk_off
        }

    def is_risk_off_environment(self) -> bool:
        """Verifica se il mercato è in modalità risk-off."""
        return self.get_safe_haven_status().get('is_risk_off', False)

    # ----------------------------------------------------------------
    # ANALISI COMPLETA CONTESTO
    # ----------------------------------------------------------------

    def get_full_context(self) -> Dict:
        """
        Restituisce un'analisi completa del contesto macro.

        Returns:
            Dizionario con tutti gli indicatori macro e raccomandazioni
        """
        vix_level = self.get_vix_level()
        vix_regime = self.get_vix_regime()
        sp500_change = self.get_sp500_daily_change()
        safe_haven = self.get_safe_haven_status()
        size_multiplier = self.get_size_multiplier()

        # Determina se è sicuro operare
        can_trade_long = True
        warnings = []

        if self.is_high_vix():
            warnings.append(f"VIX alto ({vix_level:.1f}): size ridotta al 50%")

        if self.is_sp500_crash():
            can_trade_long = False
            warnings.append(f"SP500 -2%+: stop nuovi acquisti long")

        if safe_haven.get('is_risk_off'):
            can_trade_long = False
            warnings.append("Risk-off: oro e obbligazioni in rialzo")

        context = {
            'timestamp': datetime.now().isoformat(),
            'vix': {
                'level': vix_level,
                'regime': vix_regime,
                'is_high': vix_level > self.vix_high_threshold if vix_level else False,
            },
            'sp500': {
                'daily_change': sp500_change,
                'is_crashing': sp500_change <= -self.sp500_max_drop if sp500_change is not None else False,
            },
            'safe_haven': safe_haven,
            'size_multiplier': size_multiplier,
            'can_trade_long': can_trade_long,
            'warnings': warnings,
            'market_regime': self._determine_regime(vix_regime, sp500_change, safe_haven)
        }

        return context

    def _determine_regime(self, vix_regime: str, sp500_change: Optional[float], safe_haven: Dict) -> str:
        """
        Determina il regime di mercato complessivo.

        Returns:
            'bullish', 'neutral', 'cautious', 'bearish', 'panic'
        """
        if vix_regime == 'extreme' or safe_haven.get('is_risk_off'):
            return 'panic'
        elif vix_regime == 'high' or (sp500_change and sp500_change <= -0.02):
            return 'bearish'
        elif vix_regime == 'medium':
            if sp500_change and sp500_change > 0:
                return 'neutral'
            return 'cautious'
        else:  # low VIX
            if sp500_change and sp500_change > 0.005:
                return 'bullish'
            return 'neutral'

    def should_reduce_size(self) -> bool:
        """Verifica se le condizioni macro richiedono una riduzione delle size."""
        return self.get_size_multiplier() < 1.0

    def should_stop_trading(self) -> bool:
        """Verifica se le condizioni macro sono così avverse da fermare il trading."""
        # Per crypto-only: ignora VIX e SP500 (entrambi azionari)
        assets_config = self.config.get('assets', {})
        only_crypto = (
            not assets_config.get('etf', {}).get('enabled', False) and
            not assets_config.get('stocks', {}).get('enabled', False)
        )
        if only_crypto:
            return False  # Crypto opera H24 indipendentemente dai mercati azionari

        return self.is_sp500_crash() or self.is_risk_off_environment()
