# ============================================================
# DASHBOARD STREAMLIT - TRADING BOT
# Interfaccia grafica completa su http://localhost:8501
# Pagine: Overview, Trade in Corso, Storico, Analisi, Config
# ============================================================

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import yaml
import json
import sys
import os
from datetime import datetime, timedelta
from pathlib import Path

# Aggiungi la root al path
sys.path.insert(0, str(Path(__file__).parent.parent))

from bot.database import DatabaseManager
from zoneinfo import ZoneInfo

IT_TZ = ZoneInfo("Europe/Rome")

# ============================================================
# CONFIGURAZIONE PAGINA
# ============================================================

st.set_page_config(
    page_title="Trading Bot Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# CSS personalizzato
st.markdown("""
<style>
    .main { background-color: #0f172a; }
    .metric-card {
        background: #1e293b;
        border-radius: 12px;
        padding: 1.2rem;
        border: 1px solid #334155;
    }
    .profit { color: #22c55e; }
    .loss { color: #ef4444; }
    .neutral { color: #94a3b8; }
    .status-on { color: #22c55e; font-weight: bold; }
    .status-off { color: #ef4444; font-weight: bold; }
    .status-pause { color: #f59e0b; font-weight: bold; }
    div[data-testid="metric-container"] {
        background-color: #1e293b;
        border: 1px solid #334155;
        border-radius: 8px;
        padding: 1rem;
    }
</style>
""", unsafe_allow_html=True)


# ============================================================
# UTILITY FUNCTIONS
# ============================================================

@st.cache_resource
def get_database():
    """Connessione al database (cached per la sessione)."""
    config = load_config()
    db_path = config.get('database', {}).get('path', 'data/trades.db')
    if Path(db_path).exists():
        return DatabaseManager(db_path)
    return None


def load_config():
    """Carica la configurazione dal file yaml."""
    config_path = Path(__file__).parent.parent / 'config.yaml'
    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    return {}


def load_virtual_capital() -> dict:
    """
    Legge il capitale virtuale aggiornato dal bot.
    Restituisce i dati dal file data/virtual_capital.json.
    Se il file non esiste, calcola il valore iniziale dalla config.
    """
    vc_path = Path(__file__).parent.parent / 'data' / 'virtual_capital.json'
    if vc_path.exists():
        try:
            with open(vc_path) as f:
                return json.load(f)
        except Exception:
            pass
    # Fallback: usa il valore da config
    config = load_config()
    capital_eur = config.get('trading', {}).get('capital_eur', 500)
    initial = capital_eur * 1.09
    return {
        'virtual_capital': initial,
        'initial_capital': initial,
        'capital_eur': capital_eur,
        'total_pnl': 0.0,
        'total_pnl_pct': 0.0,
    }


def save_config(config: dict):
    """Salva la configurazione nel file yaml."""
    config_path = Path(__file__).parent.parent / 'config.yaml'
    with open(config_path, 'w', encoding='utf-8') as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)


def format_pnl(value: float) -> str:
    """Formatta il PnL con colori."""
    if value is None:
        return "N/A"
    sign = "+" if value >= 0 else ""
    color = "#22c55e" if value >= 0 else "#ef4444"
    return f'<span style="color:{color};font-weight:bold">{sign}{value:.2f}$</span>'


def format_pct(value: float) -> str:
    """Formatta una percentuale con colori."""
    if value is None:
        return "N/A"
    sign = "+" if value >= 0 else ""
    color = "#22c55e" if value >= 0 else "#ef4444"
    return f'<span style="color:{color}">{sign}{value:.2%}</span>'


