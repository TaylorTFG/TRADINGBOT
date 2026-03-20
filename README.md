# 📈 Trading Bot Algoritmico - Alpaca Markets

Bot di trading automatico professionale con analisi tecnica multi-strategia,
Machine Learning, sentiment delle notizie e dashboard in tempo reale.

## Caratteristiche Principali

### 🎯 3 Strategie Combinate
1. **Multi-Indicator Confluence** - RSI, MACD, Bollinger, EMA, Volume (soglia 3/5)
2. **Breakout + Momentum** - Rottura livelli chiave con ADX e ATR dinamici
3. **News Sentiment** - Analisi NLP con VADER su NewsAPI e RSS feed

### 🗳️ Sistema di Voto Meta-Strategy
- 3/3 concordano → entrata con size massima (2% capitale)
- 2/3 concordano → entrata con size ridotta (1% capitale)
- <2 voti → nessuna operazione

### 🤖 Machine Learning Filter
- Random Forest Classifier (scikit-learn)
- 20+ features tecniche + sentiment + temporali
- Training automatico ogni domenica
- Confidence minima: 65%

### 🛡️ Risk Management Completo
- Stop loss: -1.5% dal prezzo di entrata
- Trailing stop: attivazione a +1%, distanza 0.8%
- Take profit: +3%
- Perdita giornaliera max: -5% → bot si ferma
- Perdita settimanale max: -10% → pausa 2 giorni

### 📊 Dashboard Streamlit
- Equity curve in tempo reale
- Trade aperti con P&L live
- Storico completo con export CSV
- Analisi per strategia e heatmap oraria
- Pannello configurazione grafico

### 🔔 Notifiche Telegram
- Trade aperto/chiuso in tempo reale
- Alert stop loss
- Report giornaliero ore 22:30
- Report settimanale venerdì sera

## Asset Supportati

| Tipo | Simboli | Note |
|------|---------|------|
| ETF Indici | SPY, QQQ, IWM | Alta liquidità, stabile |
| Azioni USA | AAPL, MSFT, NVDA, TSLA, AMZN | Alta liquidità |
| Crypto | BTC/USD, ETH/USD | 24/7, alta volatilità |

## Installazione Rapida

```bash
# 1. Clona il repository
git clone https://github.com/TaylorTFG/TRADING-TAYLOR.git
cd TRADING-TAYLOR

# 2. Installa dipendenze (oppure usa install.bat)
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt

# 3. Configura le API keys
# Apri config.yaml e inserisci le credenziali Alpaca

# 4. Avvia il bot
python main.py bot
```

Vedi **[QUICKSTART.md](QUICKSTART.md)** per istruzioni dettagliate.

## Struttura del Progetto

```
TRADING BOT/
├── main.py                    ← Entry point
├── config.yaml                ← Configurazione (da editare)
├── requirements.txt           ← Dipendenze Python
├── QUICKSTART.md              ← Guida rapida
├── install.bat                ← Installa tutto automaticamente
├── start_bot.bat              ← Avvia il bot
├── start_dashboard.bat        ← Apri dashboard
├── bot/
│   ├── engine.py              ← Loop principale
│   ├── broker.py              ← API Alpaca
│   ├── strategy_confluence.py ← Strategia 1
│   ├── strategy_breakout.py   ← Strategia 2
│   ├── strategy_sentiment.py  ← Strategia 3
│   ├── meta_strategy.py       ← Sistema voto
│   ├── ml_filter.py           ← Random Forest
│   ├── risk_manager.py        ← Gestione rischio
│   ├── news_analyzer.py       ← NLP notizie
│   ├── market_context.py      ← VIX, macro
│   ├── notifications.py       ← Telegram
│   └── database.py            ← SQLite
├── dashboard/
│   └── app.py                 ← Streamlit UI
├── backtester/
│   └── engine.py              ← Backtesting
├── data/
│   └── trades.db              ← Database
├── models/
│   └── ml_model.pkl           ← Modello ML
└── logs/
    └── trading_*.log          ← Log giornalieri
```

## Configurazione

Il file `config.yaml` contiene tutti i parametri configurabili:

```yaml
trading:
  mode: "paper"          # "paper" o "live"
  capital_eur: 500       # Capitale iniziale

alpaca:
  paper:
    api_key: "YOUR_KEY"
    api_secret: "YOUR_SECRET"

risk_management:
  stop_loss_pct: 0.015   # -1.5%
  take_profit_pct: 0.03  # +3%
  max_risk_per_trade: 0.02  # 2% per trade
```

## ⚠️ Disclaimer

**Questo software è fornito a scopo educativo e non costituisce consulenza finanziaria.**

Il trading algoritmico comporta rischi significativi di perdita del capitale.
Testa sempre in modalità **paper trading** prima di usare denaro reale.
Le performance passate non garantiscono risultati futuri.

---

**Linguaggio:** Python 3.11+ | **Broker:** Alpaca Markets | **Dashboard:** Streamlit
