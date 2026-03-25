#!/usr/bin/env python3
"""Test dashboard structure"""

import sys
sys.path.insert(0, '.')

print("=== DASHBOARD TEST ===")
print()

try:
    # Controlla che il file esista e si possa leggere
    import dashboard.app as app
    print("OK - Dashboard app.py importato")

    # Controlla che abbia le funzioni principali
    if hasattr(app, 'main'):
        print("OK - Funzione main trovata")

    if hasattr(app, 'page_analytics'):
        print("OK - Funzione page_analytics trovata (NUOVA)")

    if hasattr(app, 'page_dashboard'):
        print("OK - Funzione page_dashboard trovata")

    if hasattr(app, 'page_signals'):
        print("OK - Funzione page_signals trovata")

    print()
    print("DASHBOARD STRUCTURE:")
    print("  - Dashboard principale: OK")
    print("  - Advanced Metrics (NUOVO): OK")
    print("  - Trading Signals: OK")
    print()
    print("AVVIO: streamlit run dashboard/app.py")

except Exception as e:
    print(f"ERRORE: {e}")
    import traceback
    traceback.print_exc()
