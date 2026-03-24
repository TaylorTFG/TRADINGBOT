# Deploy su Render

## Prerequisiti

1. Account Render (https://render.com)
2. Repository GitHub (git push completato)
3. Credenziali Alpaca (API key + secret)

## Opzione 1: Deploy Dashboard Only (Consigliato per Testing)

### Step 1: Crea il servizio su Render

1. Vai su https://dashboard.render.com
2. Clicca "New +" → "Web Service"
3. Connetti il repository GitHub
4. Configurazione:
   - **Name**: `scalping-bot-dashboard`
   - **Environment**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**:
     ```
     streamlit run dashboard/app.py --server.port=8501 --server.address=0.0.0.0
     ```
   - **Plan**: Free (sufficie per il testing)

### Step 2: Configura variabili di ambiente

Nel panel Render, aggiungi le seguenti Environment Variables:

```
STREAMLIT_SERVER_HEADLESS=true
STREAMLIT_SERVER_ENABLECORS=false
PYTHONUNBUFFERED=1
ALPACA_API_KEY=YOUR_PAPER_KEY
ALPACA_API_SECRET=YOUR_PAPER_SECRET
```

### Step 3: Deploy

Clicca "Create Web Service" e attendi il deploy (2-3 minuti).

La dashboard sarà disponibile a: `https://scalping-bot-dashboard.onrender.com`

---

## Opzione 2: Deploy Bot Engine + Dashboard (Full Stack)

### Step 1: Database Persistente

Per il bot H24 ti serve un database persistente. Opzioni:

**A. PostgreSQL su Render** (gratuito)
```bash
1. Crea servizio "PostgreSQL"
2. Copia connection string
3. Modifica config.yaml per usare PostgreSQL
```

**B. Mantieni SQLite + Web Service**
```bash
1. Il bot crea data/trades.db in memoria
2. Ad ogni riavvio perde i dati
3. Usa solo per testing breve
```

### Step 2: Crea 2 servizi su Render

**Servizio 1: Dashboard Web**
- Build Command: `pip install -r requirements.txt`
- Start Command: `streamlit run dashboard/app.py --server.port=8501 --server.address=0.0.0.0`
- Plan: Free
- **Espone**: Dashboard su porta 8501

**Servizio 2: Bot Engine** (Background Worker)
- Build Command: `pip install -r requirements.txt`
- Start Command: `python main.py`
- Plan: Free
- **Ruota in background**: esegue il trading bot H24

### Step 3: Configurazione Ambiente

Aggiungi a entrambi i servizi:

```
PYTHONUNBUFFERED=1
ALPACA_API_KEY=YOUR_PAPER_KEY
ALPACA_API_SECRET=YOUR_PAPER_SECRET
TRADING_MODE=paper
```

---

## Monitoraggio su Render

### Logs

- Dashboard: Menu Logs accanto a "Logs"
- Bot Engine: Menu Logs accanto a "Logs"

Verifica che il bot stia inviando segnali:
```
[BTC/USD] EMA Crossover: BUY ...
[ETH/USD] Bollinger Squeeze: SELL ...
```

### Uptime & Cost

- **Free plan**: Servizio si "sospende" dopo 15 min di inattività
  - Dashboard: si riattiva con nuova richiesta
  - Bot: RIMANE SOSPESO (non ideale!)

**Consiglio**: Usa **Free plan** solo per testing breve. Per bot H24 24/7 usa **Starter Plan** ($7/mese).

---

## Troubleshooting

### Dashboard non carica
```
1. Verifica logs: https://dashboard.render.com → Select Service → Logs
2. Controlla se database esiste: data/trades.db
3. Riavvia servizio: Menu → Restart
```

### Bot non fa trading
```
1. Verifica credenziali Alpaca in Environment Variables
2. Controlla connessione: Bot logs → "CONNECTED TO ALPACA"
3. Verifica che il capitale sia >= $500
4. Controlla orario: H24 deve funzionare sempre
```

### Database non persiste
```
Se usi Free Plan + SQLite:
- Ogni riavvio cancella data/trades.db
- Soluzione: PostgreSQL su Render (free)
```

---

## Configurazione Bot per Render

### File config.yaml

Assicurati che sia corretto prima del push:

```yaml
trading:
  mode: "paper"          # ✅ Sempre "paper" fino a testing completato
  capital_eur: 500

alpaca:
  paper:
    api_key: "USE_ENV_VAR"    # Legge da ALPACA_API_KEY
    api_secret: "USE_ENV_VAR" # Legge da ALPACA_API_SECRET
```

### Modifica main.py se necessario

Se il bot non legge le env vars, modifica `main.py`:

```python
import os

api_key = os.getenv("ALPACA_API_KEY") or config["alpaca"]["paper"]["api_key"]
api_secret = os.getenv("ALPACA_API_SECRET") or config["alpaca"]["paper"]["api_secret"]
```

---

## Monitoraggio Notifiche Telegram

Il bot invia notifiche a Telegram (configura TELEGRAM_BOT_TOKEN):

```
✅ BTC/USD +$4.20 (+0.8%) | EMA Cross
🛑 ETH/USD -$2.60 (-0.5%) | cooldown 2min
⚡ SOL/USD $95.20 | SL $94.62 | TP $95.96 | 2/3 voti
```

Configura in config.yaml:
```yaml
telegram:
  enabled: true
  bot_token: "YOUR_TELEGRAM_BOT_TOKEN"
  chat_id: "YOUR_CHAT_ID"
```

---

## Performance Attese

Con Free Plan Render:
- **Dashboard**: 1-2 sec per carico pagina
- **Bot**: Ciclo 15sec può rallentare a 30-45sec
- **Uptime**: ~99% (sospensione dopo 15 min inattività sul free)

Per ottimale: Upgrade a **Starter Plan** ($7/mese per 2 servizi)

---

## Pro Tips

1. **Auto-Deploy da GitHub**: Render auto-deploya su ogni push
2. **Test Locale Prima**: `streamlit run dashboard/app.py`
3. **Monitora Costs**: Free plan è gratis ma con limitazioni
4. **Backup Database**: Scarica regolarmente `data/trades.db`
5. **Update Config**: Modifica `config.yaml` e pusha → Render redeploya automaticamente
