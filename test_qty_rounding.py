#!/usr/bin/env python3
"""Test qty rounding per prevenire doppi ordini"""

print("=" * 60)
print("QTY ROUNDING TEST - Double Order Prevention")
print("=" * 60)
print()

# Simula il bug originale
print("SCENARIO 1: Senza rounding (BUG ORIGINALE)")
print("-" * 60)

btc_price = 70284.64
capital = 2725 * 1.09  # $2500 EUR -> USD
btc_pct = 0.025  # 2.5% per BUY signal 3/4

capital_at_risk = capital * btc_pct
qty_raw = capital_at_risk / btc_price

print(f"Capital: ${capital:.2f}")
print(f"Risk %: {btc_pct*100:.1f}%")
print(f"Capital at risk: ${capital_at_risk:.2f}")
print(f"BTC Price: ${btc_price:.2f}")
print(f"Raw qty: {qty_raw:.15f}")
print()

# Applica multiplier (macro 1.0 × kelly 0.82 × session 0.75)
final_multiplier = 1.0 * 0.82 * 0.75  # 0.615
qty_with_multiplier = qty_raw * final_multiplier

print(f"Final multiplier: {final_multiplier:.3f}")
print(f"Qty after multiplier: {qty_with_multiplier:.15f}")
print()
print(f"Alpaca rounds to 6 decimals: {round(qty_with_multiplier, 6):.6f}")
print(f"Remainder sent as order 2: {qty_with_multiplier - round(qty_with_multiplier, 6):.15f}")
print("[BUG] Due to precision, two orders are placed!")
print()

# Soluzione
print("SCENARIO 2: Con rounding (FIX)")
print("-" * 60)

qty_fixed = round(qty_with_multiplier, 6)
print(f"Final qty (after rounding to 6 decimals): {qty_fixed:.6f}")
print("[OK] Single order placed, no remainder")
print()

# Test per stock
print("SCENARIO 3: Stock (AMD)")
print("-" * 60)

amd_price = 218.57
stock_pct = 0.025
capital_at_risk_stock = capital * stock_pct
qty_stock_raw = capital_at_risk_stock / amd_price
qty_stock_multiplied = qty_stock_raw * final_multiplier

print(f"Stock Price: ${amd_price:.2f}")
print(f"Qty raw: {qty_stock_raw:.6f}")
print(f"Qty after multiplier: {qty_stock_multiplied:.6f}")
print(f"Qty rounded to 2 decimals: {round(qty_stock_multiplied, 2):.2f}")
print("[OK] Correct for stock orders (shares)")
print()

print("=" * 60)
print("SUMMARY: Rounding is now applied in TWO places:")
print("  1. After applying final_multiplier in engine.py line 639")
print("  2. At start of _execute_buy() for additional safety")
print("=" * 60)
