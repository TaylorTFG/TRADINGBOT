# ============================================================
# BACKTESTING ENGINE
# Simula il trading su dati storici con commissioni e slippage
# Genera report HTML con metriche complete di performance
# ============================================================

import logging
import os
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
from pathlib import Path

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


class BacktestResult:
    """Contenitore per i risultati del backtest."""

    def __init__(self):
        self.trades: List[Dict] = []
        self.equity_curve: List[float] = []
        self.dates: List[datetime] = []
        self.metrics: Dict = {}

    def add_trade(self, trade: Dict):
        self.trades.append(trade)

    def calculate_metrics(self, initial_capital: float):
        """Calcola tutte le metriche di performance."""
        if not self.trades:
            self.metrics = {'error': 'Nessun trade nel backtest'}
            return

        closed_trades = [t for t in self.trades if t.get('status') == 'closed']
        if not closed_trades:
            self.metrics = {'error': 'Nessun trade chiuso nel backtest'}
            return

        pnls = [t['pnl'] for t in closed_trades]
        pnl_pcts = [t['pnl_pct'] for t in closed_trades]

        winning = [p for p in pnls if p > 0]
        losing = [p for p in pnls if p <= 0]

        total_pnl = sum(pnls)
        win_rate = len(winning) / len(pnls) if pnls else 0

        gross_profit = sum(winning) if winning else 0
        gross_loss = abs(sum(losing)) if losing else 0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

        # Equity curve e max drawdown
        equity = initial_capital
        peak_equity = initial_capital
        max_dd = 0
        equity_curve = [initial_capital]

        for pnl in pnls:
            equity += pnl
            equity_curve.append(equity)
            if equity > peak_equity:
                peak_equity = equity
            dd = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0
            if dd > max_dd:
                max_dd = dd

        self.equity_curve = equity_curve

        # Sharpe Ratio (annualizzato)
        if len(pnl_pcts) > 1:
            mean_return = np.mean(pnl_pcts)
            std_return = np.std(pnl_pcts, ddof=1)
            sharpe = (mean_return / std_return) * np.sqrt(252) if std_return > 0 else 0
        else:
            sharpe = 0

        self.metrics = {
            'total_trades': len(pnls),
            'winning_trades': len(winning),
            'losing_trades': len(losing),
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'total_return_pct': total_pnl / initial_capital,
            'avg_pnl': total_pnl / len(pnls) if pnls else 0,
            'avg_win': np.mean(winning) if winning else 0,
            'avg_loss': np.mean(losing) if losing else 0,
            'profit_factor': profit_factor,
            'sharpe_ratio': sharpe,
            'max_drawdown': max_dd,
            'gross_profit': gross_profit,
            'gross_loss': gross_loss,
            'final_capital': initial_capital + total_pnl,
            'initial_capital': initial_capital,
        }

        return self.metrics


