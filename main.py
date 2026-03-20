#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================
# MAIN - ENTRY POINT PRINCIPALE DEL TRADING BOT
# Avvia il bot, la dashboard o il backtester
# ============================================================

import argparse
import logging
import sys
import os
import yaml

# Forza UTF-8 su Windows per evitare UnicodeEncodeError
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

# ============================================================
# SETUP LOGGING
# ============================================================

def setup_logging(config: dict) -> logging.Logger:
    """
    Configura il sistema di logging con file rotante giornaliero.

    Args:
        config: Configurazione dal config.yaml

    Returns:
        Logger principale configurato
    """
    from logging.handlers import TimedRotatingFileHandler

    log_config = config.get('logging', {})
    log_level = getattr(logging, log_config.get('level', 'INFO').upper(), logging.INFO)
    log_dir = log_config.get('log_dir', 'logs')
    max_bytes = log_config.get('max_file_size_mb', 10) * 1024 * 1024
    backup_count = log_config.get('backup_count', 30)

    # Crea directory log
    Path(log_dir).mkdir(parents=True, exist_ok=True)

    # Nome file log con data
    log_filename = Path(log_dir) / f"trading_{datetime.now().strftime('%Y-%m-%d')}.log"

    # Formato log
    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(name)-25s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Handler file (rotante giornaliero)
    file_handler = TimedRotatingFileHandler(
        log_filename,
        when='midnight',
        interval=1,
        backupCount=backup_count,
        encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(log_level)

    # Handler console
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(log_level)

    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    # Silenzia librerie verbose
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('alpaca').setLevel(logging.WARNING)
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('telegram').setLevel(logging.WARNING)

    return logging.getLogger('main')


def load_config(config_path: str = "config.yaml") -> dict:
    """
    Carica la configurazione dal file YAML.

    Args:
        config_path: Percorso del file di configurazione

    Returns:
        Dizionario con la configurazione
    """
    path = Path(config_path)
    if not path.exists():
        print(f"ERRORE: File di configurazione '{config_path}' non trovato!")
        print("Crea il file config.yaml dalla template fornita.")
        sys.exit(1)

    with open(path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    return config


def check_api_keys(config: dict) -> bool:
    """
    Verifica che le chiavi API siano state configurate.

    Args:
        config: Configurazione

    Returns:
        True se le chiavi sono valide
    """
    mode = config.get('trading', {}).get('mode', 'paper')
    creds = config.get('alpaca', {}).get(mode, {})

    api_key = creds.get('api_key', '')
    api_secret = creds.get('api_secret', '')

    if 'YOUR_' in api_key or not api_key:
        print("="*60)
        print("ERRORE: Chiavi API Alpaca non configurate!")
        print("="*60)
        print(f"Modalità: {mode.upper()}")
        print("\nApri config.yaml e inserisci le tue credenziali:")
        print(f"  alpaca.{mode}.api_key: TUA_CHIAVE_API")
        print(f"  alpaca.{mode}.api_secret: TUA_CHIAVE_SEGRETA")
        print("\nOttieni le chiavi su: https://app.alpaca.markets/")
        return False

    return True


# ============================================================
# COMANDI PRINCIPALI
# ============================================================

def run_bot(args):
    """Avvia il bot di trading."""
    config = load_config(args.config)
    logger = setup_logging(config)

    logger.info("=" * 60)
    logger.info("TRADING BOT - AVVIO")
    logger.info(f"Versione: 1.0.0 | Python: {sys.version}")
    logger.info(f"Modalità: {config['trading']['mode'].upper()}")
    logger.info("=" * 60)

    # Override modalità se specificato da riga di comando
    if args.mode:
        config['trading']['mode'] = args.mode
        logger.info(f"Modalità override da CLI: {args.mode.upper()}")

    # Verifica chiavi API
    if not check_api_keys(config):
        sys.exit(1)

    # Importa e avvia il bot
    try:
        from bot.engine import TradingEngine

        engine = TradingEngine.__new__(TradingEngine)
        engine.config = config

        # Crea directory necessarie
        for dir_path in ['data', 'data/historical', 'models', 'logs', 'backtester/reports']:
            Path(dir_path).mkdir(parents=True, exist_ok=True)

        # Inizializza il motore
        engine.__init__(args.config)

        # Avvia
        logger.info("Avvio loop di trading...")
        engine.start()

    except ImportError as e:
        logger.error(f"Errore import: {e}")
        logger.error("Esegui prima: pip install -r requirements.txt")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Bot fermato dall'utente")
    except Exception as e:
        logger.error(f"Errore fatale: {e}", exc_info=True)
        sys.exit(1)


def run_backtest(args):
    """Avvia il backtesting engine."""
    config = load_config(args.config)
    logger = setup_logging(config)

    logger.info("=" * 60)
    logger.info("BACKTESTING ENGINE - AVVIO")
    logger.info("=" * 60)

    if not check_api_keys(config):
        sys.exit(1)

    try:
        from bot.broker import BrokerClient
        from backtester.engine import BacktestEngine

        logger.info("Connessione ad Alpaca per recupero dati storici...")
        broker = BrokerClient(config)

        backtest = BacktestEngine(config, broker)

        # Simboli da testare
        symbols = None
        if args.symbols:
            symbols = args.symbols.split(',')

        logger.info("Avvio backtest su dati storici...")
        results = backtest.run_full_backtest(symbols)

        logger.info("Backtest completato! Report salvato in backtester/reports/")

        # Stampa riepilogo
        print("\n" + "=" * 60)
        print("RISULTATI BACKTEST")
        print("=" * 60)
        for symbol, strategies in results.items():
            for strategy, result in strategies.items():
                if hasattr(result, 'metrics') and result.metrics:
                    m = result.metrics
                    print(f"\n{symbol} - {strategy.upper()}:")
                    print(f"  Return: {m.get('total_return_pct', 0):.2%}")
                    print(f"  Win Rate: {m.get('win_rate', 0):.1%}")
                    print(f"  Sharpe: {m.get('sharpe_ratio', 0):.2f}")
                    print(f"  Max DD: {m.get('max_drawdown', 0):.1%}")
                    print(f"  Profit Factor: {m.get('profit_factor', 0):.2f}")
                    print(f"  Trade: {m.get('total_trades', 0)}")

    except Exception as e:
        logger.error(f"Errore backtest: {e}", exc_info=True)
        sys.exit(1)


def run_dashboard(args):
    """Avvia la dashboard Streamlit."""
    import subprocess
    import webbrowser
    import time

    print("Avvio dashboard su http://localhost:8501...")

    config = load_config(args.config)
    port = config.get('dashboard', {}).get('port', 8501)

    # Avvia Streamlit
    cmd = [
        sys.executable, '-m', 'streamlit', 'run',
        'dashboard/app.py',
        f'--server.port={port}',
        '--server.headless=false',
        '--browser.gatherUsageStats=false'
    ]

    try:
        time.sleep(2)
        webbrowser.open(f"http://localhost:{port}")
        subprocess.run(cmd)
    except KeyboardInterrupt:
        print("\nDashboard fermata")


def train_ml(args):
    """Addestra il modello ML."""
    config = load_config(args.config)
    logger = setup_logging(config)

    logger.info("Avvio training modello ML...")

    if not check_api_keys(config):
        sys.exit(1)

    try:
        from bot.broker import BrokerClient
        from bot.database import DatabaseManager
        from bot.ml_filter import MLFilter

        broker = BrokerClient(config)
        db_path = config.get('database', {}).get('path', 'data/trades.db')
        db = DatabaseManager(db_path)
        ml = MLFilter(config, db)

        # Simboli per training
        symbols = []
        assets = config.get('assets', {})
        for cat in ['etf', 'stocks', 'crypto']:
            if assets.get(cat, {}).get('enabled', True):
                symbols.extend(assets[cat].get('symbols', []))

        metrics = ml.train(broker, symbols)

        if metrics.get('success'):
            print(f"\n[OK] Training completato!")
            print(f"   Accuracy: {metrics.get('accuracy', 0):.2%}")
            print(f"   Campioni: {metrics.get('train_samples', 0)}")
            if metrics.get('top_features'):
                print(f"   Top features: {', '.join([f[0] for f in metrics['top_features'][:3]])}")
        else:
            print(f"\n[ERRORE] Training fallito: {metrics.get('reason')}")

    except Exception as e:
        logger.error(f"Errore training ML: {e}", exc_info=True)
        sys.exit(1)


def check_status(args):
    """Mostra lo stato del bot."""
    config = load_config(args.config)

    mode = config.get('trading', {}).get('mode', 'paper')
    capital = config.get('trading', {}).get('capital_eur', 500)

    print("\n" + "=" * 50)
    print("TRADING BOT - STATUS")
    print("=" * 50)
    print(f"Modalità: {mode.upper()}")
    print(f"Capitale: EUR {capital} (~ ${capital * 1.09:.0f})")
    s1 = "ON" if config.get('strategy_confluence', {}).get('enabled') else "OFF"
    s2 = "ON" if config.get('strategy_breakout', {}).get('enabled') else "OFF"
    s3 = "ON" if config.get('strategy_sentiment', {}).get('enabled') else "OFF"
    print(f"Strategie: Confluence={s1} | Breakout={s2} | Sentiment={s3}")

    # Controlla il database
    db_path = config.get('database', {}).get('path', 'data/trades.db')
    if Path(db_path).exists():
        from bot.database import DatabaseManager
        db = DatabaseManager(db_path)
        metrics = db.get_performance_metrics()
        if metrics:
            print(f"\nPerformance Totale:")
            print(f"  Trade: {metrics.get('total_trades', 0)}")
            print(f"  P&L: ${metrics.get('total_pnl', 0):.2f}")
            print(f"  Win Rate: {metrics.get('win_rate', 0):.1%}")
    else:
        print("\nNessun dato nel database (bot non ancora avviato)")

    print("=" * 50)


# ============================================================
# MAIN
# ============================================================

def main():
    """Punto di entrata principale."""
    parser = argparse.ArgumentParser(
        description='Trading Bot Algoritmico - Alpaca Markets',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Esempi:
  python main.py bot                    # Avvia il bot (paper trading)
  python main.py bot --mode live        # Avvia in live trading
  python main.py dashboard              # Apre la dashboard
  python main.py backtest               # Esegui backtesting
  python main.py backtest --symbols SPY,AAPL  # Backtest su simboli specifici
  python main.py train-ml               # Addestra il modello ML
  python main.py status                 # Mostra stato e performance
        """
    )

    parser.add_argument(
        '--config',
        default='config.yaml',
        help='Percorso del file di configurazione (default: config.yaml)'
    )

    subparsers = parser.add_subparsers(dest='command', help='Comando da eseguire')

    # Comando: bot
    bot_parser = subparsers.add_parser('bot', help='Avvia il trading bot')
    bot_parser.add_argument('--mode', choices=['paper', 'live'], help='Override modalità')

    # Comando: dashboard
    dash_parser = subparsers.add_parser('dashboard', help='Avvia la dashboard Streamlit')

    # Comando: backtest
    bt_parser = subparsers.add_parser('backtest', help='Esegui backtesting')
    bt_parser.add_argument('--symbols', help='Simboli separati da virgola (es. SPY,AAPL)')

    # Comando: train-ml
    ml_parser = subparsers.add_parser('train-ml', help='Addestra il modello ML')

    # Comando: status
    status_parser = subparsers.add_parser('status', help='Mostra stato e performance')

    args = parser.parse_args()

    if args.command == 'bot':
        run_bot(args)
    elif args.command == 'dashboard':
        run_dashboard(args)
    elif args.command == 'backtest':
        run_backtest(args)
    elif args.command == 'train-ml':
        train_ml(args)
    elif args.command == 'status':
        check_status(args)
    else:
        # Se nessun comando specificato, mostra help
        parser.print_help()
        print("\nPer iniziare:")
        print("   1. Configura le API keys in config.yaml")
        print("   2. python main.py bot        (avvia in paper trading)")
        print("   3. python main.py dashboard  (apri dashboard)")


if __name__ == "__main__":
    main()
