# ============================================================
# PERFORMANCE TRACKER - Advanced Metrics Aggregation
# Aggrega metriche avanzate per real-time monitoring
# ============================================================

import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class PerformanceTracker:
    """
    Aggrega metriche di performance avanzate per valutazione real-time
    della qualità del bot e dell'efficienza dei trade.

    Metriche Tracciati:
    1. Rolling Win Rate (50, 100, 500 trade)
    2. Expected Value (EV) per trade
    3. Spread Cost Impact %
    4. Kelly Fraction Accuracy
    5. Regime Accuracy (TRENDING vs RANGING correctness)
    6. Sharpe Ratio rolling
    7. Max Drawdown
    8. Profit Factor
    9. Average Trade Duration
    10. Slippage Analysis

    Utilizzo:
    - Update continuamente nel main loop del bot
    - Mostrare su dashboard per valutazione performance
    - Usare per alert se metriche degradano
    - Validare strategie e regime detector
    """

    def __init__(self, config: dict, database):
        """Inizializza Performance Tracker."""
        self.config = config
        self.db = database

        # Cache metriche (aggiorna ogni N trade o ogni minuto)
        self._last_update = None
        self._update_interval = timedelta(minutes=5)  # Update ogni 5 minuti max
        self._metrics_cache = {}

        logger.info("PerformanceTracker inizializzato")

    def get_advanced_metrics(self) -> Dict:
        """
        Ritorna dizionario con tutte le metriche avanzate.

        {
            'rolling_metrics': {
                'wr_50': float,      # Win rate ultimi 50 trade
                'wr_100': float,     # Win rate ultimi 100 trade
                'wr_500': float,     # Win rate ultimi 500 trade
            },
            'edge_metrics': {
                'ev_per_trade': float,           # Expected Value medio
                'profit_factor': float,          # Gross profit / Gross loss
                'sharpe_ratio': float,           # Sharpe ratio rolling
            },
            'cost_metrics': {
                'spread_cost_total': float,      # € totali persi a spread
                'spread_cost_pct': float,        # % del capital
                'avg_slippage_pct': float,       # Slippage medio per trade
            },
            'regime_metrics': {
                'regime_accuracy_trending': float,   # % trades vincenti in TRENDING
                'regime_accuracy_ranging': float,    # % trades vincenti in RANGING
                'regime_distribution': {
                    'trending_count': int,
                    'ranging_count': int
                }
            },
            'kelly_metrics': {
                'kelly_fraction': float,         # Kelly attuale
                'kelly_vs_actual': float,        # Kelly teorico vs sizing effettivo
            },
            'session_metrics': {
                'avg_trade_duration_min': float, # Durata media trade in minuti
                'max_consecutive_losses': int,   # Max streak di loss
                'max_consecutive_wins': int,     # Max streak di wins
            },
            'timestamp': str
        }
        """
        try:
            # Check se cache è ancora valido
            now = datetime.now()
            if (self._last_update is not None and
                now - self._last_update < self._update_interval):
                return self._metrics_cache

            # ---- CALCULATE ALL METRICS ----
            trades = self.db.get_trade_history(limit=500)

            if not trades:
                return self._empty_metrics()

            # ---- 1. ROLLING WIN RATES ----
            wr_50 = self._calculate_win_rate(trades, limit=50)
            wr_100 = self._calculate_win_rate(trades, limit=100)
            wr_500 = self._calculate_win_rate(trades, limit=500)

            # ---- 2. EDGE METRICS ----
            ev_per_trade = self._calculate_expected_value(trades)
            profit_factor = self._calculate_profit_factor(trades)
            sharpe_ratio = self._calculate_sharpe_ratio(trades)

            # ---- 3. COST METRICS ----
            spread_cost_total, spread_cost_pct = self._calculate_spread_cost(trades)
            avg_slippage = self._calculate_avg_slippage(trades)

            # ---- 4. REGIME METRICS ----
            regime_trending_wr = self._calculate_regime_accuracy(trades, 'TRENDING')
            regime_ranging_wr = self._calculate_regime_accuracy(trades, 'RANGING')
            regime_dist = self._calculate_regime_distribution(trades)

            # ---- 5. KELLY METRICS ----
            kelly_frac = self._calculate_kelly_fraction(trades)
            kelly_vs_actual = self._compare_kelly_vs_actual(trades, kelly_frac)

            # ---- 6. SESSION METRICS ----
            avg_duration = self._calculate_avg_trade_duration(trades)
            max_loss_streak = self._calculate_max_loss_streak(trades)
            max_win_streak = self._calculate_max_win_streak(trades)

            # ---- BUILD RESULT ----
            result = {
                'rolling_metrics': {
                    'wr_50': round(wr_50, 3),
                    'wr_100': round(wr_100, 3),
                    'wr_500': round(wr_500, 3),
                },
                'edge_metrics': {
                    'ev_per_trade': round(ev_per_trade, 2),
                    'profit_factor': round(profit_factor, 2),
                    'sharpe_ratio': round(sharpe_ratio, 2),
                },
                'cost_metrics': {
                    'spread_cost_total': round(spread_cost_total, 2),
                    'spread_cost_pct': round(spread_cost_pct * 100, 2),
                    'avg_slippage_pct': round(avg_slippage * 100, 3),
                },
                'regime_metrics': {
                    'regime_accuracy_trending': round(regime_trending_wr, 3),
                    'regime_accuracy_ranging': round(regime_ranging_wr, 3),
                    'regime_distribution': regime_dist,
                },
                'kelly_metrics': {
                    'kelly_fraction': round(kelly_frac, 4),
                    'kelly_vs_actual': round(kelly_vs_actual, 3),
                },
                'session_metrics': {
                    'avg_trade_duration_min': round(avg_duration, 1),
                    'max_consecutive_losses': max_loss_streak,
                    'max_consecutive_wins': max_win_streak,
                },
                'timestamp': datetime.now().isoformat()
            }

            # Cache result
            self._last_update = now
            self._metrics_cache = result

            logger.debug(f"Performance metrics updated: WR50={wr_50:.1%}, EV=${ev_per_trade:.2f}, PF={profit_factor:.2f}")
            return result

        except Exception as e:
            logger.error(f"Errore calcolo performance metrics: {e}")
            return self._empty_metrics()

    # ---- HELPER METHODS ----

    def _calculate_win_rate(self, trades: List[Dict], limit: int = 50) -> float:
        """Calcola win rate su ultimi N trade."""
        relevant = trades[:limit]
        if not relevant:
            return 0.0
        wins = len([t for t in relevant if t.get('pnl', 0) > 0])
        return wins / len(relevant)

    def _calculate_expected_value(self, trades: List[Dict]) -> float:
        """Calcola EV medio per trade."""
        if not trades:
            return 0.0
        total_pnl = sum([t.get('pnl', 0) for t in trades])
        return total_pnl / len(trades)

    def _calculate_profit_factor(self, trades: List[Dict]) -> float:
        """Calcola profit factor (gross_profit / gross_loss)."""
        gross_profit = sum([t['pnl'] for t in trades if t.get('pnl', 0) > 0])
        gross_loss = sum([abs(t['pnl']) for t in trades if t.get('pnl', 0) <= 0])
        return gross_profit / gross_loss if gross_loss > 0 else 1.0

    def _calculate_sharpe_ratio(self, trades: List[Dict]) -> float:
        """Calcola Sharpe ratio su returns."""
        if len(trades) < 2:
            return 0.0
        pnls = [t.get('pnl', 0) for t in trades]
        import statistics
        mean = statistics.mean(pnls)
        stddev = statistics.stdev(pnls) if len(pnls) > 1 else 0
        return (mean / stddev * (252 ** 0.5)) if stddev > 0 else 0.0

    def _calculate_spread_cost(self, trades: List[Dict]) -> tuple:
        """Calcola costo totale dello spread."""
        # Estimato come 0.05% dello slippage per trade
        total_cost = 0.0
        for t in trades:
            if 'entry_price' in t and 'exit_price' in t:
                entry = t['entry_price']
                cost = entry * 0.0005  # 0.05% spread estimate
                total_cost += cost
        capital_total = sum([t.get('pnl', 0) for t in trades]) * 10  # Rough estimate
        cost_pct = total_cost / capital_total if capital_total > 0 else 0
        return total_cost, cost_pct

    def _calculate_avg_slippage(self, trades: List[Dict]) -> float:
        """Calcola slippage medio per trade."""
        # Placeholder: ritorna 0.0005 (0.05%)
        return 0.0005

    def _calculate_regime_accuracy(self, trades: List[Dict], regime: str) -> float:
        """Calcola win rate in specifico regime (TRENDING/RANGING)."""
        regime_trades = [t for t in trades if t.get('regime') == regime]
        if not regime_trades:
            return 0.5
        wins = len([t for t in regime_trades if t.get('pnl', 0) > 0])
        return wins / len(regime_trades)

    def _calculate_regime_distribution(self, trades: List[Dict]) -> Dict:
        """Ritorna distribuzione di regime nei trade."""
        trending = len([t for t in trades if t.get('regime') == 'TRENDING'])
        ranging = len([t for t in trades if t.get('regime') == 'RANGING'])
        return {
            'trending_count': trending,
            'ranging_count': ranging,
            'total': len(trades)
        }

    def _calculate_kelly_fraction(self, trades: List[Dict]) -> float:
        """Calcola Kelly fraction dai trade."""
        if len(trades) < 5:
            return 0.0
        wins = [t for t in trades if t.get('pnl', 0) > 0]
        losses = [t for t in trades if t.get('pnl', 0) <= 0]
        if not wins or not losses:
            return 0.0
        wr = len(wins) / len(trades)
        avg_w = sum([t['pnl'] for t in wins]) / len(wins)
        avg_l = sum([abs(t['pnl']) for t in losses]) / len(losses)
        kelly = (wr * avg_w - (1 - wr) * avg_l) / avg_w if avg_w > 0 else 0
        return kelly * 0.5  # Half-Kelly

    def _compare_kelly_vs_actual(self, trades: List[Dict], kelly_frac: float) -> float:
        """Confronta Kelly teorico vs sizing effettivo."""
        avg_position_size = sum([t.get('capital_at_risk', 0) for t in trades]) / len(trades)
        capital = self.config.get('trading', {}).get('capital_eur', 2500) * 1.09
        actual_pct = avg_position_size / capital if capital > 0 else 0
        return kelly_frac - actual_pct

    def _calculate_avg_trade_duration(self, trades: List[Dict]) -> float:
        """Calcola durata media di un trade in minuti."""
        durations = []
        for t in trades:
            if 'entry_time' in t and 'exit_time' in t:
                try:
                    # Parse timestamp and calc duration
                    duration_min = 5  # Placeholder
                    durations.append(duration_min)
                except:
                    pass
        return sum(durations) / len(durations) if durations else 0.0

    def _calculate_max_loss_streak(self, trades: List[Dict]) -> int:
        """Calcola max streak di perdite consecutive."""
        max_streak = 0
        current_streak = 0
        for t in trades:
            if t.get('pnl', 0) <= 0:
                current_streak += 1
                max_streak = max(max_streak, current_streak)
            else:
                current_streak = 0
        return max_streak

    def _calculate_max_win_streak(self, trades: List[Dict]) -> int:
        """Calcola max streak di vittorie consecutive."""
        max_streak = 0
        current_streak = 0
        for t in trades:
            if t.get('pnl', 0) > 0:
                current_streak += 1
                max_streak = max(max_streak, current_streak)
            else:
                current_streak = 0
        return max_streak

    @staticmethod
    def _empty_metrics() -> Dict:
        """Ritorna metriche vuote/default quando dati insufficienti."""
        return {
            'rolling_metrics': {
                'wr_50': 0.0,
                'wr_100': 0.0,
                'wr_500': 0.0,
            },
            'edge_metrics': {
                'ev_per_trade': 0.0,
                'profit_factor': 1.0,
                'sharpe_ratio': 0.0,
            },
            'cost_metrics': {
                'spread_cost_total': 0.0,
                'spread_cost_pct': 0.0,
                'avg_slippage_pct': 0.0,
            },
            'regime_metrics': {
                'regime_accuracy_trending': 0.5,
                'regime_accuracy_ranging': 0.5,
                'regime_distribution': {'trending_count': 0, 'ranging_count': 0, 'total': 0},
            },
            'kelly_metrics': {
                'kelly_fraction': 0.0,
                'kelly_vs_actual': 0.0,
            },
            'session_metrics': {
                'avg_trade_duration_min': 0.0,
                'max_consecutive_losses': 0,
                'max_consecutive_wins': 0,
            },
            'timestamp': datetime.now().isoformat()
        }
