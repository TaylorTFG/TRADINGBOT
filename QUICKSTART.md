# 🚀 QUICK START - Trading Bot

## 5 Passi per Iniziare

### Passo 1: Installa le Dipendenze
Fai doppio click su **`install.bat`**

Oppure da terminale:
```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

---

### Passo 2: Crea le API Keys Alpaca

1. Vai su [https://app.alpaca.markets/](https://app.alpaca.markets/)
2. Registrati gratuitamente
3. Vai su **Paper Trading** → **API Keys**
4. Clicca **"Generate New Key"**
5. Copia **API Key** e **API Secret**

> ⚠️ Il paper trading usa **dati reali ma soldi finti** - perfetto per iniziare!

---

### Passo 3: Configura il Bot

Apri **`config.yaml`** con un editor di testo e inserisci:

```yaml
alpaca:
  paper:
    api_key: "PKxxxxxxxxxxxxxxxxxx"    # ← La tua chiave
    api_secret: "xxxxxxxxxxxxxxxxxxxxxxxx"  # ← Il tuo secret
```

**(Opzionale)** Configura Telegram per ricevere notifiche:
1. Scrivi a [@BotFather](https://t.me/BotFather) su Telegram
2. Crea un nuovo bot con `/newbot`
3. Copia il token e inseriscilo in config.yaml
4. Scrivi `/start` al tuo bot e ottieni il chat_id

```yaml
telegram:
  enabled: true
  bot_token: "1234567890:AAxxxxxxxxxxxxxxxxxxxxxxxxxx"
  chat_id: "123456789"
```

---

### Passo 4: Avvia il Bot

Fai doppio click su **`start_bot.bat`**

Oppure da terminale:
```bash
venv\Scripts\activate
python main.py bot
```

---

### Passo 5: Apri la Dashboard

Fai doppio click su **`start_dashboard.bat`**

O visita: **[http://localhost:8501](http://localhost:8501)**

---

## Comandi Utili

```bash
# Avvia bot (paper trading - DEFAULT)
python main.py bot

# Avvia dashboard
python main.py dashboard

# Esegui backtest su 3 anni di dati
python main.py backtest

# Backtest su simboli specifici
python main.py backtest --symbols SPY,AAPL,NVDA

# Addestra il modello ML manualmente
python main.py train-ml

# Vedi statistiche e performance
python main.py status
```

---

## FAQ

**Q: Il bot può perdere soldi?**
A: In modalità paper trading NO (dati reali, soldi finti). In live trading sì.

**Q: Quanto capitale minimo serve?**
A: La configurazione default è €500. Alpaca non ha un minimo per il paper trading.

**Q: Il bot opera 24/7?**
A: Opera nelle finestre orarie configurate (apertura mercati USA, ore italiane).
   Per gli asset crypto opera anche fuori orario.

**Q: Come passo al live trading?**
A: Dalla dashboard → Configurazione → Switch Paper → Live.
   Dopo 30 giorni profittevoli in paper, il bot invia una notifica di suggerimento.

**Q: Come installo Python?**
A: Scarica da [python.org](https://www.python.org/downloads/).
   Seleziona "Add Python to PATH" durante l'installazione.

---

## Struttura File Principali

| File | Descrizione |
|------|-------------|
| `config.yaml` | ⚙️ Tutte le impostazioni |
| `start_bot.bat` | ▶️ Avvia il bot |
| `start_dashboard.bat` | 📊 Apri la dashboard |
| `install.bat` | 📦 Installa dipendenze |
| `logs/` | 📋 File di log giornalieri |
| `data/trades.db` | 💾 Database dei trade |
| `backtester/reports/` | 📈 Report backtest HTML |

---

## Supporto

Per problemi o domande, consulta i log in `logs/trading_YYYY-MM-DD.log`.

Livello log configurabile in `config.yaml`:
```yaml
logging:
  level: "DEBUG"  # Più dettagliato per debug
```
