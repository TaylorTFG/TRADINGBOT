# ⚡ Crypto Scalping Bot H24 - Alpaca Paper Trading

Trading bot automatico per **scalping veloce** su BTC/USD, ETH/USD, SOL/USD con Alpaca paper trading.

- **Capitale**: €500 ($545 USD)
- **Asset**: Crypto only (H24 trading)
- **Ciclo**: 15 secondi
- **Risk**: SL 0.5%, TP 0.8%, max 50 trade/giorno
- **Dashboard**: Streamlit (monitoraggio real-time)

---

## ⚡ Caratteristiche Principali

### 🎯 3 Strategie Scalping (Timeframe 1min)

1. **EMA Crossover** - EMA 5×13×50 + RSI(7) + ATR + Volume >120%
2. **Bollinger Squeeze** - Squeeze detection + breakout + mean reversion
3. **VWAP Momentum** - VWAP 1min + MACD(5,13,5) + proximity filter

### 🗳️ Sistema di Voto Intelligente
- **3/3 concordano** → BUY/SELL con size piena (2% capitale)
- **2/3 concordano** → BUY/SELL con size ridotta (1% capitale)
- **Filtro Trend 5min** → Blocca BUY se trend bear, SELL se bull

### 🛡️ Risk Management Aggressivo (Scalping)
- **Stop Loss**: -0.5% (strettissimo)
- **Take Profit**: +0.8% (piccoli guadagni frequenti, ratio 1:1.6)
- **Trailing Stop**: activation +0.4%, distance 0.25%
- **Position Timeout**: 15 minuti (chiude forzato)
- **Post-SL Cooldown**: 2 minuti
- **Daily Loss**: -3% → stop trading
- **Daily Target**: +2% → size -50%
- **Max Trades**: 50/giorno
- **Max Open**: 2 posizioni

### 📊 Dashboard Streamlit
- **Overview**: Bot status, contatori trade, posizioni aperte con countdown timeout
- **Configuration**: Tutti i parametri scalping (EMA, BB, VWAP, risk)
- **Performance 6H**: P&L timeline, win rate, tabella trade chiusi

### 🔔 Notifiche Telegram (Compatte)
```
⚡ BUY BTC/USD $84,230 | SL $83,809 | TP $84,903 | 2/3 voti
✅ BTC/USD +$4.20 (+0.8%) | 8min | EMA Cross
🛑 BTC/USD -$2.60 (-0.5%) | cooldown 2min
⏱️ ETH/USD timeout | +$0.80 (+0.15%)
```

---

## 🚀 Quick Start

### 1. Installazione
```bash
git clone https://github.com/TaylorTFG/TRADING-TAYLOR.git
cd TRADING-TAYLOR

pip install -r requirements.txt

# Configura config.yaml con credenziali Alpaca (paper)
```

### 2. Avvia Locale
```bash
# Terminal 1: Bot
python main.py

# Terminal 2: Dashboard (http://localhost:8501)
streamlit run dashboard/app.py
```

### 3. Deploy Render (Free)
Vedi **[DEPLOY.md](DEPLOY.md)** per guida completa.

```bash
# Basta pushare, Render redeploya automaticamente
git push origin master
```

---

## 📁 Struttura del Progetto

