# ============================================================
# ENGINE - LOOP PRINCIPALE DEL BOT
# Coordina tutte le componenti: strategie, risk manager,
# broker, ML filter, notifiche e database
# ============================================================

import logging
import time
import yaml
import schedule
import warnings
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from zoneinfo import ZoneInfo

# Silenzio FutureWarning di Pandas (ChainedAssignment) per log puliti
warnings.filterwarnings('ignore', category=FutureWarning)

from bot.broker import BrokerClient
from bot.database import DatabaseManager
from bot.risk_manager import RiskManager
from bot.market_context import MarketContextAnalyzer
from bot.strategy_confluence import ConfluenceStrategy
from bot.strategy_breakout import BreakoutStrategy
from bot.strategy_sentiment import SentimentStrategy
from bot.strategy_rsi_divergence import RSIDivergenceStrategy
from bot.strategy_sr_bounce import SRBounceStrategy
from bot.strategy_mtf_confluence import MTFConfluenceStrategy
from bot.news_analyzer import NewsAnalyzer
from bot.meta_strategy import MetaStrategy
from bot.ml_filter import MLFilter
from bot.notifications import TelegramNotifier
from bot.status_updater import StatusUpdater
from bot.regime_detector import RegimeDetector
from bot.correlation_guard import CorrelationGuard
from bot.session_scorer import SessionScorer
from bot.kelly_sizing import KellySizing
from bot.performance_tracker import PerformanceTracker

logger = logging.getLogger(__name__)
IT_TZ = ZoneInfo("Europe/Rome")


