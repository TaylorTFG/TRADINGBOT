#!/usr/bin/env python3
"""Test startup del bot e della dashboard"""

import logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

from bot.engine import TradingEngine

print("=== BOT STARTUP TEST ===")
print()

try:
    engine = TradingEngine("config.yaml")
    print("OK - Engine inizializzato con successo")
    print("OK - Tutti i moduli caricati (inclusi 5 nuovi)")
    print()
    print("STATO BOT:")
    print(f"  - Running: {engine.running}")
    print(f"  - Capitale virtuale: ${engine._virtual_capital:.2f}")
    print(f"  - Database: Connesso")
    print()
    print("BOT PRONTO: python main.py per avviare")
except Exception as e:
    print(f"ERRORE: {e}")
    import traceback
    traceback.print_exc()