def get_bot_status():
    """Legge lo stato del bot dal file di stato."""
    status_file = Path('data/bot_status.json')
    if status_file.exists():
        try:
            with open(status_file, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return {'status': 'unknown', 'mode': 'paper', 'started_at': None}


# ============================================================
# NAVIGAZIONE SIDEBAR
# ============================================================

with st.sidebar:
    st.title("📈 Trading Bot")
    st.caption("Dashboard di controllo")

    config = load_config()
    mode = config.get('trading', {}).get('mode', 'paper')
    mode_color = "🟡" if mode == 'paper' else "🔴"
    st.markdown(f"**Modalità:** {mode_color} {mode.upper()}")

    st.divider()

    page = st.selectbox(
        "Navigazione",
        ["📊 Overview", "📈 Trade in Corso", "📋 Storico Trade",
         "🔬 Analisi Strategie", "⚙️ Configurazione"],
        label_visibility="collapsed"
    )

    st.divider()

    # Refresh automatico
    auto_refresh = st.checkbox("Auto-refresh", value=True)
    if auto_refresh:
        refresh_secs = st.slider("Secondi", 10, 120, 30)
        st.caption(f"Refresh ogni {refresh_secs}s")

    if auto_refresh:
        import time
        placeholder = st.empty()

    st.divider()
    st.caption("Trading Bot v1.0")
    st.caption(f"Ora: {datetime.now(IT_TZ).strftime('%H:%M:%S')}")


db = get_database()


# ============================================================
# PAGINA 1: OVERVIEW
# ============================================================

if "Overview" in page:
    st.title("📊 Overview")

    if db is None:
        st.warning("⚠️ Database non trovato. Avvia prima il bot.")
        st.code("python main.py --mode paper", language="bash")
        st.stop()

    # Status bot
    bot_status = get_bot_status()
    status = bot_status.get('status', 'unknown')

    col_status, col_time = st.columns([1, 2])
    with col_status:
        if status in ('running', 'started'):
            st.markdown('<span class="status-on">● BOT ATTIVO</span>', unsafe_allow_html=True)
        elif status == 'paused':
            st.markdown('<span class="status-pause">⏸ BOT IN PAUSA</span>', unsafe_allow_html=True)
        else:
            st.markdown('<span class="status-off">■ BOT FERMO</span>', unsafe_allow_html=True)

    with col_time:
        if bot_status.get('started_at'):
            st.caption(f"Avviato: {bot_status['started_at']}")

    st.divider()

    # Metriche principali
    metrics = db.get_performance_metrics()
    today_stats = db.get_today_stats()
    daily_history = db.get_daily_stats_history(30)

    # Legge il capitale virtuale aggiornato dal bot (non i $100k Alpaca)
    vc_data = load_virtual_capital()
    current_capital = vc_data.get('virtual_capital', 0)
    initial_capital = vc_data.get('initial_capital', 0)
    capital_eur = vc_data.get('capital_eur', 500)
    total_pnl = vc_data.get('total_pnl', 0)
    total_pnl_pct = vc_data.get('total_pnl_pct', 0)

    # Banner informativo
    eur_equiv = current_capital / 1.09
    st.info(
        f"**Capitale Virtuale:** ${current_capital:.2f} (~€{eur_equiv:.0f}) — "
        f"basato su €{capital_eur} configurati. "
        f"L'account Alpaca ha $100,000 (solo per eseguire gli ordini)."
    )

    # Row 1: Metriche principali
    c1, c2, c3, c4 = st.columns(4)

    with c1:
        delta_color = "normal" if total_pnl_pct >= 0 else "inverse"
        st.metric(
            "💰 Portafoglio Virtuale",
            f"${current_capital:.2f}",
            f"{total_pnl:+.2f}$ ({total_pnl_pct:+.2%})" if total_pnl != 0 else "Nessun trade ancora",
            delta_color=delta_color
        )

    with c2:
        today_pnl = today_stats.get('total_pnl') or 0
        st.metric(
            "📅 P&L Oggi",
            f"${today_pnl:+.2f}" if today_pnl else "$0.00",
            f"{today_stats.get('total_trades', 0)} trade",
        )

    with c3:
        win_rate = metrics.get('win_rate', 0)
        st.metric(
            "🎯 Win Rate",
            f"{win_rate:.1%}" if win_rate else "N/A",
            f"{metrics.get('winning_trades', 0)}W / {metrics.get('losing_trades', 0)}L"
        )

    with c4:
        sharpe = metrics.get('sharpe_ratio', 0)
        st.metric(
            "📐 Sharpe Ratio",
            f"{sharpe:.2f}" if sharpe else "N/A",
            f"Max DD: {metrics.get('max_drawdown', 0):.1%}" if metrics.get('max_drawdown') else None
        )

    st.divider()

    # Row 2: Equity Curve
    if daily_history:
        st.subheader("📈 Equity Curve")
        df_equity = pd.DataFrame(daily_history[::-1])  # Ordine cronologico

        if 'ending_capital' in df_equity.columns and 'date' in df_equity.columns:
            df_equity = df_equity.dropna(subset=['ending_capital'])

            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=df_equity['date'],
                y=df_equity['ending_capital'],
                mode='lines+markers',
                name='Portafoglio',
                line=dict(color='#38bdf8', width=2),
                fill='tonexty',
                fillcolor='rgba(56, 189, 248, 0.1)',
            ))
            fig.add_hline(y=initial_capital, line_dash="dash", line_color="#64748b",
                         annotation_text=f"Capitale iniziale ${initial_capital:.0f}")

            fig.update_layout(
                template='plotly_dark',
                paper_bgcolor='#0f172a',
                plot_bgcolor='#1e293b',
                height=350,
                margin=dict(l=0, r=0, t=0, b=0),
                showlegend=False,
                yaxis_tickformat='$,.0f'
            )
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Equity curve disponibile dopo i primi trade")

    # Row 3: Statistiche aggiuntive
    col_l, col_r = st.columns(2)

    with col_l:
        st.subheader("📊 Metriche Performance")
        if metrics:
            data = {
                'Metrica': ['Trade Totali', 'Trade Vincenti', 'Trade Perdenti',
                           'P&L Totale', 'P&L Medio', 'Profit Factor'],
                'Valore': [
                    metrics.get('total_trades', 0),
                    metrics.get('winning_trades', 0),
                    metrics.get('losing_trades', 0),
                    f"${metrics.get('total_pnl', 0):.2f}",
                    f"${metrics.get('avg_pnl', 0):.2f}",
                    f"{metrics.get('profit_factor', 0):.2f}"
                ]
            }
            st.dataframe(pd.DataFrame(data), use_container_width=True, hide_index=True)
        else:
            st.info("Nessun dato disponibile")

    with col_r:
        st.subheader("🏆 Performance Strategie")
        strategy_perf = db.get_strategy_performance()
        if strategy_perf:
            df_strat = pd.DataFrame(strategy_perf)
            fig_strat = px.bar(
                df_strat,
                x='strategy',
                y='total_pnl',
                color='total_pnl',
                color_continuous_scale=['#ef4444', '#22c55e'],
                template='plotly_dark'
            )
            fig_strat.update_layout(
                paper_bgcolor='#0f172a',
                plot_bgcolor='#1e293b',
                height=250,
                margin=dict(l=0, r=0, t=0, b=0),
                showlegend=False
            )
            st.plotly_chart(fig_strat, use_container_width=True)
        else:
            st.info("Nessun dato strategie")


