# ============================================================
# DASHBOARD STREAMLIT - TRADING BOT SCALPING CRYPTO H24
# Interfaccia per monitorare scalping su Render
# ============================================================

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import yaml
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent.parent))

from bot.database import DatabaseManager

IT_TZ = ZoneInfo("Europe/Rome")

# ============================================================
# CONFIGURAZIONE PAGINA
# ============================================================

st.set_page_config(
    page_title="Scalping Bot Dashboard",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Dark theme per trading
st.markdown("""
<style>
    .main { background-color: #0f172a; color: #e2e8f0; }
    .stTabs [data-baseweb="tab-list"] button { background-color: #1e293b; }
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
    .status-pause { color: #f59e0b; }
    .cooldown { color: #f97316; font-weight: bold; }
    .timeout-warning { color: #ef4444; font-weight: bold; }
</style>
""", unsafe_allow_html=True)


# ============================================================
# UTILITY FUNCTIONS
# ============================================================

@st.cache_resource
def get_database():
    """Connessione al database."""
    config = load_config()
    db_path = config.get('database', {}).get('path', 'data/trades.db')
    if Path(db_path).exists():
        return DatabaseManager(db_path)
    return None


def load_config():
    """Carica configurazione."""
    config_path = Path(__file__).parent.parent / 'config.yaml'
    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    return {}


def load_bot_status():
    """Carica stato del bot."""
    status_path = Path(__file__).parent.parent / 'data' / 'bot_status.json'
    if status_path.exists():
        try:
            with open(status_path) as f:
                return json.load(f)
        except:
            pass
    return {'status': 'unknown', 'timestamp': datetime.now().isoformat()}


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
    return {
        'virtual_capital': capital_eur * 1.09,
        'initial_capital': capital_eur * 1.09,
        'total_pnl': 0,
        'total_pnl_pct': 0
    }


def get_today_stats(db):
    """Statistiche di oggi."""
    if not db:
        return {
            'total_trades': 0,
            'winning': 0,
            'losing': 0,
            'total_pnl': 0,
            'best_trade': None,
            'worst_trade': None,
        }
    return db.get_today_stats()


def format_duration(seconds):
    """Formatta durata in minuti:secondi."""
    if not seconds:
        return "N/A"
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{mins}:{secs:02d}"


# ============================================================
# PAGINA PRINCIPALE - OVERVIEW
# ============================================================

def page_overview():
    """Overview del bot e status attuali."""

    st.title("⚡ Scalping Bot Dashboard")

    config = load_config()
    db = get_database()
    bot_status = load_bot_status()
    vc_data = load_virtual_capital()
    today_stats = get_today_stats(db)

    # ---- ROW 1: Status e Capitale ----
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        status = bot_status.get('status', 'unknown')
        if status == 'started':
            emoji = "🟢"
            text = "RUNNING"
        elif status == 'paused':
            emoji = "🟡"
            text = "PAUSED"
        else:
            emoji = "🔴"
            text = "STOPPED"

        st.metric(emoji + " Bot Status", text)

    with col2:
        capital = vc_data.get('virtual_capital') or 0
        capital_eur = config.get('trading', {}).get('capital_eur', 2500)
        st.metric("💰 Capital", f"€{capital_eur} = ${capital:.2f} USD")

    with col3:
        pnl = vc_data.get('total_pnl') or 0
        pnl_pct = (vc_data.get('total_pnl_pct') or 0) * 100
        delta = f"{pnl:+.2f}$ ({pnl_pct:+.2f}%)"
        st.metric("📊 Total P&L", delta)

    with col4:
        daily_stats = get_today_stats(db)
        daily_pnl = daily_stats.get('total_pnl') or 0
        st.metric("📈 Today P&L", f"{daily_pnl:+.2f}$")

    # ---- ROW 2: Trade Counters ----
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        trades_today = today_stats.get('total_trades') or 0
        max_trades = config.get('risk_management', {}).get('daily', {}).get('max_trades', 50)
        pct = (trades_today / max_trades * 100) if max_trades > 0 else 0
        st.metric("📊 Trades Today", f"{trades_today}/{max_trades}",
                 delta=f"{pct:.0f}%")

    with col2:
        winning = today_stats.get('winning') or 0
        losing = today_stats.get('losing') or 0
        wr = (winning / (winning + losing) * 100) if (winning + losing) > 0 else 0
        st.metric("✅ Win Rate", f"{wr:.1f}%", delta=f"{winning}W/{losing}L")

    with col3:
        avg_win = today_stats.get('avg_win') or 0
        st.metric("💚 Avg Win", f"${avg_win:.2f}")

    with col4:
        avg_loss = today_stats.get('avg_loss') or 0
        st.metric("💔 Avg Loss", f"${avg_loss:.2f}")

    # ---- ROW 3: Open Positions ----
    st.subheader("📍 Posizioni Aperte")

    if db:
        open_trades = db.get_open_trades()
        if open_trades:
            for trade in open_trades:
                col1, col2, col3, col4, col5 = st.columns(5)

                symbol = trade.get('symbol', 'N/A')
                entry = trade.get('entry_price', 0)
                current = trade.get('current_price', entry)  # Would need to fetch
                sl = trade.get('stop_loss', 0)
                tp = trade.get('take_profit', 0)

                pnl = (current - entry) * trade.get('quantity', 1) if current else 0
                pnl_pct = ((current - entry) / entry * 100) if entry > 0 and current else 0

                created = trade.get('created_at')
                if created:
                    created_dt = datetime.fromisoformat(created)
                    now = datetime.now(IT_TZ) if created_dt.tzinfo else datetime.now()
                    if created_dt.tzinfo is None:
                        created_dt = created_dt.replace(tzinfo=IT_TZ)
                    duration = (now - created_dt).total_seconds()
                    duration_str = format_duration(duration)
                    timeout_warning = duration > 15*60  # 15 min
                else:
                    duration_str = "N/A"
                    timeout_warning = False

                with col1:
                    st.write(f"**{symbol}**")

                with col2:
                    st.write(f"Entry: ${entry:.2f}")
                    st.write(f"SL: ${sl:.2f} | TP: ${tp:.2f}")

                with col3:
                    color = "profit" if pnl >= 0 else "loss"
                    st.markdown(f"<p class='{color}'>{pnl:+.2f}$ ({pnl_pct:+.2f}%)</p>",
                               unsafe_allow_html=True)

                with col4:
                    if timeout_warning:
                        st.markdown(f"<p class='timeout-warning'>⏱️ {duration_str}</p>",
                                   unsafe_allow_html=True)
                    else:
                        st.write(f"⏳ {duration_str}")

                with col5:
                    st.write(f"Qty: {trade.get('quantity', 0):.6f}")
        else:
            st.info("Nessuna posizione aperta")

    # ---- ROW 4: Ultimi Trade ----
    st.subheader("🎯 Ultimi Trade (Ultimi 10)")

    if db:
        closed_trades = db.get_trade_history(limit=10)
        if closed_trades:
            df_trades = pd.DataFrame(closed_trades)
            df_display = pd.DataFrame({
                'Asset': df_trades['symbol'],
                'Side': df_trades['side'].str.upper(),
                'Entry': df_trades['entry_price'].round(2),
                'Exit': df_trades.get('exit_price', 0).round(2) if 'exit_price' in df_trades else 0,
                'P&L ($)': df_trades.get('pnl', 0).round(2) if 'pnl' in df_trades else 0,
                'P&L (%)': (df_trades.get('pnl', 0) / (df_trades['entry_price'] * df_trades['quantity']) * 100).round(2) if 'pnl' in df_trades else 0,
                'Duration': df_trades.get('duration_seconds', 0) // 60,  # minuti
                'Exit Reason': df_trades.get('exit_reason', 'N/A')
            })
            st.dataframe(df_display, use_container_width=True)
        else:
            st.info("Nessun trade completato oggi")


# ============================================================
# PAGINA CONFIGURAZIONE
# ============================================================

def page_config():
    """Mostra parametri di configurazione."""

    st.title("⚙️ Configurazione Scalping")

    config = load_config()

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("📊 Asset & Trading")
        crypto = config.get('assets', {}).get('crypto', {})
        st.write(f"**Crypto**: {', '.join(crypto.get('symbols', []))}")
        st.write(f"**Modalità**: {config.get('trading', {}).get('mode', 'paper').upper()}")
        st.write(f"**Capitale**: €{config.get('trading', {}).get('capital_eur', 500)}")
        st.write(f"**Ciclo Analisi**: {config.get('trading', {}).get('cycle_interval_seconds', 15)}s")

    with col2:
        st.subheader("🛡️ Risk Management")
        rm = config.get('risk_management', {})
        st.write(f"**R/R Ratio**: 1:2")
        st.write(f"**Stop Loss**: {rm.get('stop_loss_pct', 0)*100:.1f}%")
        st.write(f"**Take Profit**: {rm.get('take_profit_pct', 0)*100:.1f}% (R/R 1:2)")
        break_even = rm.get('break_even', {})
        if break_even.get('enabled'):
            st.write(f"**Break-Even**: +{break_even.get('activation_pct', 0)*100:.1f}%")
        trailing = rm.get('trailing_stop', {})
        st.write(f"**Trailing**: +{trailing.get('activation_pct', 0)*100:.1f}% activation, {trailing.get('trail_pct', 0)*100:.2f}% distance")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("📈 Limiti Giornalieri")
        daily = rm.get('daily', {})
        st.write(f"**Max Loss**: {daily.get('max_loss_pct', 0)*100:.1f}% (€{config.get('trading', {}).get('capital_eur', 2500) * daily.get('max_loss_pct', 0):.0f})")
        st.write(f"**Target Profit**: {daily.get('target_profit_pct', 0)*100:.1f}% (€{config.get('trading', {}).get('capital_eur', 2500) * daily.get('target_profit_pct', 0):.0f})")
        st.write(f"**Max Trade/Day**: {daily.get('max_trades', 80)}")

    with col2:
        st.subheader("🛑 Quality Filters")
        quality = rm.get('quality_filters', {})
        st.write(f"**Max Position Duration**: {quality.get('max_position_duration_min', 15)} min")
        st.write(f"**Cooldown Post-SL**: {quality.get('cooldown_after_loss_sec', 120)}s")
        st.write(f"**Max Spread**: {quality.get('max_spread_pct', 0.0005)*100:.3f}%")
        st.write(f"**Max Open Positions**: {config.get('trading', {}).get('max_open_positions', 4)} (25% per pos)")

    # Strategie
    st.subheader("🎯 Strategie (1min) - 4 Strategie con Sistema di Voto")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.write("**Strategy 1: EMA Crossover**")
        ema = config.get('strategy_confluence', {}).get('ema', {})
        st.write(f"EMA {ema.get('fast_period', 5)} × {ema.get('slow_period', 13)}")
        rsi = config.get('strategy_confluence', {}).get('rsi', {})
        st.write(f"RSI {rsi.get('period', 7)} ({rsi.get('oversold', 35)}/{rsi.get('overbought', 65)})")

    with col2:
        st.write("**Strategy 2: Bollinger Squeeze**")
        bb = config.get('strategy_breakout', {}).get('bollinger', {})
        st.write(f"BB {bb.get('period', 20)}, σ {bb.get('std_dev', 2)}")
        squeeze = config.get('strategy_breakout', {}).get('squeeze', {})
        st.write(f"Squeeze: {squeeze.get('bandwidth_threshold', 0.005)*100:.2f}%")

    with col3:
        st.write("**Strategy 3: VWAP Momentum**")
        vwap = config.get('strategy_sentiment', {}).get('vwap', {})
        st.write(f"Proximity: {vwap.get('price_proximity_pct', 0.003)*100:.2f}%")
        macd = config.get('strategy_sentiment', {}).get('macd', {})
        st.write(f"MACD {macd.get('fast_period', 5)},{macd.get('slow_period', 13)},{macd.get('signal_period', 5)}")

    with col4:
        st.write("**Strategy 4: Liquidity Hunt** ⭐")
        liq = config.get('strategy_liquidity', {})
        st.write(f"Lookback: {liq.get('lookback_mins', 60)} min")
        st.write(f"MFI({liq.get('mfi_period', 9)}) > {liq.get('mfi_buy_threshold', 40)}")
        st.write(f"Sweep: {liq.get('sweep_confirmation_distance', 0.0015)*100:.2f}%")

    # Voting system
    st.markdown("---")
    st.write("**Voting System**: 3/4 or 4/4 concordi → 25% size | 2/4 concordi → 12.5% size | <2 → HOLD")


# ============================================================
# PAGINA PERFORMANCE 6H
# ============================================================

def page_performance():
    """Report performance cada 6 horas."""

    st.title("📊 Performance 6H")

    db = get_database()
    config = load_config()

    if not db:
        st.error("Database non disponibile")
        return

    # Calcola performance ultime 6 ore
    now = datetime.now(IT_TZ)
    six_hours_ago = now - timedelta(hours=6)

    # Get trades from last 6 hours
    trades = db.get_trade_history(
        start_date=six_hours_ago.strftime('%Y-%m-%d'),
        limit=1000
    ) if db else []

    # Filter for last 6 hours (in case trades span multiple days)
    trades = [t for t in trades if t.get('entry_time') and
              datetime.fromisoformat(t['entry_time']).replace(tzinfo=IT_TZ) >= six_hours_ago]

    if not trades:
        st.info("Nessun trade negli ultimi 6 ore")
        return

    df = pd.DataFrame(trades)

    # Metriche
    col1, col2, col3, col4 = st.columns(4)

    total_pnl = df['pnl'].sum() if 'pnl' in df else 0
    total_trades = len(df)
    winners = len(df[df['pnl'] > 0]) if 'pnl' in df else 0
    losers = len(df[df['pnl'] <= 0]) if 'pnl' in df else 0

    with col1:
        delta = f"{total_pnl:+.2f}$"
        st.metric("P&L 6H", delta)

    with col2:
        st.metric("Trade Count", total_trades)

    with col3:
        wr = (winners / total_trades * 100) if total_trades > 0 else 0
        st.metric("Win Rate", f"{wr:.1f}%", delta=f"{winners}W / {losers}L")

    with col4:
        avg_pnl = df['pnl'].mean() if 'pnl' in df else 0
        st.metric("Avg Trade", f"{avg_pnl:+.2f}$")

    # Tabella trade
    st.subheader("Trade Details")
    df_display = df[[
        'symbol', 'side', 'entry_price', 'quantity', 'exit_reason'
    ]].copy()

    if 'pnl' in df:
        df_display['P&L ($)'] = df['pnl'].round(2)

    st.dataframe(df_display, use_container_width=True)

    # Grafico P&L nel tempo
    st.subheader("P&L Timeline")

    if 'closed_at' in df and 'pnl' in df:
        df_sorted = df.sort_values('closed_at')
        df_sorted['cumulative_pnl'] = df_sorted['pnl'].cumsum()

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df_sorted['closed_at'],
            y=df_sorted['cumulative_pnl'],
            mode='lines+markers',
            name='Cumulative P&L',
            line=dict(color='#3b82f6', width=2),
            marker=dict(size=6)
        ))

        fig.update_layout(
            hovermode='x unified',
            template='plotly_dark',
            title='Cumulative P&L (Last 6 Hours)',
            xaxis_title='Time',
            yaxis_title='P&L ($)',
            height=400
        )

        st.plotly_chart(fig, use_container_width=True)


# ============================================================
# MAIN APP
# ============================================================

def main():
    """App principale."""

    with st.sidebar:
        st.title("⚡ Scalping Bot")

        page = st.radio(
            "Navigation",
            ["📊 Overview", "⚙️ Configuration", "📈 Performance 6H"],
            key="page_nav"
        )

    if page == "📊 Overview":
        page_overview()
    elif page == "⚙️ Configuration":
        page_config()
    elif page == "📈 Performance 6H":
        page_performance()

    # Auto-refresh
    st.sidebar.divider()
    st.sidebar.write("⚙️ Dashboard")
    refresh_interval = st.sidebar.selectbox("Refresh", [5, 10, 30, 60], index=1, key="refresh")

    if refresh_interval:
        st.write(f"_Dashboard auto-refresh ogni {refresh_interval}s_")
        st.markdown(f"""
        <script>
            setTimeout(function() {{
                location.reload();
            }}, {refresh_interval * 1000});
        </script>
        """, unsafe_allow_html=True)


if __name__ == "__main__":
    main()
