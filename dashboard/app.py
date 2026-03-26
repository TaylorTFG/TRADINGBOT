# ============================================================
# DASHBOARD STREAMLIT - TRADING BOT SCALPING CRYPTO H24
# 3 pagine semplificate: Live Monitor, Analytics, Config
# ============================================================

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import yaml
import json
import sys
from datetime import datetime, timedelta, date
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent.parent))

from bot.database import DatabaseManager

IT_TZ = ZoneInfo("Europe/Rome")

# ============================================================
# CONFIGURAZIONE PAGINA
# ============================================================

st.set_page_config(
    page_title="Trading Bot Dashboard",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Dark theme per trading
st.markdown("""
<style>
    .main { background-color: #0f172a; color: #e2e8f0; }
    .metric-card {
        background: #1e293b;
        border-radius: 8px;
        padding: 1rem;
        border-left: 4px solid #3b82f6;
    }
    .profit { color: #22c55e; font-weight: bold; }
    .loss { color: #ef4444; font-weight: bold; }
    .neutral { color: #94a3b8; }
    .status-on { color: #22c55e; }
    .status-off { color: #ef4444; }
</style>
""", unsafe_allow_html=True)


# ============================================================
# UTILITY FUNCTIONS
# ============================================================

@st.cache_data(ttl=5)
def get_database():
    """Connessione al database con cache 5 secondi."""
    config = load_config()
    db_path = config.get('database', {}).get('path', 'data/trades.db')
    if Path(db_path).exists():
        return DatabaseManager(db_path)
    return None


@st.cache_resource
def load_config():
    """Carica configurazione."""
    config_path = Path(__file__).parent.parent / 'config.yaml'
    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    return {}


def load_virtual_capital():
    """Carica capitale virtuale."""
    vc_path = Path(__file__).parent.parent / 'data' / 'virtual_capital.json'
    if vc_path.exists():
        try:
            with open(vc_path) as f:
                return json.load(f)
        except:
            pass
    config = load_config()
    capital_eur = config.get('trading', {}).get('capital_eur', 500)
    rate = config.get('trading', {}).get('eur_usd_rate', 1.09)
    return {'virtual_capital': capital_eur * rate}


def format_currency(value):
    """Formatta valore in USD."""
    if value is None:
        return "N/A"
    color = "green" if value >= 0 else "red"
    return f"<span class='{color}'>${value:+.2f}</span>"


# ============================================================
# PAGINA 1: LIVE MONITOR
# ============================================================

def page_live_monitor():
    """Pagina principale: monitoraggio live."""
    st.title("⚡ Live Monitor")

    db = get_database()
    config = load_config()
    capital_data = load_virtual_capital()

    if not db:
        st.error("Database non trovato")
        return

    # STATUS E CAPITAL
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        virtual_cap = capital_data.get('virtual_capital', 0)
        st.metric("Capitale", f"${virtual_cap:.2f}")

    with col2:
        pnl = virtual_cap - (capital_data.get('initial_capital', 0) or capital_data.get('virtual_capital', 0))
        st.metric("P&L Totale", f"${pnl:+.2f}", delta=f"{(pnl / virtual_cap * 100) if virtual_cap else 0:+.1f}%")

    with col3:
        today_stats = db.get_today_stats()
        today_pnl = today_stats.get('total_pnl', 0) or 0
        st.metric("P&L Oggi", f"${today_pnl:+.2f}")

    with col4:
        trades_today = today_stats.get('total_trades', 0) or 0
        wins = today_stats.get('winning', 0) or 0
        wr = (wins / trades_today * 100) if trades_today > 0 else 0
        st.metric("Win Rate", f"{wr:.1f}%", f"{wins}/{trades_today} trade")

    # POSIZIONI APERTE
    st.subheader("📊 Posizioni Aperte")
    open_trades = db.get_open_trades()

    if open_trades:
        trade_list = []
        for trade in open_trades:
            # Calcola P&L non realizzato
            current_price = 0  # Normalmente recuperato dal broker
            entry_price = trade['entry_price']
            qty = trade['quantity']
            side = trade['side']

            unrealized_pnl = (current_price - entry_price) * qty if side == 'buy' else (entry_price - current_price) * qty
            duration_min = (datetime.now(IT_TZ) - datetime.fromisoformat(trade['entry_time'].replace('Z', '+00:00'))).total_seconds() / 60

            trade_list.append({
                'Simbolo': trade['symbol'],
                'Posizione': '↑ BUY' if side == 'buy' else '↓ SELL',
                'Qty': f"{qty:.6f}",
                'Entrata': f"${entry_price:.2f}",
                'P&L': f"${unrealized_pnl:+.2f}",
                'Durata': f"{duration_min:.1f} min",
                'SL': f"${trade['stop_loss']:.2f}" if trade['stop_loss'] else "N/A",
                'TP': f"${trade['take_profit']:.2f}" if trade['take_profit'] else "N/A"
            })

        df_trades = pd.DataFrame(trade_list)
        st.dataframe(df_trades, use_container_width=True, hide_index=True)
    else:
        st.info("Nessuna posizione aperta")

    # ULTIMI 15 TRADE CHIUSI
    st.subheader("📈 Ultimi 15 Trade")
    closed_trades = db.get_trade_history(limit=15)

    if closed_trades:
        trade_list = []
        for trade in closed_trades:
            entry_price = trade.get('entry_price')
            exit_price = trade.get('exit_price')
            pnl = trade.get('pnl')
            pnl_pct = trade.get('pnl_pct')

            trade_list.append({
                'Simbolo': trade['symbol'],
                'Strategia': trade.get('strategy') or 'N/A',
                'Tipo': 'BUY' if trade.get('side') == 'buy' else 'SELL',
                'Entrata': f"${entry_price:.2f}" if entry_price else "N/A",
                'Uscita': f"${exit_price:.2f}" if exit_price else "N/A",
                'P&L': f"${pnl:+.2f}" if pnl is not None else "N/A",
                'Win Rate': f"{pnl_pct:+.2%}" if pnl_pct is not None else "N/A",
                'Motivo': trade.get('exit_reason') or 'N/A'
            })

        df_closed = pd.DataFrame(trade_list)
        st.dataframe(df_closed, use_container_width=True, hide_index=True)
    else:
        st.info("Nessun trade chiuso ancora")


# ============================================================
# PAGINA 2: ANALYTICS
# ============================================================

def page_analytics():
    """Pagina analytics: performance delle strategie."""
    st.title("📊 Analytics")

    db = get_database()
    if not db:
        st.error("Database non trovato")
        return

    # METRICHE GLOBALI
    st.subheader("Metriche Globali")
    metrics = db.get_performance_metrics()

    if metrics:
        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.metric("Total Trades", metrics.get('total_trades', 0))
        with col2:
            wr = metrics.get('win_rate', 0)
            st.metric("Win Rate", f"{wr:.1%}")
        with col3:
            pf = metrics.get('profit_factor', 0)
            st.metric("Profit Factor", f"{pf:.2f}")
        with col4:
            sharpe = metrics.get('sharpe_ratio', 0)
            st.metric("Sharpe Ratio", f"{sharpe:.2f}")
        with col5:
            dd = metrics.get('max_drawdown', 0)
            st.metric("Max Drawdown", f"{dd:.1%}")

    # P&L CUMULATIVO
    st.subheader("P&L Cumulativo")
    closed_trades = db.get_trade_history(limit=500)

    if closed_trades:
        pnls = [t.get('pnl', 0) for t in closed_trades if t.get('pnl') is not None]
        cumulative = []
        running = 0
        for p in pnls:
            running += p
            cumulative.append(running)

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            y=cumulative,
            mode='lines',
            name='P&L Cumulativo',
            line=dict(color='#22c55e', width=2),
            fill='tozeroy',
            fillcolor='rgba(34, 197, 94, 0.2)'
        ))
        fig.update_layout(
            title="P&L Cumulativo nel Tempo",
            xaxis_title="Trade #",
            yaxis_title="P&L Cumulativo ($)",
            template="plotly_dark",
            height=400
        )
        st.plotly_chart(fig, use_container_width=True)

    # PERFORMANCE PER STRATEGIA
    st.subheader("Performance per Strategia")
    strategy_perf = db.get_strategy_performance()

    if strategy_perf:
        perf_list = []
        for s in strategy_perf:
            total_trades = s.get('trades', 0)
            wins = s.get('wins', 0)
            wr = (wins / total_trades * 100) if total_trades > 0 else 0
            avg_pnl = s.get('avg_pnl')
            total_pnl = s.get('total_pnl')
            perf_list.append({
                'Strategia': s.get('strategy', 'N/A'),
                'Trades': total_trades,
                'Wins': wins,
                'Losses': s.get('losses', 0),
                'Win Rate': f"{wr:.1f}%",
                'Avg PnL': f"${avg_pnl:+.2f}" if avg_pnl is not None else "N/A",
                'Total PnL': f"${total_pnl:+.2f}" if total_pnl is not None else "N/A"
            })

        df_strat = pd.DataFrame(perf_list)
        st.dataframe(df_strat, use_container_width=True, hide_index=True)

        # Pie chart per distribution trade
        fig_pie = px.pie(
            values=[s['trades'] for s in strategy_perf],
            names=[s['strategy'] for s in strategy_perf],
            title="Distribuzione Trade per Strategia"
        )
        fig_pie.update_layout(template="plotly_dark")
        st.plotly_chart(fig_pie, use_container_width=True)