# ============================================================
# PAGINA 2: TRADE IN CORSO
# ============================================================

elif "Trade in Corso" in page:
    st.title("📈 Trade in Corso")

    if db is None:
        st.warning("Database non disponibile")
        st.stop()

    # Recupera posizioni aperte
    open_trades = db.get_open_trades()

    if not open_trades:
        st.info("✅ Nessuna posizione aperta al momento")
    else:
        st.write(f"**{len(open_trades)} posizioni aperte:**")

        for trade in open_trades:
            symbol = trade.get('symbol', 'N/A')
            entry_price = trade.get('entry_price', 0)
            stop_loss = trade.get('stop_loss', 0)
            take_profit = trade.get('take_profit', 0)
            qty = trade.get('quantity', 0)
            strategy = trade.get('strategy', 'N/A')
            entry_time = trade.get('entry_time', '')

            # Tenta di recuperare prezzo live
            try:
                from bot.broker import BrokerClient
                broker = BrokerClient(config)
                current_price = broker.get_latest_price(symbol) or entry_price
            except Exception:
                current_price = entry_price

            unrealized_pnl = (current_price - entry_price) * qty
            unrealized_pct = (current_price - entry_price) / entry_price if entry_price > 0 else 0

            pnl_color = "#22c55e" if unrealized_pnl >= 0 else "#ef4444"
            pnl_emoji = "📈" if unrealized_pnl >= 0 else "📉"

            with st.expander(
                f"{pnl_emoji} {symbol} | P&L: {unrealized_pnl:+.2f}$ ({unrealized_pct:+.2%}) | {strategy}",
                expanded=True
            ):
                cols = st.columns(4)
                with cols[0]:
                    st.metric("Prezzo Entrata", f"${entry_price:.2f}")
                    st.metric("Prezzo Corrente", f"${current_price:.2f}")
                with cols[1]:
                    st.metric("Quantità", f"{qty:.4f}")
                    st.metric("P&L Non Realizzato",
                             f"{unrealized_pnl:+.2f}$",
                             f"{unrealized_pct:+.2%}")
                with cols[2]:
                    st.metric("Stop Loss", f"${stop_loss:.2f}" if stop_loss else "N/A")
                    st.metric("Take Profit", f"${take_profit:.2f}" if take_profit else "N/A")
                with cols[3]:
                    st.metric("Strategia", strategy)
                    st.caption(f"Aperto: {entry_time[:16] if entry_time else 'N/A'}")

                # Barra di rischio/rendimento
                if stop_loss and take_profit and stop_loss < entry_price < take_profit:
                    progress = (current_price - stop_loss) / (take_profit - stop_loss)
                    progress = max(0, min(1, progress))
                    st.progress(progress, text=f"Posizione: {progress:.0%} tra SL e TP")

                # Pulsante chiusura manuale
                if st.button(f"🔴 Chiudi {symbol} manualmente", key=f"close_{trade['id']}"):
                    st.warning(f"Funzione chiusura manuale: vai al terminale e usa 'python main.py --close {symbol}'")