```
TRADING-TAYLOR/
├── config.yaml                ← Parametri scalping (SL, TP, EMA, BB)
├── requirements.txt           ← Dipendenze Python
├── DEPLOY.md                  ← Guida deploy Render
├── render.yaml                ← Configurazione Render
├── main.py                    ← Entry point
│
├── bot/
│   ├── engine.py              ← Loop 15sec, H24, timeout, trade counter
│   ├── broker.py              ← Client Alpaca
│   ├── database.py            ← SQLite trades
│   ├── risk_manager.py        ← SL/TP/timeout/cooldown/daily limits
│   ├── notifications.py       ← Telegram alerts
│   ├── meta_strategy.py       ← Sistema voto + filtro trend 5min
│   ├── strategy_confluence.py ← EMA Crossover (5/13/50 + RSI 7)
│   ├── strategy_breakout.py   ← Bollinger Squeeze (20,2)
│   ├── strategy_sentiment.py  ← VWAP Momentum
│   ├── market_context.py      ← VIX, macro context
│   ├── ml_filter.py           ← Disabilitato
│   └── news_analyzer.py       ← Disabilitato (return score 0)
│
├── dashboard/
│   └── app.py                 ← Streamlit (Overview, Config, Performance)
│
├── data/
│   ├── trades.db              ← SQLite (auto-created)
│   ├── virtual_capital.json   ← Capitale aggiornato
│   └── bot_status.json        ← Status JSON
│
└── logs/
    └── trading_bot.log        ← Log file
```

---

## ⚙️ Configurazione Scalping

Il file `config.yaml` contiene tutti i parametri:

```yaml
trading:
  mode: "paper"                    # Always "paper" for testing
  capital_eur: 500
  max_open_positions: 2
  cycle_interval_seconds: 15       # 15 secondi (non 30)

assets:
  crypto:
    symbols: ["BTC/USD", "ETH/USD", "SOL/USD"]

risk_management:
  stop_loss_pct: 0.005            # -0.5%
  take_profit_pct: 0.008          # +0.8%
  trailing_stop:
    activation_pct: 0.004         # +0.4%
    trail_pct: 0.0025             # 0.25%
  daily:
    max_loss_pct: 0.03            # -3% stop
    target_profit_pct: 0.02       # +2% size -50%
    max_trades: 50
  quality_filters:
    max_position_duration_min: 15
    cooldown_after_loss_sec: 120

ml_filter: { enabled: false }      # Disabilitato (troppo lento)
```

---

## 📊 Performance Attese

| Metrica | Valore | Note |
|---------|--------|------|
| Win Rate | 50-60% | Piccoli guadagni frequenti |
| Avg Trade Duration | 5-10 min | Veloce scalping |
| Avg Win | +$0.60-1.20 | Su $545 capitale |
| Avg Loss | -$0.30-0.80 | Controllato da SL |
| Daily Target | +$11 | +2% su $545 |
| Max Daily Loss | -$16.35 | -3%, then stop |

---

## 🔍 Monitoraggio

### Dashboard (Locale)
```bash
streamlit run dashboard/app.py
# Apri http://localhost:8501
```

### Log File
```bash
tail -f logs/trading_bot.log
```

### Render (Cloud)
1. Vai https://dashboard.render.com
2. Seleziona servizio
3. Menu Logs
4. Verifica segnali EMA/BB/VWAP

### Telegram Alerts
Configura `telegram.bot_token` e `chat_id` in config.yaml per ricevere alert real-time.

---

## 🐛 Troubleshooting

**Bot non fa trade**
- Controlla credenziali Alpaca in config.yaml
- Verifica log: "CONNECTED TO ALPACA"
- Check capitale: min $500 richiesto

**Dashboard non carica**
- Controlla database: `ls data/trades.db`
- Verifica porta 8501: `lsof -i :8501`
- Clear cache: `rm -rf ~/.streamlit/`

**Performance lenta su Render**
- Free Plan ha limiti (sospensione dopo 15 min inattività)
- Upgrade a Starter Plan ($7/mese) per H24 stabile

---

## ⚠️ Disclaimer

**Questo software è fornito a scopo educativo SOLO.**

❌ **NON** usare con denaro reale finché non hai:
1. Testato almeno 30 giorni in paper
2. Win rate consistently > 50%
3. Daily loss never > -3%
4. Daily profit consistently > +1%

Il trading comporta rischi di perdita totale del capitale.
Le performance passate non garantiscono risultati futuri.

---

**Tech Stack**: Python 3.11+ | **Broker**: Alpaca Markets | **Dashboard**: Streamlit | **Cloud**: Render

**Last Updated**: 2026-03-24 | **Version**: 2.0 (Crypto Scalping H24)
