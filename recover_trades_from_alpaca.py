#!/usr/bin/env python3
"""Recupera i trade eseguiti da Alpaca e li salva nel database locale"""

import yaml
from bot.broker import BrokerClient
from bot.database import DatabaseManager
from datetime import datetime, timedelta

# Carica config
with open('config.yaml', 'r') as f:
    config = yaml.safe_load(f)

broker = BrokerClient(config)
db = DatabaseManager()

print("=" * 60)
print("RECUPERO TRADE DA ALPACA")
print("=" * 60)
print()

try:
    print("Recupero ordini da Alpaca...")

    # Recupera gli ordini eseguiti da Alpaca
    from alpaca.trading.requests import GetOrdersRequest
    from alpaca.trading.enums import QueryOrderStatus

    orders = broker.trading_client.get_orders(GetOrdersRequest(
        status='closed',  # Solo ordini chiusi
        limit=100,  # Ultimi 100 ordini
        nested=True  # Include dettagli completi
    )

    if not orders:
        print("Nessun ordine trovato su Alpaca")
    else:
        recovered_count = 0
        all_trades = db.get_trade_history(limit=500)
        existing_order_ids = [t.get('alpaca_order_id') for t in all_trades if t.get('alpaca_order_id')]

        print(f"Found {len(orders)} ordini su Alpaca")
        print(f"Database ha {len(all_trades)} trade")
        print()

        for order in orders:
            # Se l'ordine è già nel database, salta
            if order.id in existing_order_ids:
                continue

            # Estrai i dati principali
            symbol = order.symbol
            side = order.side.lower()  # 'buy' o 'sell'
            qty = float(order.qty)
            filled_price = float(order.filled_avg_price) if order.filled_avg_price else 0
            entry_time = order.created_at.isoformat() if order.created_at else datetime.now().isoformat()

            if filled_price > 0:
                # Salva il trade nel database
                trade_id = db.insert_trade({
                    'symbol': symbol,
                    'side': side,
                    'quantity': qty,
                    'entry_price': filled_price,
                    'entry_time': entry_time,
                    'entry_reason': f'Recovered from Alpaca | Order {order.id}',
                    'alpaca_order_id': order.id,
                    'strategy': 'unknown',
                })

                recovered_count += 1
                print(f"✓ {symbol} {side.upper():5} x{qty:8.4f} @ ${filled_price:10.2f} | {entry_time[:10]}")

        print()
        print(f"✓ Total: {recovered_count} trade recuperati da Alpaca")

except Exception as e:
    print(f"Errore: {e}")
    import traceback
    traceback.print_exc()