# ============================================================
# PAGINA 3: STORICO TRADE
# ============================================================

elif "Storico" in page:
    st.title("📋 Storico Trade")

    if db is None:
        st.warning("Database non disponibile")
        st.stop()

    # Filtri
    st.subheader("🔍 Filtri")
    col_f1, col_f2, col_f3 = st.columns(3)

    with col_f1:
        filter_symbol = st.selectbox(
            "Simbolo",
            ["Tutti", "SPY", "QQQ", "IWM", "AAPL", "MSFT", "NVDA", "TSLA", "AMZN",
             "BTC/USD", "ETH/USD"]
        )

    with col_f2:
        filter_strategy = st.selectbox(
            "Strategia",
            ["Tutte", "confluence", "breakout", "sentiment"]
        )

    with col_f3:
        date_range = st.date_input(
            "Periodo",
            value=(datetime.now() - timedelta(days=30), datetime.now())
        )

    # Recupera storico
    history = db.get_trade_history(
        symbol=filter_symbol if filter_symbol != "Tutti" else None,
        strategy=filter_strategy if filter_strategy != "Tutte" else None,
        start_date=str(date_range[0]) if len(date_range) > 0 else None,
        end_date=str(date_range[1]) if len(date_range) > 1 else None,
        limit=500
    )

    if history:
        df = pd.DataFrame(history)

        # Metriche rapide
        total_pnl = df['pnl'].sum() if 'pnl' in df.columns else 0
        win_count = len(df[df['pnl'] > 0]) if 'pnl' in df.columns else 0
        lose_count = len(df[df['pnl'] <= 0]) if 'pnl' in df.columns else 0

        m1, m2, m3 = st.columns(3)
        m1.metric("Trade Totali", len(df))
        m2.metric("P&L Totale", f"${total_pnl:.2f}")
        m3.metric("Win Rate", f"{win_count/(win_count+lose_count):.1%}" if (win_count+lose_count) > 0 else "N/A")

        # Tabella
        display_cols = ['symbol', 'side', 'entry_price', 'exit_price',
                       'pnl', 'pnl_pct', 'strategy', 'exit_reason',
                       'entry_time', 'exit_time']
        display_cols = [c for c in display_cols if c in df.columns]

        def highlight_pnl(val):
            if isinstance(val, (int, float)):
                color = '#22c55e' if val > 0 else '#ef4444'
                return f'color: {color}'
            return ''

        styled_df = df[display_cols].style.map(
            highlight_pnl,
            subset=['pnl'] if 'pnl' in display_cols else []
        )

        st.dataframe(styled_df, use_container_width=True, hide_index=True)

        # Export CSV
        csv = df[display_cols].to_csv(index=False)
        st.download_button(
            "📥 Esporta CSV",
            data=csv,
            file_name=f"trades_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv"
        )
    else:
        st.info("Nessun trade trovato con i filtri selezionati")


# ============================================================
# PAGINA 4: ANALISI STRATEGIE
# ============================================================