class TradingEngine:
    """
    Motore principale del trading bot.

    Gestisce il loop operativo:
    1. Verifica orari e condizioni di mercato
    2. Selezione automatica migliori asset
    3. Analisi multi-strategia per ogni asset
    4. Sistema di voto finale
    5. Filtro ML
    6. Esecuzione ordini con risk management
    7. Monitoring posizioni aperte (stop loss, trailing, take profit)
    8. Report e notifiche
    """

    def __init__(self, config_path: str = "config.yaml"):
        """
        Inizializza il trading engine.

        Args:
            config_path: Percorso del file di configurazione
        """
        # Carica configurazione
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)

        # Stato del bot
        self.running = False
        self.paused = False

        # Tasso di cambio EUR/USD (approssimativo)
        self._eur_usd_rate = 1.09

        # Capitale virtuale: parte da capital_eur configurato, non dai $100k di Alpaca.
        # Tutti i calcoli di sizing e i limiti giornalieri usano questo valore.
        capital_eur = self.config.get('trading', {}).get('capital_eur', 500)
        self._initial_virtual_capital: float = capital_eur * self._eur_usd_rate
        self._virtual_capital: float = self._initial_virtual_capital
        self._daily_starting_capital: Optional[float] = None
        self._weekly_starting_capital: Optional[float] = None

        # Paper trading tracker
        self._profitable_days: int = 0
        self._paper_start_date: Optional[datetime] = None

        # Pending Limit Orders per Order Chase (3 candele timeout)
        self._pending_orders: Dict[str, Dict] = {}  # {order_id: {symbol, qty, side, ...}}

        # Inizializza componenti
        self._init_components()

        # Pianifica tasks periodici
        self._setup_scheduled_tasks()

        logger.info("TradingEngine inizializzato")

    def _init_components(self):
        """Inizializza tutti i componenti del bot."""
        logger.info("Inizializzazione componenti...")

        # Database
        db_path = self.config.get('database', {}).get('path', 'data/trades.db')
        self.db = DatabaseManager(db_path)

        # Broker (Alpaca)
        self.broker = BrokerClient(self.config)

        # Risk Manager
        self.risk_manager = RiskManager(self.config, self.db)

        # Contesto Macro
        self.market_context = MarketContextAnalyzer(self.broker, self.config)

        # News Analyzer
        self.news_analyzer = NewsAnalyzer(self.config)

        # Strategie (6 totali: 4 originali + 2 nuove)
        self.strategy_confluence = ConfluenceStrategy(self.config)
        self.strategy_breakout = BreakoutStrategy(self.config)
        self.strategy_sentiment = SentimentStrategy(self.news_analyzer, self.config)
        self.strategy_rsi_divergence = RSIDivergenceStrategy(self.config)
        self.strategy_sr_bounce = SRBounceStrategy(self.config)
        self.strategy_mtf_confluence = MTFConfluenceStrategy(self.config)

        # Meta-Strategy (sistema di voto)
        self.meta_strategy = MetaStrategy(self.config)

        # ML Filter
        self.ml_filter = MLFilter(self.config, self.db)

        # Notifiche Telegram (disabilitato per locale)
        # self.notifier = TelegramNotifier(self.config)
        self.notifier = None  # Disabilitato localmente

        # Status Updater (aggiorna bot_status.json per dashboard)
        self.status_updater = StatusUpdater(self.config)

        # ---- NUOVI MODULI (8 Modifiche) ----
        # Regime Detector (classifica mercato TRENDING/RANGING/UNDEFINED)
        self.regime_detector = RegimeDetector(self.config)

        # Correlation Guard (evita posizioni correlate)
        self.correlation_guard = CorrelationGuard()

        # Session Scorer (valuta qualità sessione 0-10)
        self.session_scorer = SessionScorer(self.config, self.db)

        # Kelly Sizing (position sizing basato su edge)
        self.kelly_sizing = KellySizing(self.config, self.db)

        # Performance Tracker (metriche avanzate)
        self.performance_tracker = PerformanceTracker(self.config, self.db)

        logger.info("Tutti i componenti inizializzati (inclusi 5 nuovi moduli)")

    def _setup_scheduled_tasks(self):
        """Pianifica i task periodici (report, retraining ML, ecc.)."""
        tg_config = self.config.get('telegram', {})

        # Report giornaliero
        daily_time = tg_config.get('daily_report_time', '22:30')
        schedule.every().day.at(daily_time).do(self._send_daily_report)

        # Report settimanale (venerdì)
        weekly_time = tg_config.get('weekly_report_time', '22:00')
        schedule.every().friday.at(weekly_time).do(self._send_weekly_report)

        # Reset stato giornaliero a mezzanotte
        schedule.every().day.at('00:01').do(self._daily_reset)

        # Controllo retraining ML (domenica mattina)
        schedule.every().sunday.at('02:00').do(self._retrain_ml_if_needed)

        logger.info("Task schedulati configurati")

    # ----------------------------------------------------------------
    # CICLO PRINCIPALE
    # ----------------------------------------------------------------

    def start(self):
        """Avvia il bot di trading."""
        logger.info("=" * 60)
        logger.info("TRADING BOT AVVIATO")
        logger.info(f"Modalità: {self.config['trading']['mode'].upper()}")
        logger.info("=" * 60)

        # Verifica connessione
        if not self.broker.is_connected():
            logger.error("Impossibile connettersi ad Alpaca. Verifica le credenziali in config.yaml")
            return

        # Carica capitale virtuale da file (se bot già avviato in precedenza)
        # Carica capitale dal file (se esiste) o usa config
        self._virtual_capital = self._load_virtual_capital()
        self._daily_starting_capital = self._virtual_capital
        self._weekly_starting_capital = self._virtual_capital

        # Verifica se capital_eur è cambiato (e.g., da €500 a €2500)
        # Se cambiato, ricalcola il capitale virtuale
        capital_eur = self.config.get('trading', {}).get('capital_eur', 500)
        expected_virtual_capital = capital_eur * self._eur_usd_rate

        if abs(self._virtual_capital - expected_virtual_capital) > 1:  # Tolleranza $1
            logger.warning(
                f"Rilevato cambio capitale: era ${self._virtual_capital:.2f}, "
                f"ora €{capital_eur} = ${expected_virtual_capital:.2f}"
            )
            self._initial_virtual_capital = expected_virtual_capital
            self._virtual_capital = expected_virtual_capital
            self._daily_starting_capital = expected_virtual_capital
            self._weekly_starting_capital = expected_virtual_capital

        logger.info(f"Capitale virtuale: €{capital_eur} = ${self._virtual_capital:.2f} USD")
        logger.info(f"(Account Alpaca paper: $100,000 — usato solo come esecutore ordini)")

        # Sincronizza posizioni DB con Alpaca
        self._sync_positions_with_alpaca()

        # Notifica avvio (aggiorna dashboard status)
        self.status_updater.update_status('started')

        # Segna data inizio paper trading
        if self.config['trading']['mode'] == 'paper':
            self._paper_start_date = datetime.now(IT_TZ)

        self.running = True

        # Loop principale
        while self.running:
            try:
                # Esegui task schedulati
                schedule.run_pending()

                # Verifica se il bot deve essere in pausa
                if self.paused or self.risk_manager.is_paused():
                    logger.debug("Bot in pausa - attendo...")
                    time.sleep(60)
                    continue

                # Ciclo di trading (SCALPING: ogni 15 secondi)
                self._trading_cycle()

                # Attendi prima del prossimo ciclo (15 secondi per scalping)
                time.sleep(15)

            except KeyboardInterrupt:
                logger.info("Interruzione manuale ricevuta")
                self.stop()
                break
            except Exception as e:
                logger.error(f"Errore nel ciclo principale: {e}", exc_info=True)
                self.db.log_event('ERROR', f'Errore ciclo principale: {str(e)}')
                time.sleep(60)  # Attendi prima di riprovare

    def stop(self):
        """Ferma il bot e chiude tutte le posizioni aperte."""
        logger.info("Arresto bot in corso...")
        self.running = False

        # Chiudi tutte le posizioni aperte prima di uscire
        if self.config['trading'].get('close_on_stop', True):
            open_positions = self.broker.get_positions()
            if open_positions:
                logger.info(f"Chiusura {len(open_positions)} posizioni aperte...")
                self.broker.close_all_positions()

        self.status_updater.update_status('stopped')
        logger.info("Bot fermato")

    def pause(self):
        """Mette il bot in pausa (senza chiudere posizioni)."""
        self.paused = True
        logger.info("Bot messo in pausa")
        self.status_updater.update_status('paused', 'Pausa manuale')

    def resume(self):
        """Riprende il bot dalla pausa."""
        self.paused = False
        logger.info("Bot ripreso dalla pausa")

    # ----------------------------------------------------------------
    # CICLO DI TRADING
    # ----------------------------------------------------------------

    def _trading_cycle(self):
        """
        Esegue un ciclo completo di analisi e trading.

        Fasi:
        1. Verifica orari operativi"""
        logger.info("=== CICLO TRADING INIZIATO ===" )

        """
        2. Verifica condizioni macro
        3. Monitora posizioni aperte
        4. Seleziona migliori asset
        5. Analizza e trada
        """
        now = datetime.now(IT_TZ)

        # --- FASE 1: Verifica chiusura forzata (solo se configurata) ---
        force_close_time = self.config['trading'].get('force_close_time', None)
        if force_close_time and self.risk_manager.should_force_close(force_close_time):
            logger.info("FASE 1: Chiusura forzata - ciclo saltato")
            open_trades = self.db.get_open_trades()
            if open_trades:
                logger.info("Chiusura forzata posizioni per fine giornata")
                self._close_all_positions("Chiusura fine giornata")
            return

        # --- FASE 2: SCALPING H24 --- Nessun check orari, opera sempre per crypto ---
        # (H24 crypto scalping, nessuna pausa oraria)

        # --- FASE 3: Verifica limiti giornalieri sul capitale virtuale ---
        current_capital = self._virtual_capital  # Usa capitale virtuale (es. $545), non i $100k Alpaca

        if self._daily_starting_capital and self._daily_starting_capital > 0:
            daily_check = self.risk_manager.check_daily_limits(
                current_capital,
                self._daily_starting_capital
            )
            if not daily_check['can_trade']:
                logger.warning(f"FASE 3: Daily limits raggiunto - {daily_check.get('reason', '')}")
                if 'Perdita' in daily_check.get('reason', ''):
                    if self.notifier:
                        if self.notifier:
                            self.notifier.notify_daily_drawdown(
                            abs(daily_check.get('daily_pnl_pct', 0)),
                            current_capital
                        )
                    self.paused = True
                return

        # --- FASE 4: Regime Detection (NUOVO) ---
        # Classifica il mercato e seleziona strategie rilevanti
        best_assets_temp = self._select_best_assets()
        if best_assets_temp:
            try:
                # Recupera 200 candele 1min da BTC/USD per regime detection accurato
                df_regime = self.broker.get_recent_bars("BTC/USD", '1m', 200)
                regime_info = self.regime_detector.detect_regime(df_regime)
                self._current_regime = regime_info

                # Macro context regime (non usato come proxy per gli asset)
                logger.debug(
                    f"BTC Macro Regime: {regime_info['regime']} | ADX={regime_info.get('adx', 0):.1f} | "
                    f"CI={regime_info.get('choppiness', 0):.1f}"
                )
            except Exception as e:
                logger.debug(f"Errore regime detection BTC: {e}")

        # --- FASE 5: Session Scoring (NUOVO) ---
        # Valuta qualità della sessione per adaptive sizing
        session_info = self.session_scorer.calculate_session_score()
        self._session_size_multiplier = session_info.get('size_multiplier', 1.0)

        # --- FASE 6: Contesto macro ---
        if self.market_context.should_stop_trading():
            logger.warning("FASE 6: Condizioni macro avverse - stop nuovi acquisti")
            return

        macro_multiplier = self.market_context.get_size_multiplier()

        # --- FASE 7: Monitora posizioni aperte ---
        self._monitor_open_positions(current_capital)

        # --- FASE 6: Verifica se ML deve essere riaddestrato ---
        if self.ml_filter.should_retrain():
            logger.info("Avvio retraining ML schedulato")
            self._retrain_ml_if_needed()

        # --- FASE 7: Seleziona e analizza asset ---
        open_trades = self.db.get_open_trades()
        if len(open_trades) >= self.config['trading'].get('max_open_positions', 6):
            logger.debug("Numero massimo posizioni aperte raggiunto")
            return

        # Seleziona i migliori asset del momento
        best_assets = self._select_best_assets()

        # Analizza ogni asset selezionato
        for symbol in best_assets:
            try:
                self._analyze_and_trade(
                    symbol,
                    current_capital,
                    macro_multiplier,
                    open_trades
                )
            except Exception as e:
                logger.error(f"Errore analisi {symbol}: {e}", exc_info=True)

        # --- CICLO COMPLETATO: Summary Log con moltiplicatori ---
        open_count = len(self.db.get_open_trades())
        today_stats = self.db.get_today_stats()
        trades_today = today_stats.get('total_trades', 0) or 0
        pnl_today = today_stats.get('total_pnl', 0) or 0
        win_count = today_stats.get('winning', 0) or 0
        loss_count = today_stats.get('losing', 0) or 0

        # Calcola moltiplicatori attuali per diagnostica
        vix_mult = self.market_context.get_size_multiplier()
        kelly_info = self.kelly_sizing.calculate_kelly_fraction()
        kelly_mult = kelly_info.get('position_size_pct', 0.15) / 0.15
        session_mult = self._session_size_multiplier

        logger.info(
            f"CICLO | Open={open_count}/2 | Trades={trades_today} | "
            f"P&L={pnl_today:+.2f}$ | W={win_count} L={loss_count} | "
            f"Cap=${current_capital:.2f} | "
            f"Sizing: VIX={vix_mult:.1f}× Kelly={kelly_mult:.2f}× Sess={session_mult:.1f}× "
            f"→ {vix_mult*kelly_mult*session_mult:.2f}× totale"
        )

    # ----------------------------------------------------------------
    # SELEZIONE ASSET
    # ----------------------------------------------------------------

    def _select_best_assets(self) -> List[str]:
        """
        Seleziona automaticamente i migliori asset in base a:
        - Volume (liquidità)
        - Volatilità (ATR) - più opportunità
        - Momentum (performance ultime 24 ore)

        Returns:
            Lista ordinata di simboli per priorità
        """
        all_assets = []
        assets_config = self.config.get('assets', {})

        # Raccogli tutti gli asset abilitati
        if assets_config.get('etf', {}).get('enabled', True):
            all_assets.extend(assets_config['etf'].get('symbols', []))

        if assets_config.get('stocks', {}).get('enabled', True):
            all_assets.extend(assets_config['stocks'].get('symbols', []))

        if assets_config.get('crypto', {}).get('enabled', True):
            all_assets.extend(assets_config['crypto'].get('symbols', []))

        max_assets = assets_config.get('max_assets_per_cycle', 5)

        # Calcola score per ogni asset
        scored_assets = []
        for symbol in all_assets:
            try:
                score = self._calculate_asset_score(symbol)
                scored_assets.append((symbol, score))
            except Exception as e:
                logger.debug(f"Errore calcolo score per {symbol}: {e}")
                scored_assets.append((symbol, 0))

        # Ordina per score decrescente
        scored_assets.sort(key=lambda x: x[1], reverse=True)

        selected = [s[0] for s in scored_assets[:max_assets]]
        logger.info(f"Asset selezionati: {selected}")
        return selected

    def _calculate_asset_score(self, symbol: str) -> float:
        """
        Calcola uno score di opportunità per un asset.

        Score = (volume_ratio * 0.3) + (volatility_normalized * 0.3) + (momentum * 0.4)

        Returns:
            Score float (maggiore = migliore opportunità)
        """
        df = self.broker.get_recent_bars(symbol, '1h', 48)
        if df is None or df.empty:
            return 0.0

        # Volume ratio (ultimo vs media)
        vol_ma = df['volume'].rolling(24).mean()
        if vol_ma.iloc[-1] > 0:
            vol_ratio = float(df['volume'].iloc[-1] / vol_ma.iloc[-1])
        else:
            vol_ratio = 1.0

        # Volatilità (ATR normalizzato)
        if len(df) >= 14:
            tr = (df['high'] - df['low']).rolling(14).mean()
            atr_normalized = float(tr.iloc[-1] / df['close'].iloc[-1]) if df['close'].iloc[-1] > 0 else 0
        else:
            atr_normalized = 0

        # Momentum 24 ore
        if len(df) >= 24:
            momentum = float(
                (df['close'].iloc[-1] - df['close'].iloc[-24]) / df['close'].iloc[-24]
            ) if df['close'].iloc[-24] > 0 else 0
        else:
            momentum = 0

        score = (vol_ratio * 0.3) + (atr_normalized * 0.3) + (abs(momentum) * 0.4)
        return score

    # ----------------------------------------------------------------
    # ANALISI E TRADING
    # ----------------------------------------------------------------

    def _can_trade_asset(self, symbol: str) -> bool:
        """
        Verifica se possiamo operare su un asset specifico in base agli orari.
        - Crypto (/): H24 sempre
        - Stock (no /): Solo 15:30-22:00 IT (09:30-16:00 USA)

        Returns:
            True se possiamo operare, False altrimenti
        """
        is_crypto = '/' in symbol
        if is_crypto:
            return True  # Crypto H24

        # Stock: verifica orari
        now = datetime.now(ZoneInfo("Europe/Rome"))
        current_time = now.time()
        start = datetime.strptime("15:30", '%H:%M').time()
        end = datetime.strptime("22:00", '%H:%M').time()
        return start <= current_time <= end

    def _analyze_and_trade(
        self,
        symbol: str,
        capital: float,
        macro_multiplier: float,
        open_trades: List[Dict]
    ):
        """
        Analizza un asset con tutte le strategie e decide se tradare.

        Args:
            symbol: Simbolo da analizzare
            capital: Capitale attuale
            macro_multiplier: Moltiplicatore size per contesto macro
            open_trades: Lista posizioni già aperte
        """
        # Verifica orari operativi (differenziato crypto vs stock)
        if not self._can_trade_asset(symbol):
            return

        # Verifica se possiamo aprire una nuova posizione
        pos_check = self.risk_manager.can_open_position(symbol, open_trades)
        if not pos_check['can_open']:
            logger.debug(f"[{symbol}] {pos_check['reason']}")
            return

        # ---- CORRELAZIONE GUARD (NUOVO) ----
        # Blocca posizioni su asset correlati
        can_open_corr, reason_corr = self.correlation_guard.can_open_position(
            symbol, 'BUY', open_trades
        )
        if not can_open_corr:
            logger.info(f"[{symbol}] CorrelationGuard BLOCKED: {reason_corr}")
            return

        # ===== RECUPERO DATI MULTI-TIMEFRAME (FIX BUG 1) =====
        # Recupera 3 timeframe SEPARATI per trigger entry su 1m
        df_1h  = self.broker.get_recent_bars(symbol, '1h', 100)    # Bias/trend macro
        df_15m = self.broker.get_recent_bars(symbol, '15m', 100)   # Setup
        df_1m  = self.broker.get_recent_bars(symbol, '1m', 300)    # Trigger entry

        if df_1m is None or df_1m.empty:
            logger.warning(f"[{symbol}] Nessun dato 1m disponibile")
            return

        # ===== REGIME DETECTION PER-ASSET (FIX BUG 2) =====
        # Calcola regime individuale per ogni asset (non global BTC)
        try:
            regime_info = self.regime_detector.detect_regime(df_1m)
            asset_regime = regime_info
            logger.debug(
                f"[{symbol}] Regime: {regime_info['regime']} | "
                f"ADX={regime_info.get('adx', 0):.1f} | "
                f"CI={regime_info.get('choppiness', 0):.1f}"
            )
        except Exception as e:
            logger.debug(f"[{symbol}] Errore regime detection: {e}")
            asset_regime = {'regime': 'UNDEFINED', 'strategy_mask': [True]*6}

        # ---- FILTRO TREND 1H: blocca BUY se asset in downtrend 1h ----
        trend_1h = 'NEUTRAL'
        if df_1h is not None and len(df_1h) >= 50:
            try:
                close_1h = df_1h['close']
                ema20_1h = float(close_1h.ewm(span=20).mean().iloc[-1])
                ema50_1h = float(close_1h.ewm(span=50).mean().iloc[-1])
                current_close_1h = float(close_1h.iloc[-1])

                if current_close_1h > ema20_1h and ema20_1h > ema50_1h:
                    trend_1h = 'BULLISH'
                elif current_close_1h < ema20_1h and ema20_1h < ema50_1h:
                    trend_1h = 'BEARISH'
                else:
                    trend_1h = 'NEUTRAL'

                logger.debug(f"[{symbol}] Trend 1h: {trend_1h} (C={current_close_1h:.2f}, EMA20={ema20_1h:.2f}, EMA50={ema50_1h:.2f})")
            except Exception as e:
                logger.debug(f"[{symbol}] Errore calcolo trend 1h: {e}")
                trend_1h = 'NEUTRAL'

        # Cache per uso in monitoring
        if not hasattr(self, '_trend_1h_cache'):
            self._trend_1h_cache = {}
        self._trend_1h_cache[symbol] = trend_1h

        # Calcola indicatori tecnici su df_1m (non 5m)
        df_with_indicators = self.strategy_confluence.calculate_indicators(df_1m)
        if df_with_indicators is None:
            return

        # --- Analisi Strategia 1: Confluence (EMA Crossover) ---
        # Usa df_1m per segnali veloci
        signal_1 = self.strategy_confluence.analyze(df_with_indicators, symbol)

        # --- Analisi Strategia 2: Breakout (Bollinger Squeeze) ---
        # Usa df_15m per setup + df_1h per contesto macro
        signal_2 = self.strategy_breakout.analyze(df_15m, df_1h, symbol)

        # --- Analisi Strategia 3: Sentiment (VWAP Momentum) ---
        # Usa df_1m con VWAP session-based
        signal_3 = self.strategy_sentiment.analyze(df_1m, symbol)

        # --- Analisi Strategia 4: RSI Divergence (NEW) ---
        # Rileva divergenze RSI su df_1m con bias 1h
        signal_4 = self.strategy_rsi_divergence.analyze(df_1m, symbol, df_1h=df_1h)

        # --- Analisi Strategia 5: S/R Bounce (NEW) ---
        # Identifica S/R su df_1h e attende bounce su df_1m
        signal_5 = self.strategy_sr_bounce.analyze(df_1m, df_1h, symbol)

        # --- Analisi Strategia 6: MTF Confluence (NEW) ---
        # Genera segnale quando 1h, 15m, 1m sono allineati
        signal_6 = self.strategy_mtf_confluence.analyze(df_1m, df_15m, df_1h, symbol)

        # ===== VOTING SYSTEM (6 STRATEGIE CON PESI) =====
        current_price = float(df_1m.iloc[-1]['close']) if df_1m is not None and len(df_1m) > 0 else 0

        # Usa strategy_mask dal regime detector per-asset
        strategy_mask = asset_regime.get('strategy_mask', [True]*6)

        vote_result = self.meta_strategy.vote(
            signal_1, signal_2, signal_3, signal_4, signal_5, signal_6,
            symbol,
            df_1m=df_1m, df_15m=df_15m, df_1h=df_1h,
            strategy_mask=strategy_mask,
            regime_info=asset_regime
        )
        final_signal = vote_result['final_signal']
        vote_score = vote_result['weighted_score']  # Ora è score pesato, non conteggio voti

        # Log dei singoli voti delle 6 strategie con pesi
        votes = vote_result.get('votes', {})
        logger.info(
            f"[{symbol}] Voti strategie (pesati): "
            f"EMA={votes.get('confluence', 'HOLD')} | "
            f"BB={votes.get('breakout', 'HOLD')} | "
            f"VWAP={votes.get('sentiment', 'HOLD')} | "
            f"RSI-Div={votes.get('rsi_divergence', 'HOLD')} | "
            f"S/R={votes.get('sr_bounce', 'HOLD')} | "
            f"MTF={votes.get('mtf_confluence', 'HOLD')} → "
            f"FINALE: {final_signal} (score={vote_score:.2f})"
        )

        # Salva i segnali nel database (6 strategie)
        for signal, name in [
            (signal_1, 'confluence'),
            (signal_2, 'breakout'),
            (signal_3, 'sentiment'),
            (signal_4, 'rsi_divergence'),
            (signal_5, 'sr_bounce'),
            (signal_6, 'mtf_confluence')
        ]:
            self.db.insert_signal({
                'symbol': symbol,
                'strategy': name,
                'signal': signal.get('signal', 'HOLD'),
                'score': signal.get('score', signal.get('sentiment_score', 0)),
                'details': signal
            })

        # Se non c'è segnale operativo, esci
        # NOTA: Fidati del segnale finale del meta_strategy — ha già valutato min_score e regime
        # Non ri-valutare abs(vote_score) < 2 qui (appartiene al meta_strategy)
        if final_signal == 'HOLD':
            logger.debug(f"[{symbol}] HOLD - {vote_result['reason']}")
            return

        # --- Filtro ML (DISABILITATO per scalping) ---
        # ML filter è troppo lento per scalping 1min, manteniamo approvazione automatica
        if self.ml_filter.config.get('ml_filter', {}).get('enabled', False):
            sentiment_score = signal_3.get('sentiment_score', 0) or 0
            vix_level = self.market_context.get_vix_level()
            ml_result = self.ml_filter.predict(df_with_indicators, sentiment_score, vix_level)

            if not ml_result['approved']:
                logger.info(f"[{symbol}] Segnale RIGETTATO dal ML: {ml_result['reason']}")
                return
        else:
            # ML disabled: approva automaticamente il segnale
            ml_result = {'approved': True, 'confidence': 1.0, 'reason': 'ML disabled for scalping'}

        # --- Calcolo Position Sizing (con Kelly sizing e Session scoring) ---
        current_price = self.broker.get_latest_price(symbol)
        if not current_price:
            logger.warning(f"[{symbol}] Impossibile ottenere prezzo corrente")
            return

        atr = float(df_with_indicators['atr'].iloc[-1]) if 'atr' in df_with_indicators.columns else None
        position_size = self.risk_manager.calculate_position_size(
            capital=capital,
            price=current_price,
            atr=atr,
            vote_score=abs(vote_score),
            macro_multiplier=macro_multiplier
        )

        # ---- KELLY SIZING (NUOVO) ----
        # Calcola sizing basato su Kelly Criterion
        kelly_info = self.kelly_sizing.calculate_kelly_fraction()
        kelly_multiplier = kelly_info.get('position_size_pct', 0.15) / 0.15  # Normalizza rispetto a default 15%

        # ---- SESSION SCORING (NUOVO) ----
        # Applica moltiplicatore basato su qualità sessione
        session_multiplier = self._session_size_multiplier

        # Combina tutti i moltiplicatori
        final_multiplier = macro_multiplier * kelly_multiplier * session_multiplier
        position_size['qty'] = position_size['qty'] * final_multiplier
        position_size['capital_at_risk'] = position_size['capital_at_risk'] * final_multiplier

        # Arrotonda quantità per compatibilità Alpaca (max 8 decimali per crypto, 2 per stock)
        # Per evitare doppi ordini, arrotondiamo a 6 decimali
        is_crypto = '/' in symbol
        if is_crypto:
            position_size['qty'] = round(position_size['qty'], 6)
        else:
            position_size['qty'] = round(position_size['qty'], 2)

        # Log dei moltiplicatori applicati
        logger.debug(
            f"[{symbol}] Sizing Multipliers: macro={macro_multiplier:.2f}x × "
            f"kelly={kelly_multiplier:.2f}x × session={session_multiplier:.2f}x = "
            f"final={final_multiplier:.2f}x | Qty={position_size['qty']:.2f}"
        )

        if position_size['qty'] <= 0:
            logger.warning(f"[{symbol}] Quantità calcolata = 0, operazione saltata")
            return

        # --- Esecuzione Ordine ---
        if final_signal == 'BUY':
            # Filtro trend 1h: non comprare se trend 1h è BEARISH
            trend = self._trend_1h_cache.get(symbol, 'NEUTRAL') if hasattr(self, '_trend_1h_cache') else 'NEUTRAL'
            if trend == 'BEARISH':
                logger.info(f"[{symbol}] BUY bloccato: trend 1h BEARISH (EMA20 < EMA50)")
                return

            self._execute_buy(
                symbol=symbol,
                qty=position_size['qty'],
                price=current_price,
                stop_loss=position_size['stop_loss'],
                take_profit=position_size['take_profit'],
                vote_result=vote_result,
                ml_result=ml_result
            )

        elif final_signal == 'SELL':
            # Controlla se c'è una posizione aperta da chiudere
            existing_trade = self.db.get_trade_by_symbol(symbol)
            if existing_trade:
                self._close_position(
                    symbol=symbol,
                    trade=existing_trade,
                    reason=f"Segnale SELL ({vote_result['reason']})"
                )

    def _execute_buy(
        self,
        symbol: str,
        qty: float,
        price: float,
        stop_loss: float,
        take_profit: float,
        vote_result: Dict,
        ml_result: Dict
    ):
        """
        Esegue un ordine di acquisto con ATR-based stops dinamici.

        Args:
            symbol: Simbolo da comprare
            qty: Quantità
            price: Prezzo corrente
            stop_loss: Prezzo stop loss (default, può essere sovrascritto da ATR)
            take_profit: Prezzo take profit (default, può essere sovrascritto da ATR)
            vote_result: Risultato del sistema di voto
            ml_result: Risultato del filtro ML
        """
        # ---- QUANTITÀ ROUNDING (previene doppi ordini da arrotondamento Alpaca) ----
        # Arrotonda la quantità per evitare che Alpaca esegua parzialmente l'ordine
        # e il bot invii il resto come secondo ordine
        is_crypto = '/' in symbol
        if is_crypto:
            qty = round(qty, 6)  # Crypto: max 6 decimali per Alpaca
        else:
            qty = round(qty, 2)  # Stock: max 2 decimali (shares intere o quarti)

        if qty <= 0:
            logger.warning(f"[{symbol}] Quantità dopo rounding = 0, ordine saltato")
            return

        # ---- ATR-BASED STOPS (NUOVO) ----
        # Calcola SL/TP dinamici basati su volatilità
        try:
            df_1min = self.broker.get_recent_bars(symbol, '1m', 50)
            atr_result = self.risk_manager.calculate_atr_based_stops(df_1min, price)

            if atr_result.get('atr_used', False):
                # Usa stops ATR-based
                stop_loss = price * (1 - atr_result['sl_pct'])
                take_profit = price * (1 + atr_result['tp_pct'])
                logger.debug(f"[{symbol}] ATR-based stops: SL={atr_result['sl_pct']*100:.2f}%, TP={atr_result['tp_pct']*100:.2f}% (ATR={atr_result['atr_value']:.4f})")
        except Exception as e:
            logger.warning(f"[{symbol}] Errore ATR calc, uso fixed: {e}")

        logger.info(
            f"[{symbol}] ACQUISTO: qty={qty:.4f}, price=${price:.2f}, "
            f"SL=${stop_loss:.2f}, TP=${take_profit:.2f} | "
            f"Voti={vote_result['buy_votes']}/3 | ML={ml_result['confidence']:.1%}"
        )

        # Invia ordine ad Alpaca
        order = self.broker.place_market_order(
            symbol=symbol,
            qty=qty,
            side='buy',
            stop_loss=stop_loss,
            take_profit=take_profit
        )

        if order:
            # Determina la strategia principale
            strategy_name = f"meta_{vote_result['buy_votes']}v_{vote_result.get('strategy_name', 'multi')}"

            # Registra nel database
            entry_reason = f"MetaStrategy: {vote_result.get('reason', 'Consensus reached')}"
            trade_id = self.db.insert_trade({
                'symbol': symbol,
                'side': 'buy',
                'quantity': qty,
                'entry_price': order.get('filled_price') or price,
                'strategy': strategy_name,
                'entry_reason': entry_reason,
                'stop_loss': stop_loss,
                'take_profit': take_profit,
                'alpaca_order_id': order.get('order_id'),
                'ml_confidence': ml_result.get('confidence'),
                'vote_score': vote_result.get('buy_votes', 0),
                'regime_at_entry': self._current_regime.get('regime', 'UNDEFINED'),
                'confidence': vote_result.get('avg_confidence', 0)
            })

            # Notifica Telegram
            if self.notifier:
                self.notifier.notify_trade_open({
                'symbol': symbol,
                'side': 'buy',
                'entry_price': order.get('filled_price') or price,
                'quantity': qty,
                'strategy': strategy_name,
                'stop_loss': stop_loss,
                'take_profit': take_profit,
                'vote_score': vote_result.get('buy_votes', 0)
            })

            # Incrementa contatore trade giornaliero (SCALPING)
            self.risk_manager.increment_trade_count()

            logger.info(f"[{symbol}] Ordine eseguito: trade ID={trade_id}")

        else:
            logger.error(f"[{symbol}] Ordine FALLITO")

    # ----------------------------------------------------------------
    # MONITORING POSIZIONI
    # ----------------------------------------------------------------

    def _monitor_open_positions(self, current_capital: float):
        """
        Monitora le posizioni aperte per stop loss, trailing stop e take profit.

        Args:
            current_capital: Capitale attuale
        """
        open_trades = self.db.get_open_trades()
        if not open_trades:
            return

        for trade in open_trades:
            symbol = trade['symbol']

            try:
                # Recupera prezzo corrente
                current_price = self.broker.get_latest_price(symbol)
                if not current_price:
                    continue

                # SCALPING: Verifica timeout posizione (15 minuti max)
                if self.risk_manager.should_close_by_timeout(trade):
                    logger.warning(f"[{symbol}] TIMEOUT posizione (> 15 min)")
                    self._close_position(symbol, trade, "Timeout scalping (15min)")
                    if self.notifier:
                        self.notifier.notify_timeout_close(trade, current_price)
                    continue

                # Verifica stop loss
                if self.risk_manager.should_stop_loss(trade, current_price):
                    pnl = (current_price - trade['entry_price']) * trade['quantity']
                    logger.warning(f"[{symbol}] STOP LOSS scattato a ${current_price:.2f}")
                    self._close_position(symbol, trade, "Stop loss")
                    if self.notifier:
                        self.notifier.notify_stop_loss(symbol, current_price, pnl)
                    # SCALPING: Avvia cooldown di 2 minuti dopo lo stop loss
                    self.risk_manager.set_stop_loss_cooldown()
                    continue

                # Verifica take profit
                if self.risk_manager.should_take_profit(trade, current_price):
                    logger.info(f"[{symbol}] TAKE PROFIT raggiunto a ${current_price:.2f}")
                    self._close_position(symbol, trade, "Take profit")
                    continue

                # Check break-even automatico
                be_stop = self.risk_manager.check_break_even(trade, current_price)
                if be_stop and be_stop > trade.get('stop_loss', 0):
                    self.db.update_trade_stop(trade['id'], be_stop)
                    logger.info(f"[{symbol}] Break-even attivato: SL → ${be_stop:.4f}")

                # ---- USCITA ANTICIPATA SE SEGNALE SI INVERTE ----
                # Calcola rapidamente se il MTF Confluence si è invertito
                try:
                    df_1m_quick = self.broker.get_recent_bars(symbol, '1m', 50)
                    df_15m_quick = self.broker.get_recent_bars(symbol, '15m', 30)
                    df_1h_quick = self.broker.get_recent_bars(symbol, '1h', 50)

                    if df_1m_quick is not None and df_15m_quick is not None and df_1h_quick is not None:
                        mtf_check = self.strategy_mtf_confluence.analyze(
                            df_1m_quick, df_15m_quick, df_1h_quick, symbol
                        )
                        trade_side = trade.get('side', 'buy')
                        pnl_current = (current_price - trade['entry_price']) * trade['quantity']

                        # Uscita anticipata se MTF si inverte E siamo in perdita
                        if (trade_side == 'buy' and
                            mtf_check.get('signal') == 'SELL' and
                            mtf_check.get('score', 0) >= 2 and
                            pnl_current < 0):
                            logger.info(f"[{symbol}] Uscita anticipata: MTF invertito in SELL, PnL={pnl_current:.2f}")
                            self._close_position(symbol, trade, "MTF signal reversal (early exit)")
                            continue
                except Exception as e:
                    logger.debug(f"[{symbol}] Errore early exit check: {e}")

                # Aggiorna trailing stop
                new_stop = self.risk_manager.update_trailing_stop(trade, current_price)
                if new_stop:
                    self.db.update_trade_stop(trade['id'], new_stop)
                    logger.debug(f"[{symbol}] Trailing stop aggiornato: ${new_stop:.2f}")

                # SCALPING: Verifica chiusura parziale TP1 (50% a TP1, 50% con trailing stop)
                partial = self.risk_manager.should_take_partial_profit(trade, current_price)
                if partial['close_partial']:
                    partial_qty = trade['quantity'] * 0.5
                    try:
                        # Chiude 50% della posizione
                        success = self.broker.place_market_order(symbol, partial_qty, 'sell' if trade['side'] == 'buy' else 'buy')
                        if success:
                            # Aggiorna database con chiusura parziale
                            self.db.update_trade_partial_close(trade['id'], partial_qty, current_price)

                            # Calcola PnL parziale
                            pnl_partial = (current_price - trade['entry_price']) * partial_qty if trade['side'] == 'buy' else (trade['entry_price'] - current_price) * partial_qty

                            # Aggiorna capitale virtuale
                            self._virtual_capital += pnl_partial
                            self._save_virtual_capital()

                            logger.info(
                                f"[{symbol}] TP PARZIALE: chiusi {partial_qty:.6f} @ ${current_price:.2f} | "
                                f"PnL parziale: ${pnl_partial:+.2f} | "
                                f"Capitale: ${self._virtual_capital:.2f}"
                            )

                            # Notifica Telegram
                            if self.notifier:
                                self.notifier.notify_trade_close({
                                    **trade,
                                    'exit_price': current_price,
                                    'quantity': partial_qty,
                                    'pnl': pnl_partial
                                }, "Take Profit Parziale (50%)")
                    except Exception as e:
                        logger.error(f"[{symbol}] Errore nella chiusura parziale TP1: {e}")

            except Exception as e:
                logger.error(f"Errore monitoraggio {symbol}: {e}")

    def _close_position(self, symbol: str, trade: Dict, reason: str):
        """
        Chiude una posizione aperta.

        Args:
            symbol: Simbolo da chiudere
            trade: Dati del trade dal database
            reason: Motivo della chiusura
        """
        # Chiudi su Alpaca
        success = self.broker.close_position(symbol)

        if success:
            # Recupera prezzo di chiusura
            exit_price = self.broker.get_latest_price(symbol) or trade['entry_price']

            # Aggiorna database
            self.db.close_trade(trade['id'], exit_price, reason)

            # Calcola PnL per notifica
            pnl = (exit_price - trade['entry_price']) * trade['quantity']
            pnl_pct = (exit_price - trade['entry_price']) / trade['entry_price']

            trade_data = {
                **trade,
                'exit_price': exit_price,
                'pnl': pnl,
                'pnl_pct': pnl_pct
            }

            # Aggiorna capitale virtuale con il P&L del trade
            self._virtual_capital += pnl
            self._save_virtual_capital()

            # Notifica Telegram
            if self.notifier:
                self.notifier.notify_trade_close(trade_data, reason)

            logger.info(
                f"[{symbol}] Posizione chiusa: PnL={pnl:+.2f}$ ({pnl_pct:+.2%}) | {reason} | "
                f"Capitale virtuale: ${self._virtual_capital:.2f}"
            )

    def _close_all_positions(self, reason: str):
        """Chiude tutte le posizioni aperte."""
        open_trades = self.db.get_open_trades()
        for trade in open_trades:
            self._close_position(trade['symbol'], trade, reason)

    # ----------------------------------------------------------------
    # ORARI OPERATIVI
    # ----------------------------------------------------------------

    def _is_trading_window_active(self) -> bool:
        """
        Verifica se l'orario attuale rientra nelle finestre operative.

        Returns:
            True se siamo in una finestra operativa valida
        """
        now = datetime.now(IT_TZ)
        current_time = now.time()

        trading_hours = self.config.get('trading_hours', {})
        windows = trading_hours.get('windows', [])
        avoid = trading_hours.get('avoid', [])

        # Controlla se siamo in una finestra da evitare
        for avoidance in avoid:
            start = datetime.strptime(avoidance['start'], '%H:%M').time()
            end = datetime.strptime(avoidance['end'], '%H:%M').time()
            if start <= current_time <= end:
                return False

        # Controlla se siamo in una finestra operativa
        for window in windows:
            start = datetime.strptime(window['start'], '%H:%M').time()
            end = datetime.strptime(window['end'], '%H:%M').time()
            if start <= current_time <= end:
                return True

        return False

    # ----------------------------------------------------------------
    # GESTIONE CAPITALE VIRTUALE
    # ----------------------------------------------------------------

    def _save_virtual_capital(self):
        """
        Salva il capitale virtuale su file JSON.
        Permette di riprendere dalla stessa cifra al riavvio del bot.
        """
        import json
        from pathlib import Path
        Path('data').mkdir(exist_ok=True)
        data = {
            'virtual_capital': self._virtual_capital,
            'initial_capital': self._initial_virtual_capital,
            'capital_eur': self.config.get('trading', {}).get('capital_eur', 500),
            'total_pnl': self._virtual_capital - self._initial_virtual_capital,
            'total_pnl_pct': (self._virtual_capital - self._initial_virtual_capital) / self._initial_virtual_capital,
            'updated_at': datetime.now().isoformat(),
        }
        with open('data/virtual_capital.json', 'w') as f:
            json.dump(data, f, indent=2)

    def _load_virtual_capital(self) -> float:
        """
        Carica il capitale virtuale dal file JSON.
        Al primo avvio usa il valore da config.yaml.

        Returns:
            Capitale virtuale corrente in USD
        """
        import json
        from pathlib import Path
        path = Path('data/virtual_capital.json')
        if path.exists():
            try:
                with open(path) as f:
                    data = json.load(f)
                capital = data.get('virtual_capital', self._initial_virtual_capital)
                logger.info(f"Capitale virtuale caricato: ${capital:.2f} (dal file precedente)")
                return capital
            except Exception as e:
                logger.warning(f"Impossibile caricare capitale virtuale: {e}. Uso valore config.")

        # Prima volta: salva e restituisce il valore iniziale
        logger.info(f"Prima esecuzione — capitale virtuale inizializzato: ${self._initial_virtual_capital:.2f}")
        self._save_virtual_capital()
        return self._initial_virtual_capital

    def _sync_positions_with_alpaca(self):
        """Allinea posizioni DB con quelle reali su Alpaca (posizioni + ordini pending)."""
        try:
            db_open = self.db.get_open_trades()
            alpaca_positions = {p['symbol'].replace('/', '') for p in self.broker.get_positions()}

            # Recupera anche gli ordini pending da Alpaca
            alpaca_orders = self.broker.get_orders(status='open')  # open = pending + partialmente eseguiti
            alpaca_pending_symbols = set()
            if alpaca_orders:
                for order in alpaca_orders:
                    # Order symbol è senza '/', symbol del trade è con '/'
                    symbol_with_slash = order.get('symbol', '').replace('USD', '/USD') if '/' not in order.get('symbol', '') else order.get('symbol', '')
                    alpaca_pending_symbols.add(order.get('symbol', ''))

            for trade in db_open:
                symbol_alpaca = trade['symbol'].replace('/', '')
                order_id = trade.get('alpaca_order_id')

                # Controlla se la posizione è eseguita su Alpaca
                position_exists = symbol_alpaca in alpaca_positions

                # Controlla se c'è un ordine pending per questo trade
                order_exists = symbol_alpaca in alpaca_pending_symbols or (order_id and any(o.get('order_id') == order_id for o in alpaca_orders or []))

                # Se né posizione né ordine, chiudi il trade come ghost position
                if not position_exists and not order_exists:
                    exit_price = self.broker.get_latest_price(trade['symbol']) or trade['entry_price']
                    self.db.close_trade(trade['id'], exit_price, 'Startup sync: position and order not found on Alpaca')
                    logger.warning(
                        f"[STARTUP SYNC] Closed ghost position: {trade['symbol']} "
                        f"(no position, no pending order)"
                    )
                elif order_exists and not position_exists:
                    # Ordine pendente da molto tempo → cancella e chiudi trade
                    entry_time = datetime.fromisoformat(trade.get('entry_time', datetime.now().isoformat()))
                    age_seconds = (datetime.now() - entry_time).total_seconds()

                    if age_seconds > 3600:  # > 1 ora di ordine pending
                        logger.warning(
                            f"[STARTUP SYNC] {trade['symbol']} ordine pending da {age_seconds//60:.0f} min, cancellazione..."
                        )
                        # Cancella l'ordine su Alpaca
                        try:
                            if order_id:
                                self.broker.cancel_order(order_id)
                        except Exception as e:
                            logger.error(f"Errore cancellazione ordine {order_id}: {e}")

                        # Chiudi il trade nel DB
                        exit_price = self.broker.get_latest_price(trade['symbol']) or trade['entry_price']
                        self.db.close_trade(trade['id'], exit_price, 'Startup sync: pending order cancelled (>1h)')
                        logger.warning(f"[STARTUP SYNC] Trade chiuso: {trade['symbol']} (ordine cancellato)")
        except Exception as e:
            logger.error(f"Errore sync posizioni Alpaca: {e}")

    # ----------------------------------------------------------------
    # TASK SCHEDULATI
    # ----------------------------------------------------------------

    def _daily_reset(self):
        """Resetta lo stato giornaliero a mezzanotte."""
        logger.info("Reset giornaliero in corso...")

        # Il capitale giornaliero di riferimento è il virtuale, non quello Alpaca
        self._daily_starting_capital = self._virtual_capital

        self.risk_manager.reset_daily_state()

        # Aggiorna tracker paper trading
        if self.config['trading']['mode'] == 'paper':
            yesterday_stats = self.db.get_today_stats()
            if yesterday_stats.get('total_pnl', 0) > 0:
                self._profitable_days += 1

                # Notifica se raggiunto target paper trading
                days_target = self.config.get('paper_trading', {}).get('days_for_live_suggestion', 30)
                if (self._profitable_days >= days_target and
                        self.config.get('paper_trading', {}).get('notify_live_ready', True)):
                    if self.notifier:
                        self.notifier.notify_live_trading_ready(self._profitable_days)

        logger.info(f"Nuovo starting capital giornaliero: ${self._daily_starting_capital:.2f}")

    def _send_daily_report(self):
        """Invia il report giornaliero via Telegram."""
        stats = self.db.get_today_stats()

        current_capital = self._virtual_capital
        daily_pnl = current_capital - (self._daily_starting_capital or current_capital)
        daily_pnl_pct = daily_pnl / self._daily_starting_capital if self._daily_starting_capital else 0

        report_data = {
            'total_pnl': daily_pnl,
            'pnl_pct': daily_pnl_pct,
            'ending_capital': current_capital,
            'trades_count': stats.get('total_trades', 0),
            'winning_trades': stats.get('winning', 0),
            'losing_trades': stats.get('losing', 0),
            'best_trade': stats.get('best_trade'),
            'worst_trade': stats.get('worst_trade'),
        }

        self.db.update_daily_stats({
            **report_data,
            'starting_capital': self._daily_starting_capital,
            'mode': self.config['trading']['mode']
        })

        if self.notifier:
            self.notifier.send_daily_report(report_data)

    def _send_weekly_report(self):
        """Invia il report settimanale via Telegram."""
        metrics = self.db.get_performance_metrics()

        weekly_pnl = self._virtual_capital - (self._weekly_starting_capital or self._virtual_capital)
        weekly_pnl_pct = weekly_pnl / self._weekly_starting_capital if self._weekly_starting_capital else 0

        # Aggiorna capitale settimanale di riferimento
        self._weekly_starting_capital = self._virtual_capital

        # Verifica limiti settimanali
        weekly_check = self.risk_manager.check_weekly_limits(weekly_pnl_pct)

        strategy_perf = self.db.get_strategy_performance()
        best_strategy = strategy_perf[0]['strategy'] if strategy_perf else 'N/A'

        report_data = {
            **metrics,
            'total_pnl': weekly_pnl,
            'pnl_pct': weekly_pnl_pct,
            'ending_capital': self._virtual_capital,
            'best_strategy': best_strategy,
            'paused_next_week': weekly_check.get('should_pause', False)
        }

        if self.notifier:
            self.notifier.send_weekly_report(report_data)

        if weekly_check.get('should_pause'):
            self.status_updater.update_status(
                'paused',
                f"Perdite settimanali eccessive: {weekly_pnl_pct:.2%}"
            )

    def _retrain_ml_if_needed(self):
        """Riaddestra il modello ML se necessario."""
        if self.ml_filter.should_retrain():
            logger.info("Inizio retraining ML domenicale...")
            all_symbols = []
            assets_config = self.config.get('assets', {})

            for category in ['etf', 'stocks', 'crypto']:
                if assets_config.get(category, {}).get('enabled', True):
                    all_symbols.extend(assets_config[category].get('symbols', []))

            metrics = self.ml_filter.train(self.broker, all_symbols)
            if metrics.get('success'):
                logger.info(f"ML retraining completato: accuracy={metrics.get('accuracy', 0):.2%}")
            else:
                logger.warning(f"ML retraining fallito: {metrics.get('reason')}")