class BacktestEngine:
    """
    Motore di backtesting completo.

    Simula il comportamento del bot su dati storici:
    - Commissioni reali (0% su Alpaca)
    - Slippage simulato (0.05%)
    - Gestione stop loss, take profit, trailing stop
    - Report HTML automatici
    """

    def __init__(self, config: dict, broker):
        """
        Inizializza il motore di backtesting.

        Args:
            config: Configurazione dal config.yaml
            broker: BrokerClient per recuperare dati storici
        """
        self.config = config
        self.broker = broker
        self.backtest_config = config.get('backtesting', {})

        self.slippage = self.backtest_config.get('slippage_pct', 0.0005)
        self.commission = self.backtest_config.get('commission_pct', 0.0)

        # Capital iniziale in EUR → USD (approssimativo)
        capital_eur = config.get('trading', {}).get('capital_eur', 500)
        self.initial_capital = capital_eur * 1.09  # Conversione approssimativa EUR→USD

        # Directory output
        self.reports_dir = Path('backtester/reports')
        self.reports_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"BacktestEngine inizializzato (capitale: ${self.initial_capital:.2f})")

    def run_strategy(
        self,
        strategy_name: str,
        symbol: str,
        df: pd.DataFrame,
        signals: List[Dict]
    ) -> BacktestResult:
        """
        Esegue il backtest per una strategia su un simbolo.

        Args:
            strategy_name: Nome della strategia
            symbol: Simbolo testato
            df: DataFrame con dati OHLCV
            signals: Lista di segnali generati dalla strategia

        Returns:
            BacktestResult con trades e metriche
        """
        result = BacktestResult()
        capital = self.initial_capital
        open_position = None

        risk_config = self.config.get('risk_management', {})
        stop_loss_pct = risk_config.get('stop_loss_pct', 0.015)
        take_profit_pct = risk_config.get('take_profit_pct', 0.03)
        trailing_activation = risk_config.get('trailing_stop', {}).get('activation_pct', 0.01)
        trailing_distance = risk_config.get('trailing_stop', {}).get('trail_pct', 0.008)
        max_risk_pct = risk_config.get('max_risk_per_trade', 0.02)

        for i, row in df.iterrows():
            # Trova il segnale per questo timestamp se disponibile
            signal = next((s for s in signals if s.get('timestamp') == i), None)
            if signal is None:
                signal_type = 'HOLD'
            else:
                signal_type = signal.get('signal', 'HOLD')

            close = float(row['close'])
            high = float(row['high'])
            low = float(row['low'])

            # --- GESTIONE POSIZIONE APERTA ---
            if open_position:
                entry_price = open_position['entry_price']

                # Simula stop loss (usa il low della candela)
                stop_loss = open_position['stop_loss']
                if low <= stop_loss:
                    exit_price = stop_loss * (1 - self.slippage)
                    pnl = (exit_price - entry_price) * open_position['qty']
                    capital += pnl
                    open_position['exit_price'] = exit_price
                    open_position['exit_time'] = i
                    open_position['pnl'] = pnl
                    open_position['pnl_pct'] = (exit_price - entry_price) / entry_price
                    open_position['exit_reason'] = 'stop_loss'
                    open_position['status'] = 'closed'
                    result.add_trade(dict(open_position))
                    open_position = None
                    continue

                # Simula take profit (usa il high della candela)
                take_profit = open_position['take_profit']
                if high >= take_profit:
                    exit_price = take_profit * (1 - self.slippage)
                    pnl = (exit_price - entry_price) * open_position['qty']
                    capital += pnl
                    open_position['exit_price'] = exit_price
                    open_position['exit_time'] = i
                    open_position['pnl'] = pnl
                    open_position['pnl_pct'] = (exit_price - entry_price) / entry_price
                    open_position['exit_reason'] = 'take_profit'
                    open_position['status'] = 'closed'
                    result.add_trade(dict(open_position))
                    open_position = None
                    continue

                # Aggiorna trailing stop
                profit_pct = (close - entry_price) / entry_price
                if profit_pct >= trailing_activation:
                    new_stop = close * (1 - trailing_distance)
                    if new_stop > open_position['stop_loss']:
                        open_position['stop_loss'] = new_stop

                # Segnale SELL su posizione aperta → chiudi
                if signal_type == 'SELL':
                    exit_price = close * (1 - self.slippage)
                    pnl = (exit_price - entry_price) * open_position['qty']
                    capital += pnl
                    open_position['exit_price'] = exit_price
                    open_position['exit_time'] = i
                    open_position['pnl'] = pnl
                    open_position['pnl_pct'] = (exit_price - entry_price) / entry_price
                    open_position['exit_reason'] = 'sell_signal'
                    open_position['status'] = 'closed'
                    result.add_trade(dict(open_position))
                    open_position = None
                    continue

            # --- APERTURA NUOVA POSIZIONE ---
            elif signal_type == 'BUY' and capital > 0:
                # Position sizing
                qty = (capital * max_risk_pct) / close
                entry_price = close * (1 + self.slippage)

                open_position = {
                    'symbol': symbol,
                    'strategy': strategy_name,
                    'side': 'buy',
                    'entry_price': entry_price,
                    'entry_time': i,
                    'qty': qty,
                    'stop_loss': entry_price * (1 - stop_loss_pct),
                    'take_profit': entry_price * (1 + take_profit_pct),
                    'status': 'open',
                    'capital_at_entry': capital
                }

        # Chiudi eventuale posizione ancora aperta alla fine del backtest
        if open_position:
            last_close = float(df['close'].iloc[-1])
            exit_price = last_close * (1 - self.slippage)
            pnl = (exit_price - open_position['entry_price']) * open_position['qty']
            capital += pnl
            open_position['exit_price'] = exit_price
            open_position['exit_time'] = df.index[-1]
            open_position['pnl'] = pnl
            open_position['pnl_pct'] = (exit_price - open_position['entry_price']) / open_position['entry_price']
            open_position['exit_reason'] = 'end_of_data'
            open_position['status'] = 'closed'
            result.add_trade(dict(open_position))

        result.calculate_metrics(self.initial_capital)
        return result

    def run_full_backtest(self, symbols: Optional[List[str]] = None) -> Dict:
        """
        Esegue il backtest completo su tutti i simboli e tutte le strategie.

        Args:
            symbols: Lista simboli da testare (default: dalla config)

        Returns:
            Dizionario con risultati per ogni strategia e simbolo
        """
        if symbols is None:
            symbols = []
            assets = self.config.get('assets', {})
            for cat in ['etf', 'stocks', 'crypto']:
                if assets.get(cat, {}).get('enabled', True):
                    symbols.extend(assets[cat].get('symbols', []))

        history_years = self.backtest_config.get('history_years', 3)
        start_date = datetime.now() - timedelta(days=history_years * 365)

        all_results = {}

        for symbol in symbols:
            logger.info(f"Backtest su {symbol}...")

            # Recupera dati storici
            df = self.broker.get_bars(symbol, '1d', start_date)
            if df is None or df.empty:
                logger.warning(f"Nessun dato per {symbol}")
                continue

            symbol_results = {}

            # --- Backtest Strategia 1: Confluence ---
            try:
                from bot.strategy_confluence import ConfluenceStrategy
                confluence = ConfluenceStrategy(self.config)
                df_indicators = confluence.calculate_indicators(df)
                if df_indicators is not None:
                    signals = [
                        confluence.analyze(df_indicators.iloc[:i+1], symbol)
                        for i in range(50, len(df_indicators))
                    ]
                    # Associa ogni segnale al suo timestamp
                    for i, sig in enumerate(signals):
                        sig['timestamp'] = df_indicators.index[50 + i]

                    result = self.run_strategy('confluence', symbol, df_indicators, signals)
                    symbol_results['confluence'] = result
                    logger.info(f"  Confluence: {result.metrics.get('total_return_pct', 0):.2%} | "
                               f"W/R: {result.metrics.get('win_rate', 0):.1%}")
            except Exception as e:
                logger.error(f"Errore backtest confluence {symbol}: {e}")

            # --- Backtest Strategia 2: Breakout ---
            try:
                from bot.strategy_breakout import BreakoutStrategy
                breakout = BreakoutStrategy(self.config)
                signals_bt = []
                for i in range(30, len(df)):
                    window = df.iloc[max(0, i-200):i+1]
                    daily_window = df.iloc[max(0, i-30):i+1]
                    sig = breakout.analyze(window, daily_window, symbol)
                    sig['timestamp'] = df.index[i]
                    signals_bt.append(sig)

                result = self.run_strategy('breakout', symbol, df, signals_bt)
                symbol_results['breakout'] = result
                logger.info(f"  Breakout: {result.metrics.get('total_return_pct', 0):.2%} | "
                           f"W/R: {result.metrics.get('win_rate', 0):.1%}")
            except Exception as e:
                logger.error(f"Errore backtest breakout {symbol}: {e}")

            all_results[symbol] = symbol_results

        # Genera report HTML
        report_path = self.generate_html_report(all_results)
        logger.info(f"Report backtest generato: {report_path}")

        return all_results

    def generate_html_report(self, results: Dict) -> str:
        """
        Genera un report HTML interattivo con i risultati del backtest.

        Args:
            results: Risultati del backtest per simbolo e strategia

        Returns:
            Percorso del file HTML generato
        """
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        report_path = self.reports_dir / f"backtest_{timestamp}.html"

        # Calcola statistiche aggregate
        all_metrics = []
        for symbol, strategies in results.items():
            for strategy, result in strategies.items():
                if isinstance(result, BacktestResult) and result.metrics:
                    metrics = result.metrics.copy()
                    metrics['symbol'] = symbol
                    metrics['strategy'] = strategy
                    all_metrics.append(metrics)

        # Genera HTML
        html = self._build_html_report(all_metrics, results)

        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(html)

        return str(report_path)

    def _build_html_report(self, all_metrics: List[Dict], results: Dict) -> str:
        """Costruisce il contenuto HTML del report."""
        targets = self.backtest_config.get('targets', {})

        def fmt_pct(v):
            if v is None:
                return 'N/A'
            return f"{v:.2%}"

        def fmt_money(v):
            if v is None:
                return 'N/A'
            return f"${v:.2f}"

        def status_color(val, target, higher_better=True):
            if val is None:
                return '#666'
            if higher_better:
                return '#22c55e' if val >= target else '#ef4444'
            else:
                return '#22c55e' if val <= target else '#ef4444'

        rows = ""
        for m in all_metrics:
            sharpe_ok = m.get('sharpe_ratio', 0) >= targets.get('sharpe_ratio', 1.5)
            dd_ok = m.get('max_drawdown', 1) <= targets.get('max_drawdown', 0.15)
            wr_ok = m.get('win_rate', 0) >= targets.get('win_rate', 0.55)
            pf_ok = m.get('profit_factor', 0) >= targets.get('profit_factor', 1.5)

            rows += f"""
            <tr>
                <td><strong>{m.get('symbol', '')}</strong></td>
                <td>{m.get('strategy', '').upper()}</td>
                <td style="color: {'#22c55e' if m.get('total_return_pct', 0) > 0 else '#ef4444'}">
                    <strong>{fmt_pct(m.get('total_return_pct'))}</strong>
                </td>
                <td>{m.get('total_trades', 0)}</td>
                <td style="color: {'#22c55e' if wr_ok else '#ef4444'}">{fmt_pct(m.get('win_rate'))}</td>
                <td style="color: {'#22c55e' if pf_ok else '#ef4444'}">{m.get('profit_factor', 0):.2f}</td>
                <td style="color: {'#22c55e' if sharpe_ok else '#ef4444'}">{m.get('sharpe_ratio', 0):.2f}</td>
                <td style="color: {'#22c55e' if dd_ok else '#ef4444'}">{fmt_pct(m.get('max_drawdown'))}</td>
                <td>{fmt_money(m.get('final_capital'))}</td>
            </tr>"""

        return f"""<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Trading Bot - Report Backtest</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                background: #0f172a; color: #e2e8f0; padding: 2rem; }}
        h1 {{ font-size: 2rem; color: #38bdf8; margin-bottom: 0.5rem; }}
        h2 {{ font-size: 1.25rem; color: #94a3b8; margin: 2rem 0 1rem; }}
        .subtitle {{ color: #64748b; margin-bottom: 2rem; }}
        .targets {{ background: #1e293b; border-radius: 12px; padding: 1.5rem; margin-bottom: 2rem; }}
        .targets h3 {{ color: #38bdf8; margin-bottom: 1rem; }}
        .targets-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 1rem; }}
        .target-card {{ background: #0f172a; border-radius: 8px; padding: 1rem; text-align: center; }}
        .target-card .label {{ font-size: 0.8rem; color: #64748b; margin-bottom: 0.25rem; }}
        .target-card .value {{ font-size: 1.25rem; font-weight: bold; color: #38bdf8; }}
        table {{ width: 100%; border-collapse: collapse; background: #1e293b;
                 border-radius: 12px; overflow: hidden; }}
        th {{ background: #0f172a; padding: 1rem; text-align: left; font-size: 0.8rem;
              text-transform: uppercase; letter-spacing: 0.05em; color: #64748b; }}
        td {{ padding: 0.875rem 1rem; border-bottom: 1px solid #0f172a; }}
        tr:last-child td {{ border-bottom: none; }}
        tr:hover td {{ background: rgba(56, 189, 248, 0.05); }}
        .badge {{ display: inline-block; padding: 0.2rem 0.6rem; border-radius: 4px;
                  font-size: 0.75rem; font-weight: bold; }}
        .badge-ok {{ background: rgba(34, 197, 94, 0.2); color: #22c55e; }}
        .badge-fail {{ background: rgba(239, 68, 68, 0.2); color: #ef4444; }}
        footer {{ margin-top: 2rem; color: #475569; font-size: 0.8rem; text-align: center; }}
    </style>
</head>
<body>
    <h1>📊 Trading Bot - Report Backtest</h1>
    <p class="subtitle">Generato il {datetime.now().strftime('%d/%m/%Y alle %H:%M:%S')}</p>

    <div class="targets">
        <h3>🎯 Target di Performance</h3>
        <div class="targets-grid">
            <div class="target-card">
                <div class="label">Sharpe Ratio</div>
                <div class="value">> {targets.get('sharpe_ratio', 1.5)}</div>
            </div>
            <div class="target-card">
                <div class="label">Max Drawdown</div>
                <div class="value">< {targets.get('max_drawdown', 0.15):.0%}</div>
            </div>
            <div class="target-card">
                <div class="label">Win Rate</div>
                <div class="value">> {targets.get('win_rate', 0.55):.0%}</div>
            </div>
            <div class="target-card">
                <div class="label">Profit Factor</div>
                <div class="value">> {targets.get('profit_factor', 1.5)}</div>
            </div>
        </div>
    </div>

    <h2>📈 Risultati per Strategia e Simbolo</h2>
    <table>
        <thead>
            <tr>
                <th>Simbolo</th>
                <th>Strategia</th>
                <th>Return Totale</th>
                <th>Trade</th>
                <th>Win Rate</th>
                <th>Profit Factor</th>
                <th>Sharpe</th>
                <th>Max Drawdown</th>
                <th>Capitale Finale</th>
            </tr>
        </thead>
        <tbody>
            {rows}
        </tbody>
    </table>

    <footer>
        Trading Bot v1.0 | Capitale iniziale: ${self.initial_capital:.2f} |
        Slippage: {self.slippage:.3%} | Commissioni: {self.commission:.3%}
    </footer>
</body>
</html>"""