elif "Analisi" in page:
    st.title("🔬 Analisi Strategie")

    if db is None:
        st.warning("Database non disponibile")
        st.stop()

    # Performance per strategia
    st.subheader("📊 Performance per Strategia")
    strategy_perf = db.get_strategy_performance()

    if strategy_perf:
        df_strat = pd.DataFrame(strategy_perf)
        df_strat['win_rate'] = df_strat['wins'] / df_strat['trades']

        col_s1, col_s2 = st.columns(2)

        with col_s1:
            fig = px.bar(
                df_strat,
                x='strategy',
                y='total_pnl',
                color='total_pnl',
                title='P&L per Strategia',
                color_continuous_scale=['#ef4444', '#22c55e'],
                template='plotly_dark'
            )
            fig.update_layout(paper_bgcolor='#0f172a', plot_bgcolor='#1e293b')
            st.plotly_chart(fig, use_container_width=True)

        with col_s2:
            fig2 = px.bar(
                df_strat,
                x='strategy',
                y='win_rate',
                title='Win Rate per Strategia',
                color='win_rate',
                color_continuous_scale=['#ef4444', '#22c55e'],
                template='plotly_dark',
                range_y=[0, 1]
            )
            fig2.update_layout(paper_bgcolor='#0f172a', plot_bgcolor='#1e293b')
            fig2.add_hline(y=0.55, line_dash="dash", annotation_text="Target 55%")
            st.plotly_chart(fig2, use_container_width=True)

        st.dataframe(df_strat, use_container_width=True, hide_index=True)
    else:
        st.info("Nessun dato disponibile per le strategie")

    # Heatmap oraria
    st.subheader("🕐 Heatmap Oraria dei Trade")
    history = db.get_trade_history(limit=1000)

    if history:
        df_h = pd.DataFrame(history)
        if 'entry_time' in df_h.columns and 'pnl' in df_h.columns:
            df_h['entry_time'] = pd.to_datetime(df_h['entry_time'])
            df_h['hour'] = df_h['entry_time'].dt.hour
            df_h['weekday'] = df_h['entry_time'].dt.day_name()

            heatmap_data = df_h.groupby(['weekday', 'hour'])['pnl'].sum().reset_index()
            heatmap_pivot = heatmap_data.pivot(index='weekday', columns='hour', values='pnl').fillna(0)

            # Ordina per giorno della settimana
            days_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
            heatmap_pivot = heatmap_pivot.reindex([d for d in days_order if d in heatmap_pivot.index])

            fig_heat = px.imshow(
                heatmap_pivot,
                title='P&L per Ora e Giorno della Settimana',
                color_continuous_scale='RdYlGn',
                template='plotly_dark',
                aspect='auto'
            )
            fig_heat.update_layout(paper_bgcolor='#0f172a', plot_bgcolor='#1e293b')
            st.plotly_chart(fig_heat, use_container_width=True)
    else:
        st.info("Dati insufficienti per la heatmap")


# ============================================================
# PAGINA 5: CONFIGURAZIONE
# ============================================================

