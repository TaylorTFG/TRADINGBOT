# ============================================================
# BROKER - INTERFACCIA ALPACA MARKETS API
# Gestione connessione, ordini, posizioni e dati di mercato
# con riconnessione automatica in caso di errori
# ============================================================

import logging
import time
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from zoneinfo import ZoneInfo

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest,
    LimitOrderRequest,
    StopLossRequest,
    TakeProfitRequest,
    GetOrdersRequest
)
from alpaca.trading.enums import OrderSide, TimeInForce, OrderStatus, QueryOrderStatus
from alpaca.data.historical import StockHistoricalDataClient, CryptoHistoricalDataClient
from alpaca.data.requests import (
    StockBarsRequest,
    CryptoBarsRequest,
    StockLatestQuoteRequest,
    CryptoLatestQuoteRequest
)
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

logger = logging.getLogger(__name__)

# Fuso orario italiano
IT_TZ = ZoneInfo("Europe/Rome")
UTC_TZ = ZoneInfo("UTC")


class BrokerClient:
    """
    Client per interagire con Alpaca Markets API.
    Gestisce ordini, posizioni e recupero dati storici/live.
    Implementa riconnessione automatica in caso di errori di rete.
    """

    def __init__(self, config: dict):
        """
        Inizializza il client Alpaca.

        Args:
            config: Configurazione completa dal config.yaml
        """
        self.config = config
        self.mode = config['trading']['mode']  # 'paper' o 'live'
        self.max_retries = 3
        self.retry_delay = 5  # secondi tra i tentativi

        # Seleziona le credenziali in base alla modalità
        creds = config['alpaca'][self.mode]
        self.api_key = creds['api_key']
        self.api_secret = creds['api_secret']
        self.base_url = creds['base_url']

        # Inizializza i client
        self._init_clients()
        logger.info(f"BrokerClient inizializzato in modalità: {self.mode.upper()}")

    def _init_clients(self):
        """Crea i client Alpaca per trading e dati storici."""
        paper = (self.mode == 'paper')

        # Client per trading (ordini, posizioni, account)
        self.trading_client = TradingClient(
            api_key=self.api_key,
            secret_key=self.api_secret,
            paper=paper
        )

        # Client per dati storici azioni
        self.stock_data_client = StockHistoricalDataClient(
            api_key=self.api_key,
            secret_key=self.api_secret
        )

        # Client per dati storici crypto
        self.crypto_data_client = CryptoHistoricalDataClient(
            api_key=self.api_key,
            secret_key=self.api_secret
        )

        logger.debug("Client Alpaca inizializzati")

    def _retry_on_error(self, func, *args, **kwargs):
        """
        Esegue una funzione con retry automatico in caso di errore.

        Args:
            func: Funzione da eseguire
            *args: Argomenti della funzione
            **kwargs: Keyword arguments della funzione

        Returns:
            Risultato della funzione

        Raises:
            Exception: Se tutti i tentativi falliscono
        """
        for attempt in range(self.max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger.warning(f"Tentativo {attempt + 1}/{self.max_retries} fallito: {e}")
                if attempt < self.max_retries - 1:
                    logger.info(f"Riconnessione in {self.retry_delay}s...")
                    time.sleep(self.retry_delay)
                    try:
                        self._init_clients()  # Reinizializza i client
                    except Exception as reconnect_err:
                        logger.error(f"Errore riconnessione: {reconnect_err}")
                else:
                    logger.error(f"Tutti i tentativi falliti per {func.__name__}")
                    raise

    # ----------------------------------------------------------------
    # INFORMAZIONI ACCOUNT
    # ----------------------------------------------------------------

    def get_account(self) -> Dict:
        """
        Recupera le informazioni dell'account Alpaca.

        Returns:
            Dizionario con capitale, potere d'acquisto, ecc.
        """
        try:
            account = self._retry_on_error(self.trading_client.get_account)
            return {
                'equity': float(account.equity),
                'cash': float(account.cash),
                'buying_power': float(account.buying_power),
                'portfolio_value': float(account.portfolio_value),
                'currency': account.currency,
                'account_blocked': account.account_blocked,
                'trading_blocked': account.trading_blocked,
                'pattern_day_trader': account.pattern_day_trader,
            }
        except Exception as e:
            logger.error(f"Errore recupero account: {e}")
            return {}

    def get_buying_power(self) -> float:
        """Restituisce il potere d'acquisto disponibile in USD."""
        account = self.get_account()
        return float(account.get('buying_power', 0))

    def get_portfolio_value(self) -> float:
        """Restituisce il valore totale del portafoglio in USD."""
        account = self.get_account()
        return float(account.get('portfolio_value', 0))

    # ----------------------------------------------------------------
    # POSIZIONI
    # ----------------------------------------------------------------

    def get_positions(self) -> List[Dict]:
        """
        Recupera tutte le posizioni aperte.

        Returns:
            Lista di dizionari con dettagli posizioni
        """
        try:
            positions = self._retry_on_error(self.trading_client.get_all_positions)
            result = []
            for pos in positions:
                result.append({
                    'symbol': pos.symbol,
                    'qty': float(pos.qty),
                    'side': pos.side.value,
                    'avg_entry_price': float(pos.avg_entry_price),
                    'current_price': float(pos.current_price) if pos.current_price else None,
                    'market_value': float(pos.market_value) if pos.market_value else None,
                    'unrealized_pl': float(pos.unrealized_pl) if pos.unrealized_pl else None,
                    'unrealized_plpc': float(pos.unrealized_plpc) if pos.unrealized_plpc else None,
                    'change_today': float(pos.change_today) if pos.change_today else None,
                })
            return result
        except Exception as e:
            logger.error(f"Errore recupero posizioni: {e}")
            return []

    def get_position(self, symbol: str) -> Optional[Dict]:
        """Recupera la posizione per un simbolo specifico."""
        try:
            pos = self._retry_on_error(
                self.trading_client.get_open_position,
                symbol.replace('/', '')  # Rimuove '/' per crypto (BTC/USD → BTCUSD)
            )
            if pos:
                return {
                    'symbol': pos.symbol,
                    'qty': float(pos.qty),
                    'side': pos.side.value,
                    'avg_entry_price': float(pos.avg_entry_price),
                    'current_price': float(pos.current_price) if pos.current_price else None,
                    'unrealized_pl': float(pos.unrealized_pl) if pos.unrealized_pl else None,
                    'unrealized_plpc': float(pos.unrealized_plpc) if pos.unrealized_plpc else None,
                }
        except Exception:
            return None

    # ----------------------------------------------------------------
    # ORDINI
    # ----------------------------------------------------------------

    def place_market_order(
        self,
        symbol: str,
        qty: float,
        side: str,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None
    ) -> Optional[Dict]:
        """
        Piazza un ordine di mercato con stop loss e take profit opzionali.

        Args:
            symbol: Simbolo dell'asset (es. 'AAPL', 'BTC/USD')
            qty: Quantità da acquistare/vendere
            side: 'buy' o 'sell'
            stop_loss: Prezzo stop loss (opzionale)
            take_profit: Prezzo take profit (opzionale)

        Returns:
            Dizionario con i dettagli dell'ordine o None in caso di errore
        """
        try:
            # Normalizza il simbolo (rimuove '/' per crypto)
            alpaca_symbol = symbol.replace('/', '')

            order_side = OrderSide.BUY if side.lower() == 'buy' else OrderSide.SELL

            # Per crypto: usa GTC (Good-Till-Canceled) invece di DAY
            # DAY non è supportato per crypto su Alpaca
            tif = TimeInForce.GTC if '/' in symbol else TimeInForce.DAY

            order_request = MarketOrderRequest(
                symbol=alpaca_symbol,
                qty=qty,
                side=order_side,
                time_in_force=tif,
            )

            order = self._retry_on_error(
                self.trading_client.submit_order,
                order_request
            )

            logger.info(f"Ordine mercato piazzato: {symbol} {side} {qty} | ID: {order.id}")

            # Piazza stop loss separato se fornito
            if stop_loss and order.status == OrderStatus.FILLED:
                self._place_stop_loss_order(alpaca_symbol, qty, side, stop_loss)

            # Piazza take profit separato se fornito
            if take_profit and order.status == OrderStatus.FILLED:
                self._place_take_profit_order(alpaca_symbol, qty, side, take_profit)

            return {
                'order_id': str(order.id),
                'symbol': symbol,
                'side': side,
                'qty': qty,
                'status': order.status.value,
                'filled_price': float(order.filled_avg_price) if order.filled_avg_price else None,
                'created_at': str(order.created_at),
            }

        except Exception as e:
            logger.error(f"Errore ordine mercato {symbol} {side} {qty}: {e}")
            return None

    def place_limit_order(
        self,
        symbol: str,
        qty: float,
        side: str,
        limit_price: float
    ) -> Optional[Dict]:
        """
        Piazza un ordine limit (Maker) per ridurre commissioni.

        Args:
            symbol: Simbolo dell'asset (es. 'BTC/USD')
            qty: Quantità da acquistare/vendere
            side: 'buy' o 'sell'
            limit_price: Prezzo limite

        Returns:
            Dizionario con i dettagli dell'ordine o None in caso di errore
        """
        try:
            # Normalizza il simbolo (rimuove '/' per crypto)
            alpaca_symbol = symbol.replace('/', '')

            order_side = OrderSide.BUY if side.lower() == 'buy' else OrderSide.SELL

            # Per crypto: usa GTC (Good-Till-Canceled) invece di DAY
            # DAY non è supportato per crypto su Alpaca
            tif = TimeInForce.GTC if '/' in symbol else TimeInForce.DAY

            order_request = LimitOrderRequest(
                symbol=alpaca_symbol,
                qty=qty,
                side=order_side,
                time_in_force=tif,
                limit_price=limit_price,
            )

            order = self._retry_on_error(
                self.trading_client.submit_order,
                order_request
            )

            logger.info(f"Ordine limit piazzato: {symbol} {side} {qty} @ {limit_price} | ID: {order.id}")

            return {
                'order_id': str(order.id),
                'symbol': symbol,
                'side': side,
                'qty': qty,
                'limit_price': limit_price,
                'status': order.status.value,
                'created_at': str(order.created_at),
            }

        except Exception as e:
            logger.error(f"Errore ordine limit {symbol} {side} {qty} @ {limit_price}: {e}")
            return None

    def get_order_status(self, order_id: str) -> Optional[str]:
        """
        Recupera lo stato di un ordine specifico.

        Args:
            order_id: ID dell'ordine

        Returns:
            Stato dell'ordine ('FILLED', 'PENDING', 'CANCELED', ecc.) o None se errore
        """
        try:
            order = self._retry_on_error(
                self.trading_client.get_order_by_id,
                order_id
            )
            return order.status.value if order else None
        except Exception as e:
            logger.warning(f"Errore recupero stato ordine {order_id}: {e}")
            return None

    def get_orders(self, status: str = 'open', limit: int = 100) -> Optional[List[Dict]]:
        """
        Recupera gli ordini aperti (pending, partially filled).

        Args:
            status: 'open' filtra localmente, 'closed' filtra localmente
            limit: Numero massimo di ordini (non usato — API non lo supporta)

        Returns:
            Lista di ordini o None in caso di errore
        """
        try:
            # Alpaca API: get_orders() senza parametri ritorna tutti gli ordini
            # Filtriamo localmente per status
            orders = self._retry_on_error(self.trading_client.get_orders)

            if not orders:
                logger.debug(f"Nessun ordine su Alpaca")
                return []

            result = []
            for order in orders:
                order_status = order.status.value if hasattr(order.status, 'value') else str(order.status)

                # Filtra per status (open = NEW, PARTIALLY_FILLED, PENDING_NEW, etc.)
                if status == 'open':
                    # Considera open: new, partially_filled, pending_new, accepted, pending_cancel, pending_replace
                    open_statuses = ['new', 'partially_filled', 'pending_new', 'accepted', 'pending_cancel', 'pending_replace']
                    if order_status.lower() not in open_statuses:
                        continue
                elif status == 'closed':
                    # Considera closed: filled, canceled, expired, rejected
                    closed_statuses = ['filled', 'canceled', 'expired', 'rejected', 'done_for_day']
                    if order_status.lower() not in closed_statuses:
                        continue

                order_dict = {
                    'order_id': str(order.id),
                    'symbol': order.symbol,
                    'side': order.side.value if hasattr(order.side, 'value') else str(order.side),
                    'qty': float(order.qty) if order.qty else 0,
                    'status': order_status,
                    'filled_qty': float(order.filled_qty) if order.filled_qty else 0,
                    'filled_avg_price': float(order.filled_avg_price) if order.filled_avg_price else None,
                    'created_at': str(order.created_at),
                }
                result.append(order_dict)
                logger.debug(
                    f"Ordine open: {order_dict['symbol']} {order_dict['side']} "
                    f"{order_dict['qty']} qty (fill={order_dict['filled_qty']}) → {order_status}"
                )

            logger.info(f"Recuperati {len(result)} ordini {status} da Alpaca")
            return result
        except Exception as e:
            logger.error(f"Errore recupero ordini: {e}", exc_info=True)
            return []

    def cancel_order(self, order_id: str) -> bool:
        """
        Cancella un ordine specifico.

        Args:
            order_id: ID dell'ordine da cancellare

        Returns:
            True se successo, False altrimenti
        """
        try:
            self._retry_on_error(
                self.trading_client.cancel_order,
                order_id
            )
            logger.info(f"Ordine cancellato: {order_id}")
            return True
        except Exception as e:
            logger.warning(f"Errore cancellazione ordine {order_id}: {e}")
            return False

    def _place_stop_loss_order(self, symbol: str, qty: float, original_side: str, stop_price: float):
        """Piazza un ordine stop loss come ordine separato."""
        try:
            # Il lato dello stop loss è opposto all'ordine originale
            stop_side = OrderSide.SELL if original_side.lower() == 'buy' else OrderSide.BUY

            stop_request = MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=stop_side,
                time_in_force=TimeInForce.GTC,
                stop_price=stop_price,
                order_class='simple',
                type='stop'
            )
            self.trading_client.submit_order(stop_request)
            logger.debug(f"Stop loss piazzato per {symbol} a {stop_price}")
        except Exception as e:
            logger.warning(f"Impossibile piazzare stop loss per {symbol}: {e}")

    def _place_take_profit_order(self, symbol: str, qty: float, original_side: str, limit_price: float):
        """Piazza un ordine take profit come ordine separato."""
        try:
            tp_side = OrderSide.SELL if original_side.lower() == 'buy' else OrderSide.BUY

            tp_request = LimitOrderRequest(
                symbol=symbol,
                qty=qty,
                side=tp_side,
                time_in_force=TimeInForce.GTC,
                limit_price=limit_price
            )
            self.trading_client.submit_order(tp_request)
            logger.debug(f"Take profit piazzato per {symbol} a {limit_price}")
        except Exception as e:
            logger.warning(f"Impossibile piazzare take profit per {symbol}: {e}")

    def close_position(self, symbol: str) -> bool:
        """
        Chiude completamente una posizione aperta.

        Args:
            symbol: Simbolo da chiudere

        Returns:
            True se successo o posizione non trovata (già chiusa)
        """
        try:
            alpaca_symbol = symbol.replace('/', '')
            self._retry_on_error(
                self.trading_client.close_position,
                alpaca_symbol
            )
            logger.info(f"Posizione chiusa: {symbol}")
            return True
        except Exception as e:
            error_str = str(e)
            # Se la posizione non esiste, è già chiusa - non è un errore
            if "position not found" in error_str.lower() or "40410000" in error_str:
                logger.info(f"Posizione non trovata su Alpaca (già chiusa): {symbol}")
                return True
            logger.error(f"Errore chiusura posizione {symbol}: {e}")
            return False

    def close_all_positions(self) -> bool:
        """Chiude tutte le posizioni aperte (usato per chiusura forzata fine giornata)."""
        try:
            self._retry_on_error(self.trading_client.close_all_positions, cancel_orders=True)
            logger.info("Tutte le posizioni chiuse")
            return True
        except Exception as e:
            logger.error(f"Errore chiusura tutte le posizioni: {e}")
            return False

    def cancel_all_orders(self) -> bool:
        """Cancella tutti gli ordini in sospeso."""
        try:
            self._retry_on_error(self.trading_client.cancel_orders)
            logger.info("Tutti gli ordini cancellati")
            return True
        except Exception as e:
            logger.error(f"Errore cancellazione ordini: {e}")
            return False

    # ----------------------------------------------------------------
    # DATI STORICI
    # ----------------------------------------------------------------

    def get_bars(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: Optional[datetime] = None,
        limit: int = 1000
    ):
        """
        Recupera i dati OHLCV storici.

        Args:
            symbol: Simbolo dell'asset
            timeframe: '1m', '5m', '15m', '1h', '1d'
            start: Data/ora inizio
            end: Data/ora fine (default: ora corrente)
            limit: Numero massimo di barre

        Returns:
            DataFrame pandas con colonne: open, high, low, close, volume
        """
        try:
            # Mappa timeframe string → TimeFrame Alpaca
            tf_map = {
                '1m': TimeFrame(1, TimeFrameUnit.Minute),
                '5m': TimeFrame(5, TimeFrameUnit.Minute),
                '15m': TimeFrame(15, TimeFrameUnit.Minute),
                '30m': TimeFrame(30, TimeFrameUnit.Minute),
                '1h': TimeFrame(1, TimeFrameUnit.Hour),
                '4h': TimeFrame(4, TimeFrameUnit.Hour),
                '1d': TimeFrame(1, TimeFrameUnit.Day),
            }

            tf = tf_map.get(timeframe, TimeFrame(5, TimeFrameUnit.Minute))

            if end is None:
                end = datetime.now(UTC_TZ)

            # Determina se è crypto o azione
            is_crypto = '/' in symbol or symbol in ['BTCUSD', 'ETHUSD']

            if is_crypto:
                # Assicura che il simbolo crypto abbia il formato BTC/USD (Alpaca lo richiede)
                if '/' not in symbol:
                    alpaca_symbol = symbol[:-3] + '/' + symbol[-3:] if len(symbol) > 3 else symbol
                else:
                    alpaca_symbol = symbol
                request = CryptoBarsRequest(
                    symbol_or_symbols=alpaca_symbol,
                    timeframe=tf,
                    start=start,
                    end=end,
                    limit=limit
                )
                bars = self._retry_on_error(
                    self.crypto_data_client.get_crypto_bars,
                    request
                )
            else:
                request = StockBarsRequest(
                    symbol_or_symbols=symbol,
                    timeframe=tf,
                    start=start,
                    end=end,
                    limit=limit,
                    feed='iex'  # Feed gratuito
                )
                bars = self._retry_on_error(
                    self.stock_data_client.get_stock_bars,
                    request
                )

            # Converti in DataFrame
            df = bars.df
            if df is None or df.empty:
                logger.warning(f"Nessun dato per {symbol} timeframe {timeframe}")
                return None

            # Rimuovi il livello MultiIndex se presente
            if hasattr(df.index, 'levels'):
                df = df.droplevel(0)

            # Rinomina colonne in minuscolo
            df.columns = [c.lower() for c in df.columns]

            logger.debug(f"Recuperati {len(df)} bar per {symbol} ({timeframe})")
            return df

        except Exception as e:
            logger.error(f"Errore recupero dati {symbol} {timeframe}: {e}")
            return None

    def get_latest_price(self, symbol: str) -> Optional[float]:
        """
        Recupera il prezzo più recente di un asset.

        Args:
            symbol: Simbolo dell'asset

        Returns:
            Prezzo attuale o None in caso di errore
        """
        try:
            is_crypto = '/' in symbol or symbol in ['BTCUSD', 'ETHUSD']

            if is_crypto:
                # Assicura che il simbolo crypto abbia il formato BTC/USD (Alpaca lo richiede)
                if '/' not in symbol:
                    alpaca_symbol = symbol[:-3] + '/' + symbol[-3:] if len(symbol) > 3 else symbol
                else:
                    alpaca_symbol = symbol
                request = CryptoLatestQuoteRequest(symbol_or_symbols=alpaca_symbol)
                quote = self._retry_on_error(
                    self.crypto_data_client.get_crypto_latest_quote,
                    request
                )
                symbol_key = alpaca_symbol
            else:
                request = StockLatestQuoteRequest(symbol_or_symbols=symbol)
                quote = self._retry_on_error(
                    self.stock_data_client.get_stock_latest_quote,
                    request
                )
                symbol_key = symbol

            if quote and symbol_key in quote:
                q = quote[symbol_key]
                # Usa il mid price tra ask e bid
                price = (float(q.ask_price) + float(q.bid_price)) / 2
                return price

        except Exception as e:
            logger.error(f"Errore recupero prezzo {symbol}: {e}")
            return None

    def get_recent_bars(self, symbol: str, timeframe: str = '5m', periods: int = 100):
        """
        Recupera le ultime N candele per un simbolo.

        Args:
            symbol: Simbolo dell'asset
            timeframe: Timeframe delle candele
            periods: Numero di candele da recuperare

        Returns:
            DataFrame con le candele
        """
        # Calcola la data di inizio in base al timeframe e numero di periodi
        tf_minutes = {
            '1m': 1, '5m': 5, '15m': 15, '30m': 30,
            '1h': 60, '4h': 240, '1d': 1440
        }
        minutes = tf_minutes.get(timeframe, 5)
        start = datetime.now(UTC_TZ) - timedelta(minutes=minutes * periods * 2)
        # Moltiplico per 2 per avere un buffer extra (mercato chiuso nei fine settimana)

        return self.get_bars(symbol, timeframe, start, limit=periods)

    # ----------------------------------------------------------------
    # STATO MERCATO
    # ----------------------------------------------------------------

    def is_market_open(self) -> bool:
        """Verifica se il mercato azionario USA è attualmente aperto."""
        try:
            clock = self._retry_on_error(self.trading_client.get_clock)
            return clock.is_open
        except Exception as e:
            logger.error(f"Errore verifica stato mercato: {e}")
            return False

    def get_next_market_open(self) -> Optional[datetime]:
        """Restituisce la prossima apertura del mercato."""
        try:
            clock = self._retry_on_error(self.trading_client.get_clock)
            return clock.next_open
        except Exception as e:
            logger.error(f"Errore recupero prossima apertura: {e}")
            return None

    def is_connected(self) -> bool:
        """Verifica se la connessione ad Alpaca è attiva."""
        try:
            self.trading_client.get_account()
            return True
        except Exception:
            return False
