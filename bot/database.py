# ============================================================
# DATABASE MANAGER - TRADING BOT
# Gestione database SQLite per trade, segnali e statistiche
# ============================================================

import sqlite3
import logging
import json
from datetime import datetime, date
from typing import Optional, List, Dict, Any
from pathlib import Path

logger = logging.getLogger(__name__)


class DatabaseManager:
    """
    Gestisce tutte le operazioni sul database SQLite.
    Salva trade, segnali, statistiche giornaliere e log del bot.
    """

    def __init__(self, db_path: str = "data/trades.db"):
        """
        Inizializza il database manager.

        Args:
            db_path: Percorso del file SQLite
        """
        self.db_path = db_path
        # Crea la directory se non esiste
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_database()
        logger.info(f"Database inizializzato: {db_path}")

    def _get_connection(self) -> sqlite3.Connection:
        """Crea e restituisce una connessione al database con row_factory."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Accesso alle colonne per nome
        conn.execute("PRAGMA journal_mode=WAL")  # Migliore concorrenza
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_database(self):
        """Crea le tabelle del database se non esistono."""
        with self._get_connection() as conn:
            conn.executescript("""
                -- Tabella trade (posizioni aperte e chiuse)
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL CHECK(side IN ('buy', 'sell')),
                    quantity REAL NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_price REAL,
                    entry_time DATETIME NOT NULL,
                    exit_time DATETIME,
                    pnl REAL,
                    pnl_pct REAL,
                    strategy TEXT,
                    exit_reason TEXT,
                    stop_loss REAL,
                    take_profit REAL,
                    trailing_stop REAL,
                    status TEXT DEFAULT 'open' CHECK(status IN ('open', 'closed', 'cancelled')),
                    alpaca_order_id TEXT,
                    ml_confidence REAL,
                    vote_score INTEGER,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );

                -- Tabella segnali generati dalle strategie
                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME NOT NULL,
                    symbol TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    signal TEXT NOT NULL CHECK(signal IN ('BUY', 'SELL', 'HOLD')),
                    score REAL,
                    confidence REAL,
                    details TEXT,
                    executed INTEGER DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );

                -- Statistiche giornaliere
                CREATE TABLE IF NOT EXISTS daily_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date DATE NOT NULL UNIQUE,
                    starting_capital REAL,
                    ending_capital REAL,
                    pnl REAL,
                    pnl_pct REAL,
                    trades_count INTEGER DEFAULT 0,
                    winning_trades INTEGER DEFAULT 0,
                    losing_trades INTEGER DEFAULT 0,
                    max_drawdown REAL,
                    best_trade_pnl REAL,
                    worst_trade_pnl REAL,
                    mode TEXT DEFAULT 'paper',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );

                -- Log eventi bot
                CREATE TABLE IF NOT EXISTS bot_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    event_type TEXT NOT NULL,
                    description TEXT,
                    data TEXT
                );

                -- Dati performance ML
                CREATE TABLE IF NOT EXISTS ml_predictions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME NOT NULL,
                    symbol TEXT NOT NULL,
                    predicted_profitable INTEGER,
                    confidence REAL,
                    actual_result INTEGER,
                    features TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );

                -- Indici per performance
                CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
                CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
                CREATE INDEX IF NOT EXISTS idx_trades_entry_time ON trades(entry_time);
                CREATE INDEX IF NOT EXISTS idx_signals_timestamp ON signals(timestamp);
                CREATE INDEX IF NOT EXISTS idx_signals_symbol ON signals(symbol);
                CREATE INDEX IF NOT EXISTS idx_daily_stats_date ON daily_stats(date);
            """)
        logger.debug("Schema database verificato/creato")

    # ----------------------------------------------------------------
    # GESTIONE TRADE
    # ----------------------------------------------------------------

    def insert_trade(self, trade_data: Dict[str, Any]) -> int:
        """
        Inserisce un nuovo trade nel database.

        Args:
            trade_data: Dizionario con i dati del trade

        Returns:
            ID del trade inserito
        """
        with self._get_connection() as conn:
            cursor = conn.execute("""
                INSERT INTO trades (
                    symbol, side, quantity, entry_price, entry_time,
                    strategy, stop_loss, take_profit, status,
                    alpaca_order_id, ml_confidence, vote_score
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trade_data['symbol'],
                trade_data['side'],
                trade_data['quantity'],
                trade_data['entry_price'],
                trade_data.get('entry_time', datetime.now().isoformat()),
                trade_data.get('strategy', 'unknown'),
                trade_data.get('stop_loss'),
                trade_data.get('take_profit'),
                'open',
                trade_data.get('alpaca_order_id'),
                trade_data.get('ml_confidence'),
                trade_data.get('vote_score')
            ))
            trade_id = cursor.lastrowid
            logger.info(f"Trade inserito DB: ID={trade_id}, {trade_data['symbol']} {trade_data['side']}")
            return trade_id

    def close_trade(self, trade_id: int, exit_price: float, exit_reason: str) -> bool:
        """
        Chiude un trade nel database calcolando PnL.

        Args:
            trade_id: ID del trade da chiudere
            exit_price: Prezzo di uscita
            exit_reason: Motivo della chiusura

        Returns:
            True se successo
        """
        with self._get_connection() as conn:
            # Recupera i dati del trade aperto
            row = conn.execute(
                "SELECT * FROM trades WHERE id = ? AND status = 'open'",
                (trade_id,)
            ).fetchone()

            if not row:
                logger.warning(f"Trade {trade_id} non trovato o già chiuso")
                return False

            # Calcola PnL
            entry_price = row['entry_price']
            quantity = row['quantity']
            side = row['side']

            if side == 'buy':
                pnl = (exit_price - entry_price) * quantity
                pnl_pct = (exit_price - entry_price) / entry_price
            else:
                pnl = (entry_price - exit_price) * quantity
                pnl_pct = (entry_price - exit_price) / entry_price

            conn.execute("""
                UPDATE trades SET
                    exit_price = ?,
                    exit_time = ?,
                    pnl = ?,
                    pnl_pct = ?,
                    exit_reason = ?,
                    status = 'closed'
                WHERE id = ?
            """, (
                exit_price,
                datetime.now().isoformat(),
                pnl,
                pnl_pct,
                exit_reason,
                trade_id
            ))

            logger.info(f"Trade {trade_id} chiuso: PnL={pnl:.2f}$ ({pnl_pct:.2%}), motivo={exit_reason}")
            return True

    def update_trade_stop(self, trade_id: int, new_stop: float):
        """Aggiorna il trailing stop di un trade aperto."""
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE trades SET trailing_stop = ?, stop_loss = ? WHERE id = ?",
                (new_stop, new_stop, trade_id)
            )

    def get_open_trades(self) -> List[Dict]:
        """Restituisce tutti i trade attualmente aperti."""
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM trades WHERE status = 'open' ORDER BY entry_time DESC"
            ).fetchall()
            return [dict(row) for row in rows]

    def get_trade_by_symbol(self, symbol: str) -> Optional[Dict]:
        """Restituisce il trade aperto per un simbolo specifico."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM trades WHERE symbol = ? AND status = 'open'",
                (symbol,)
            ).fetchone()
            return dict(row) if row else None

    def get_trade_history(
        self,
        symbol: Optional[str] = None,
        strategy: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict]:
        """
        Restituisce lo storico trade con filtri opzionali.

        Args:
            symbol: Filtra per simbolo
            strategy: Filtra per strategia
            start_date: Data inizio (formato YYYY-MM-DD)
            end_date: Data fine (formato YYYY-MM-DD)
            limit: Numero massimo di risultati

        Returns:
            Lista di trade
        """
        query = "SELECT * FROM trades WHERE status = 'closed'"
        params = []

        if symbol:
            query += " AND symbol = ?"
            params.append(symbol)
        if strategy:
            query += " AND strategy = ?"
            params.append(strategy)
        if start_date:
            query += " AND entry_time >= ?"
            params.append(start_date)
        if end_date:
            query += " AND entry_time <= ?"
            params.append(end_date + " 23:59:59")

        query += " ORDER BY entry_time DESC LIMIT ?"
        params.append(limit)

        with self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]

    def get_today_stats(self) -> Dict:
        """Calcola statistiche dei trade di oggi."""
        today = date.today().isoformat()
        with self._get_connection() as conn:
            row = conn.execute("""
                SELECT
                    COUNT(*) as total_trades,
                    SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as winning,
                    SUM(CASE WHEN pnl <= 0 THEN 1 ELSE 0 END) as losing,
                    SUM(pnl) as total_pnl,
                    MAX(pnl) as best_trade,
                    MIN(pnl) as worst_trade
                FROM trades
                WHERE status = 'closed'
                AND date(exit_time) = ?
            """, (today,)).fetchone()
            return dict(row) if row else {}

    # ----------------------------------------------------------------
    # GESTIONE SEGNALI
    # ----------------------------------------------------------------

    def insert_signal(self, signal_data: Dict[str, Any]) -> int:
        """Salva un segnale generato da una strategia."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                INSERT INTO signals (timestamp, symbol, strategy, signal, score, confidence, details)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                signal_data.get('timestamp', datetime.now().isoformat()),
                signal_data['symbol'],
                signal_data['strategy'],
                signal_data['signal'],
                signal_data.get('score'),
                signal_data.get('confidence'),
                json.dumps(signal_data.get('details', {}))
            ))
            return cursor.lastrowid

    # ----------------------------------------------------------------
    # STATISTICHE GIORNALIERE
    # ----------------------------------------------------------------

    def update_daily_stats(self, stats: Dict[str, Any]):
        """Aggiorna o inserisce le statistiche del giorno corrente."""
        today = date.today().isoformat()
        with self._get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO daily_stats (
                    date, starting_capital, ending_capital, pnl, pnl_pct,
                    trades_count, winning_trades, losing_trades,
                    max_drawdown, best_trade_pnl, worst_trade_pnl, mode
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                today,
                stats.get('starting_capital'),
                stats.get('ending_capital'),
                stats.get('pnl'),
                stats.get('pnl_pct'),
                stats.get('trades_count', 0),
                stats.get('winning_trades', 0),
                stats.get('losing_trades', 0),
                stats.get('max_drawdown'),
                stats.get('best_trade_pnl'),
                stats.get('worst_trade_pnl'),
                stats.get('mode', 'paper')
            ))

    def get_daily_stats_history(self, days: int = 30) -> List[Dict]:
        """Restituisce le statistiche giornaliere degli ultimi N giorni."""
        with self._get_connection() as conn:
            rows = conn.execute("""
                SELECT * FROM daily_stats
                ORDER BY date DESC
                LIMIT ?
            """, (days,)).fetchall()
            return [dict(row) for row in rows]

    # ----------------------------------------------------------------
    # EVENTI BOT
    # ----------------------------------------------------------------

    def log_event(self, event_type: str, description: str, data: Optional[Dict] = None):
        """Registra un evento del bot nel database."""
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO bot_events (event_type, description, data)
                VALUES (?, ?, ?)
            """, (event_type, description, json.dumps(data) if data else None))

    # ----------------------------------------------------------------
    # METRICHE PERFORMANCE
    # ----------------------------------------------------------------

    def get_performance_metrics(self) -> Dict:
        """
        Calcola le metriche di performance aggregate su tutti i trade chiusi.

        Returns:
            Dizionario con Sharpe ratio, win rate, profit factor, ecc.
        """
        with self._get_connection() as conn:
            trades = conn.execute("""
                SELECT pnl, pnl_pct, entry_time, exit_time, strategy
                FROM trades WHERE status = 'closed'
                ORDER BY exit_time
            """).fetchall()

        if not trades:
            return {}

        pnls = [t['pnl'] for t in trades]
        pnl_pcts = [t['pnl_pct'] for t in trades]

        winning = [p for p in pnls if p > 0]
        losing = [p for p in pnls if p <= 0]

        total_pnl = sum(pnls)
        win_rate = len(winning) / len(pnls) if pnls else 0

        # Profit Factor
        gross_profit = sum(winning) if winning else 0
        gross_loss = abs(sum(losing)) if losing else 0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

        # Sharpe Ratio (semplificato)
        import statistics
        if len(pnl_pcts) > 1:
            mean_return = statistics.mean(pnl_pcts)
            std_return = statistics.stdev(pnl_pcts)
            sharpe = (mean_return / std_return) * (252 ** 0.5) if std_return > 0 else 0
        else:
            sharpe = 0

        # Max Drawdown
        cumulative = []
        running = 0
        for p in pnls:
            running += p
            cumulative.append(running)

        max_dd = 0
        peak = cumulative[0] if cumulative else 0
        for val in cumulative:
            if val > peak:
                peak = val
            dd = (peak - val) / abs(peak) if peak != 0 else 0
            if dd > max_dd:
                max_dd = dd

        return {
            'total_trades': len(pnls),
            'winning_trades': len(winning),
            'losing_trades': len(losing),
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'avg_pnl': total_pnl / len(pnls) if pnls else 0,
            'profit_factor': profit_factor,
            'sharpe_ratio': sharpe,
            'max_drawdown': max_dd,
            'gross_profit': gross_profit,
            'gross_loss': gross_loss,
            'avg_win': statistics.mean(winning) if winning else 0,
            'avg_loss': statistics.mean(losing) if losing else 0,
        }

    def get_strategy_performance(self) -> List[Dict]:
        """Performance separata per ogni strategia."""
        with self._get_connection() as conn:
            rows = conn.execute("""
                SELECT
                    strategy,
                    COUNT(*) as trades,
                    SUM(pnl) as total_pnl,
                    AVG(pnl) as avg_pnl,
                    SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                    SUM(CASE WHEN pnl <= 0 THEN 1 ELSE 0 END) as losses
                FROM trades
                WHERE status = 'closed' AND strategy IS NOT NULL
                GROUP BY strategy
                ORDER BY total_pnl DESC
            """).fetchall()
            return [dict(row) for row in rows]