elif "Configurazione" in page:
    st.title("⚙️ Configurazione")

    config = load_config()

    tab1, tab2, tab3 = st.tabs(["🎛️ Parametri Trading", "⚠️ Risk Management", "🔑 API Keys"])

    with tab1:
        st.subheader("Parametri di Trading")

        col1, col2 = st.columns(2)

        with col1:
            new_capital = st.number_input(
                "Capitale iniziale (€)",
                min_value=100,
                max_value=100000,
                value=config.get('trading', {}).get('capital_eur', 500)
            )

            new_max_pos = st.slider(
                "Max posizioni contemporanee",
                min_value=1,
                max_value=10,
                value=config.get('trading', {}).get('max_open_positions', 6)
            )

            new_force_close = st.text_input(
                "Chiusura forzata (ora IT)",
                value=config.get('trading', {}).get('force_close_time', '21:45')
            )

        with col2:
            st.write("**Strategie attive:**")
            s1_enabled = st.checkbox(
                "Confluence (multi-indicatore)",
                value=config.get('strategy_confluence', {}).get('enabled', True)
            )
            s2_enabled = st.checkbox(
                "Breakout + Momentum",
                value=config.get('strategy_breakout', {}).get('enabled', True)
            )
            s3_enabled = st.checkbox(
                "News Sentiment",
                value=config.get('strategy_sentiment', {}).get('enabled', True)
            )
            ml_enabled = st.checkbox(
                "ML Filter (Random Forest)",
                value=config.get('ml_filter', {}).get('enabled', True)
            )

    with tab2:
        st.subheader("Risk Management")

        col3, col4 = st.columns(2)

        with col3:
            new_sl = st.slider(
                "Stop Loss (%)",
                min_value=0.5,
                max_value=5.0,
                value=config.get('risk_management', {}).get('stop_loss_pct', 1.5) * 100,
                step=0.1
            ) / 100

            new_tp = st.slider(
                "Take Profit (%)",
                min_value=1.0,
                max_value=10.0,
                value=config.get('risk_management', {}).get('take_profit_pct', 3.0) * 100,
                step=0.1
            ) / 100

        with col4:
            new_max_daily_loss = st.slider(
                "Max perdita giornaliera (%)",
                min_value=1.0,
                max_value=15.0,
                value=config.get('risk_management', {}).get('daily', {}).get('max_loss_pct', 5.0) * 100,
                step=0.5
            ) / 100

            new_risk_per_trade = st.slider(
                "Rischio max per trade (%)",
                min_value=0.5,
                max_value=5.0,
                value=config.get('risk_management', {}).get('max_risk_per_trade', 2.0) * 100,
                step=0.25
            ) / 100

    with tab3:
        st.subheader("API Keys")
        st.warning("⚠️ Non condividere mai le tue chiavi API!")

        st.text_input("Alpaca Paper API Key", value="*" * 20, type="password")
        st.text_input("Alpaca Paper API Secret", value="*" * 20, type="password")
        st.text_input("Telegram Bot Token", value="*" * 20, type="password")
        st.caption("Per modificare le chiavi API, edita direttamente il file config.yaml")

    st.divider()

    # Switch Paper → Live
    st.subheader("🔄 Cambio Modalità")
    current_mode = config.get('trading', {}).get('mode', 'paper')

    if current_mode == 'paper':
        st.info("📋 Attualmente in modalità PAPER TRADING")
        if st.button("🔴 Passa a LIVE TRADING", type="secondary"):
            st.error("⚠️ ATTENZIONE: Il live trading usa denaro reale!")
            confirm = st.checkbox("Confermo di voler passare al live trading")
            if confirm:
                confirm2 = st.checkbox("Seconda conferma: Ho letto i rischi e voglio procedere")
                if confirm2:
                    config['trading']['mode'] = 'live'
                    save_config(config)
                    st.success("Modalità cambiata a LIVE. Riavvia il bot per applicare.")
    else:
        st.warning("🔴 Attualmente in modalità LIVE TRADING")
        if st.button("✅ Torna a PAPER TRADING"):
            config['trading']['mode'] = 'paper'
            save_config(config)
            st.success("Modalità cambiata a PAPER. Riavvia il bot per applicare.")

    # Salva configurazione
    st.divider()
    if st.button("💾 Salva Configurazione", type="primary"):
        # Aggiorna configurazione
        if 'trading' not in config:
            config['trading'] = {}
        config['trading']['capital_eur'] = new_capital
        config['trading']['max_open_positions'] = new_max_pos
        config['trading']['force_close_time'] = new_force_close

        if 'strategy_confluence' not in config:
            config['strategy_confluence'] = {}
        config['strategy_confluence']['enabled'] = s1_enabled

        if 'strategy_breakout' not in config:
            config['strategy_breakout'] = {}
        config['strategy_breakout']['enabled'] = s2_enabled

        if 'strategy_sentiment' not in config:
            config['strategy_sentiment'] = {}
        config['strategy_sentiment']['enabled'] = s3_enabled

        if 'ml_filter' not in config:
            config['ml_filter'] = {}
        config['ml_filter']['enabled'] = ml_enabled

        if 'risk_management' not in config:
            config['risk_management'] = {}
        config['risk_management']['stop_loss_pct'] = new_sl
        config['risk_management']['take_profit_pct'] = new_tp
        config['risk_management']['max_risk_per_trade'] = new_risk_per_trade

        if 'daily' not in config['risk_management']:
            config['risk_management']['daily'] = {}
        config['risk_management']['daily']['max_loss_pct'] = new_max_daily_loss

        save_config(config)
        st.success("✅ Configurazione salvata! Riavvia il bot per applicare le modifiche.")


# Auto-refresh
if auto_refresh:
    import time
    time.sleep(refresh_secs)
    st.rerun()
