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
from bot.strategy_liquidity import LiquidityHuntStrategy
from bot.news_analyzer import NewsAnalyzer
from bot.meta_strategy import MetaStrategy
from bot.ml_filter import MLFilter
from bot.notifications import TelegramNotifier
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

        # Strategie
        self.strategy_confluence = ConfluenceStrategy(self.config)
        self.strategy_breakout = BreakoutStrategy(self.config)
        self.strategy_sentiment = SentimentStrategy(self.news_analyzer, self.config)
        self.strategy_liquidity = LiquidityHuntStrategy(self.config)

        # Meta-Strategy (sistema di voto)
        self.meta_strategy = MetaStrategy(self.config)

        # ML Filter
        self.ml_filter = MLFilter(self.config, self.db)

        # Notifiche Telegram
        self.notifier = TelegramNotifier(self.config)

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

        # Notifica avvio
        self.notifier.notify_bot_status('started')

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

        self.notifier.notify_bot_status('stopped')
        logger.info("Bot fermato")

    def pause(self):
        """Mette il bot in pausa (senza chiudere posizioni)."""
        self.paused = True
        logger.info("Bot messo in pausa")
        self.notifier.notify_bot_status('paused', 'Pausa manuale')

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
        1. Verifica orari operativi
        2. Verifica condizioni macro
        3. Monitora posizioni aperte
        4. Seleziona migliori asset
        5. Analizza e trada
        """
        now = datetime.now(IT_TZ)

        # --- FASE 1: Verifica chiusura forzata ---
        force_close_time = self.config['trading'].get('force_close_time', '21:45')
        if self.risk_manager.should_force_close(force_close_time):
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
                if 'Perdita' in daily_check.get('reason', ''):
                    logger.warning(f"Stop trading: {daily_check['reason']}")
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
                df_1min = self.broker.get_bars(best_assets_temp[0], '1m', limit=50)
                regime_info = self.regime_detector.detect_regime(df_1min)
                self._current_regime = regime_info
            except:
                self._current_regime = {'regime': 'UNDEFINED', 'strategy_mask': [True, True, True, True]}
        else:
            self._current_regime = {'regime': 'UNDEFINED', 'strategy_mask': [True, True, True, True]}

        # --- FASE 5: Session Scoring (NUOVO) ---
        # Valuta qualità della sessione per adaptive sizing
        session_info = self.session_scorer.calculate_session_score()
        self._session_size_multiplier = session_info.get('size_multiplier', 1.0)

        # --- FASE 6: Contesto macro ---
        if self.market_context.should_stop_trading():
            logger.warning("Condizioni macro avverse - stop nuovi acquisti")
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
        logger.debug(f"Asset selezionati: {selected}")
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
            logger.debug(f"[{symbol}] {reason_corr}")
            return

        # Recupera dati di mercato
        df_5min = self.broker.get_recent_bars(symbol, '5m', 200)
        df_15min = self.broker.get_recent_bars(symbol, '15m', 100)
        df_daily = self.broker.get_recent_bars(symbol, '1d', 30)

        if df_5min is None or df_5min.empty:
            logger.warning(f"[{symbol}] Nessun dato disponibile")
            return

        # Calcola indicatori tecnici (confluence strategy aggiunge gli indicatori)
        df_with_indicators = self.strategy_confluence.calculate_indicators(df_5min)
        if df_with_indicators is None:
            return

        # Aggiungi colonne EMA con nome compatibile per SentimentStrategy
        for ema_col in [f'ema_20', f'ema_50']:
            period = int(ema_col.split('_')[1])
            col_name = f'ema_{period}'
            if col_name not in df_with_indicators.columns:
                df_with_indicators[col_name] = df_5min['close'].ewm(span=period, adjust=False).mean()

        # --- Analisi Strategia 1: Confluence (EMA Crossover) ---
        signal_1 = self.strategy_confluence.analyze(df_with_indicators, symbol)

        # --- Analisi Strategia 2: Breakout (Bollinger Squeeze) ---
        signal_2 = self.strategy_breakout.analyze(df_5min, df_daily, symbol)

        # --- Analisi Strategia 3: Sentiment (VWAP Momentum) ---
        signal_3 = self.strategy_sentiment.analyze(df_with_indicators, symbol)

        # --- Analisi Strategia 4: Liquidity Hunt (Sweep Detection + MFI) ---
        signal_4 = self.strategy_liquidity.analyze(df_with_indicators, df_5min, symbol)

        # --- Sistema di Voto Meta-Strategy (con regime detection + strategy mask) ---
        current_price = float(df_5min.iloc[-1]['close']) if df_5min is not None and len(df_5min) > 0 else 0

        # Usa strategy_mask dal regime detector per filtrare strategie
        strategy_mask = self._current_regime.get('strategy_mask', [True, True, True, True])

        vote_result = self.meta_strategy.vote(
            signal_1, signal_2, signal_3, signal_4,
            symbol,
            df_5min=df_5min,
            df_daily=df_daily,
            current_price=current_price,
            strategy_mask=strategy_mask,  # NUOVO: regime-based filtering
            regime_info=self._current_regime  # NUOVO: passa regime per context
        )
        final_signal = vote_result['final_signal']
        vote_score = vote_result['vote_score']

        # Salva i segnali nel database (4 strategie)
        for signal, name in [(signal_1, 'confluence'), (signal_2, 'breakout'), (signal_3, 'sentiment'), (signal_4, 'liquidity')]:
            self.db.insert_signal({
                'symbol': symbol,
                'strategy': name,
                'signal': signal.get('signal', 'HOLD'),
                'score': signal.get('score', signal.get('sentiment_score', 0)),
                'details': signal
            })

        # Se non c'è segnale operativo, esci
        if final_signal == 'HOLD' or abs(vote_score) < 2:
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

        if position_size['qty'] <= 0:
            logger.warning(f"[{symbol}] Quantità calcolata = 0, operazione saltata")
            return

        # --- Esecuzione Ordine ---
        if final_signal == 'BUY':
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
            trade_id = self.db.insert_trade({
                'symbol': symbol,
                'side': 'buy',
                'quantity': qty,
                'entry_price': order.get('filled_price') or price,
                'strategy': strategy_name,
                'stop_loss': stop_loss,
                'take_profit': take_profit,
                'alpaca_order_id': order.get('order_id'),
                'ml_confidence': ml_result.get('confidence'),
                'vote_score': vote_result.get('buy_votes', 0)
            })

            # Notifica Telegram
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
                    self.notifier.notify_timeout_close(trade, current_price)
                    continue

                # Verifica stop loss
                if self.risk_manager.should_stop_loss(trade, current_price):
                    pnl = (current_price - trade['entry_price']) * trade['quantity']
                    logger.warning(f"[{symbol}] STOP LOSS scattato a ${current_price:.2f}")
                    self._close_position(symbol, trade, "Stop loss")
                    self.notifier.notify_stop_loss(symbol, current_price, pnl)
                    # SCALPING: Avvia cooldown di 2 minuti dopo lo stop loss
                    self.risk_manager.set_stop_loss_cooldown()
                    continue

                # Verifica take profit
                if self.risk_manager.should_take_profit(trade, current_price):
                    logger.info(f"[{symbol}] TAKE PROFIT raggiunto a ${current_price:.2f}")
                    self._close_position(symbol, trade, "Take profit")
                    continue

                # Aggiorna trailing stop
                new_stop = self.risk_manager.update_trailing_stop(trade, current_price)
                if new_stop:
                    self.db.update_trade_stop(trade['id'], new_stop)
                    logger.debug(f"[{symbol}] Trailing stop aggiornato: ${new_stop:.2f}")

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

        self.notifier.send_weekly_report(report_data)

        if weekly_check.get('should_pause'):
            self.notifier.notify_bot_status(
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
