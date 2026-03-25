#!/usr/bin/env python3
"""Check ETH/USD P&L"""

import yaml
from bot.broker import BrokerClient
from bot.database import DatabaseManager

# Carica config
with open('config.yaml', 'r') as f:
    config = yaml.safe_load(f)

broker = BrokerClient(config)
db = DatabaseManager()

# Prendi prezzo corrente
try:
    last_price = broker.get_latest_price('ETH/USD')
except Exception as e:
    print(f"Errore: {e}")
    import sys
    sys.exit(1)

# Prendi posizione dal database
open_trades = db.get_open_trades()
eth_trade = None
for trade in open_trades:
    if trade['symbol'] == 'ETH/USD':
        eth_trade = trade
        break

if not eth_trade:
    print("Nessuna posizione aperta su ETH/USD")
else:
    entry_price = eth_trade['entry_price']
    pnl = (last_price - entry_price)
    pnl_pct = (pnl / entry_price) * 100

    print("=" * 50)
    print("POSIZIONE ETH/USD")
    print("=" * 50)
    print()
    print(f"Entry Price:    ${entry_price:.2f}")
    print(f"Current Price:  ${last_price:.2f}")
    print(f"Variazione:     ${pnl:+.2f} ({pnl_pct:+.2f}%)")
    print()
    if pnl > 0:
        print("✓ IN PROFITTO")
    elif pnl < 0:
        print("✗ IN PERDITA")
    else:
        print("= PAREGGIO")
    print()
    print(f"Entry Time: {eth_trade.get('entry_time', 'N/A')}")
    print(f"Side: {eth_trade.get('side', 'BUY')}")