# ============================================================
# PAGINA 3: CONFIG
# ============================================================

def page_config():
    """Pagina configurazione e status."""
    st.title("⚙️ Configurazione & Status")

    config = load_config()

    # PARAMETRI CHIAVE (READONLY)
    st.subheader("Parametri Chiave")
    col1, col2, col3 = st.columns(3)

    with col1:
        st.write("**Modalità Trading**")
        st.code(config.get('trading', {}).get('mode', 'paper'))

    with col2:
        st.write("**Capitale (EUR)**")
        st.code(f"{config.get('trading', {}).get('capital_eur', 0)}")

    with col3:
        st.write("**Timezone**")
        st.code(config.get('trading', {}).get('timezone', 'Europe/Rome'))

    # STRATEGIE ABILITATE
    st.subheader("Strategie Abilitate")
    strategies = {
        'Confluence': config.get('strategy_confluence', {}).get('enabled', False),
        'Breakout': config.get('strategy_breakout', {}).get('enabled', False),
        'Sentiment': config.get('strategy_sentiment', {}).get('enabled', False),
        'RSI Divergence': config.get('strategy_rsi_divergence', {}).get('enabled', False),
        'S/R Bounce': config.get('strategy_sr_bounce', {}).get('enabled', False),
        'MTF Confluence': config.get('strategy_mtf_confluence', {}).get('enabled', False),
    }

    cols = st.columns(3)
    for i, (name, enabled) in enumerate(strategies.items()):
        with cols[i % 3]:
            status = "✓ ON" if enabled else "✗ OFF"
            st.write(f"{name}: {status}")

    # ASSET
    st.subheader("Asset Operativi")
    assets = config.get('assets', {}).get('crypto', {}).get('symbols', [])
    st.write(f"**{len(assets)} Asset:** {', '.join(assets)}")

    # LOG VIEWER
    st.subheader("📝 Log Viewer")
    log_path = Path(__file__).parent.parent / 'logs' / 'trading_bot.log'

    if log_path.exists():
        try:
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
                last_lines = lines[-50:] if len(lines) > 50 else lines
                log_text = ''.join(last_lines)
                st.code(log_text, language='log')
        except Exception as e:
            st.error(f"Errore lettura log: {e}")
    else:
        st.info("Log file non trovato")

    # AZIONI
    st.subheader("Azioni")
    if st.button("🔄 Ricarica Dati", use_container_width=True):
        st.cache_data.clear()
        st.success("Dati ricaricati!")

    if st.button("🚀 Restart Bot", use_container_width=True):
        st.warning("Riavviare il bot da terminale: `python main.py bot`")


# ============================================================
# MAIN
# ============================================================

def main():
    # Sidebar per selezione pagina
    st.sidebar.title("Navigation")
    page = st.sidebar.radio(
        "Seleziona pagina:",
        options=["Live Monitor", "Analytics", "Config"],
        label_visibility="collapsed"
    )

    # Auto-refresh
    st.sidebar.markdown("---")
    refresh_interval = st.sidebar.slider(
        "Auto-refresh (sec)",
        min_value=5,
        max_value=60,
        value=30
    )
    st.sidebar.write(f"⏱️ Refresh ogni {refresh_interval}s")

    # Mostra pagina selezionata
    if page == "Live Monitor":
        page_live_monitor()
    elif page == "Analytics":
        page_analytics()
    elif page == "Config":
        page_config()

    # Auto-refresh
    import time
    time.sleep(refresh_interval)
    st.rerun()


if __name__ == "__main__":
    main()
