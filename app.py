
import os
import sys

# --- GUARANTEED STREAMLIT CLOUD DEPENDENCY AUTO-INSTALLER ---
try:
    from dhanhq import dhanhq
except ImportError:
    os.system("uv pip install dhanhq pandas numpy requests")
    os.system(f"{sys.executable} -m pip install dhanhq pandas numpy requests")
    from dhanhq import dhanhq

import concurrent.futures
import datetime
import sqlite3
import numpy as np
import pandas as pd
import requests
import streamlit as st

# ==========================================
# 1. DATABASE INITIALIZATION (SQLite)
# ==========================================
DB_FILE = "trading_terminal.db"

def init_db():
    """Initializes local SQLite database tables for Signals, Paper Trades, and Journal."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # Table 1: Signal History
    c.execute('''
        CREATE TABLE IF NOT EXISTS signal_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            symbol TEXT,
            signal TEXT,
            strike TEXT,
            spot_price REAL,
            entry_zone TEXT,
            sl REAL,
            target REAL,
            setup_type TEXT
        )
    ''')

    # Table 2: Paper Trades
    c.execute('''
        CREATE TABLE IF NOT EXISTS paper_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            symbol TEXT,
            strike TEXT,
            trade_type TEXT,
            qty INTEGER,
            entry_price REAL,
            exit_price REAL,
            pnl REAL,
            status TEXT DEFAULT 'OPEN'
        )
    ''')

    # Table 3: Trade Journal
    c.execute('''
        CREATE TABLE IF NOT EXISTS trade_journal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            symbol TEXT,
            trade_type TEXT,
            entry_price REAL,
            exit_price REAL,
            qty INTEGER,
            pnl REAL,
            setup_tag TEXT,
            rating INTEGER,
            notes TEXT
        )
    ''')
    
    conn.commit()
    conn.close()

# Initialize DB on load
init_db()

# ==========================================
# 2. STREAMLIT UI SETUP
# ==========================================
st.set_page_config(
    page_title="Institutional Options Terminal",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    .main { background-color: #0d1117; color: #c9d1d9; }
    .stButton>button { background-color: #238636; color: white; font-weight: bold; width: 100%; border-radius: 6px; }
    .stButton>button:hover { background-color: #2ea043; }
    .metric-card { background-color: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 12px; text-align: center; }
    .metric-lbl { font-size: 0.75rem; color: #8b949e; text-transform: uppercase; font-weight: 600; }
    .metric-val { font-size: 1.25rem; font-weight: 700; margin-top: 4px; }
</style>
""", unsafe_allow_html=True)

st.title("🏛️ Institutional Options Terminal & Journal")

# Sidebar Controls
st.sidebar.header("🔑 Dhan API Credentials")
client_id = st.sidebar.text_input("Dhan Client ID", type="password")
access_token = st.sidebar.text_input("Dhan Access Token", type="password")

st.sidebar.markdown("---")
timeframe = st.sidebar.selectbox("Analysis Timeframe", ["3", "5", "15"], index=1)

# Default FnO Universe
FNO_UNIVERSE = [
    "NIFTY", "BANKNIFTY", "FINNIFTY",
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN",
    "BHARTIARTL", "ITC", "KOTAKBANK", "LT", "AXISBANK", "TATAMOTORS",
    "TATASTEEL", "MARUTI", "SUNPHARMA", "TITAN", "BAJFINANCE", "HCLTECH"
]

# ==========================================
# 3. SCRIP MASTER & SMC DETECTOR
# ==========================================
@st.cache_data(ttl=86400)
def fetch_dhan_scrip_master():
    """Downloads and accurately maps Dhan Scrip Master for Indices and Equities."""
    url = "https://images.dhan.co/api-data/api-scrip-master.csv"
    try:
        df = pd.read_csv(url, low_memory=False)
        symbol_map = {}
        
        index_alias = {
            "NIFTY": "NIFTY 50",
            "BANKNIFTY": "NIFTY BANK",
            "FINNIFTY": "NIFTY FIN SERVICE"
        }

        for _, row in df.iterrows():
            sym = str(row.get('SEM_TRADING_SYMBOL', '')).strip()
            sec_id = str(row.get('SEM_SMST_SECURITY_ID', '')).strip()
            segment = str(row.get('SEM_EXM_EXCH_ID', '')).strip()
            instrument = str(row.get('SEM_SEGMENT', '')).strip()

            # Handle Indices (NSE Segment 'I')
            if segment == 'NSE' and instrument == 'I':
                for clean_name, dhan_name in index_alias.items():
                    if sym.upper() == dhan_name.upper():
                        symbol_map[clean_name] = {
                            "security_id": sec_id,
                            "exchange_segment": "IDX_I",
                            "instrument_type": "INDEX"
                        }

            # Handle NSE Equities (Segment 'E')
            elif segment == 'NSE' and instrument == 'E':
                clean_sym = sym.replace("-EQ", "").strip()
                if clean_sym not in symbol_map:
                    symbol_map[clean_sym] = {
                        "security_id": sec_id,
                        "exchange_segment": "NSE_EQ",
                        "instrument_type": "EQUITY"
                    }

        return symbol_map
    except Exception as e:
        st.error(f"Error loading Dhan Scrip Master: {e}")
        return {}

def detect_fair_value_gaps(df):
    df['FVG_Bullish'] = False
    df['FVG_Bearish'] = False
    df['FVG_Low'] = np.nan
    df['FVG_High'] = np.nan

    for i in range(2, len(df)):
        c1_high = df.iloc[i-2]['high']
        c1_low = df.iloc[i-2]['low']
        c3_high = df.iloc[i]['high']
        c3_low = df.iloc[i]['low']

        if c3_low > c1_high:
            df.iloc[i, df.columns.get_loc('FVG_Bullish')] = True
            df.iloc[i, df.columns.get_loc('FVG_Low')] = c1_high
            df.iloc[i, df.columns.get_loc('FVG_High')] = c3_low
        elif c3_high < c1_low:
            df.iloc[i, df.columns.get_loc('FVG_Bearish')] = True
            df.iloc[i, df.columns.get_loc('FVG_Low')] = c3_high
            df.iloc[i, df.columns.get_loc('FVG_High')] = c1_low

    return df

def analyze_symbol(dhan, symbol, meta_info, interval_min):
    try:
        sec_id = meta_info['security_id']
        exch_seg = meta_info['exchange_segment']
        inst_type = meta_info['instrument_type']

        today = datetime.datetime.now()
        from_date = (today - datetime.timedelta(days=5)).strftime('%Y-%m-%d')
        to_date = today.strftime('%Y-%m-%d')

        res = dhan.get_intraday_data(
            security_id=sec_id,
            exchange_segment=exch_seg,
            instrument_type=inst_type,
            from_date=from_date,
            to_date=to_date,
            interval=str(interval_min)
        )

        if not isinstance(res, dict) or res.get('status') != 'success' or not res.get('data'):
            return None

        raw_data = res['data']
        df = pd.DataFrame(raw_data)
        if df.empty or len(df) < 25:
            return None

        # Standardize column headers
        df.columns = [c.lower() for c in df.columns]

        # FIX: Ensure DataFrame is chronologically sorted (Oldest -> Newest)
        if 'start_time' in df.columns:
            df['start_time'] = pd.to_numeric(df['start_time'])
            df = df.sort_values(by='start_time', ascending=True).reset_index(drop=True)
        elif 'timestamp' in df.columns:
            df = df.sort_values(by='timestamp', ascending=True).reset_index(drop=True)

        # Detect FVGs on sorted data
        df = detect_fair_value_gaps(df)

        # Get the guaranteed latest candle price
        current_candle = df.iloc[-1]
        current_price = float(current_candle['close'])

        signal, setup_type, entry_zone, option_type = "NEUTRAL", None, "", ""
        stop_loss, target = 0.0, 0.0

        for idx in range(len(df)-6, len(df)-1):
            row = df.iloc[idx]
            if row['FVG_Bullish']:
                fvg_low, fvg_high = float(row['FVG_Low']), float(row['FVG_High'])
                if fvg_low <= current_price <= (fvg_high * 1.002):
                    signal = "EARLY BUY CE"
                    setup_type = "Bullish FVG Retest"
                    entry_zone = f"{fvg_low:.2f} - {fvg_high:.2f}"
                    stop_loss = round(fvg_low * 0.996, 2)
                    target = round(current_price + (2.5 * (current_price - stop_loss)), 2)
                    option_type = "CE"
                    break
            elif row['FVG_Bearish']:
                fvg_low, fvg_high = float(row['FVG_Low']), float(row['FVG_High'])
                if (fvg_low * 0.998) <= current_price <= fvg_high:
                    signal = "EARLY BUY PE"
                    setup_type = "Bearish FVG Retest"
                    entry_zone = f"{fvg_low:.2f} - {fvg_high:.2f}"
                    stop_loss = round(fvg_high * 1.004, 2)
                    target = round(current_price - (2.5 * (stop_loss - current_price)), 2)
                    option_type = "PE"
                    break

        if signal != "NEUTRAL":
            strike_step = 50 if "NIFTY" in symbol else (100 if "BANK" in symbol else 10)
            atm_strike = round(current_price / strike_step) * strike_step

            sig_data = {
                "Symbol": symbol,
                "Signal": signal,
                "Option Strike": f"{atm_strike} {option_type}",
                "Current Price": round(current_price, 2),
                "Institutional Entry Zone": entry_zone,
                "Tight Stop Loss": stop_loss,
                "Target (1:2.5 RR)": target,
                "Institutional Setup": setup_type
            }

            save_signal_to_db(sig_data)
            return sig_data

    except Exception:
        return None
    return None

def save_signal_to_db(data):
    """Saves generated signals into the SQLite history database."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        INSERT INTO signal_history (symbol, signal, strike, spot_price, entry_zone, sl, target, setup_type)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (data['Symbol'], data['Signal'], data['Option Strike'], data['Current Price'],
          data['Institutional Entry Zone'], data['Tight Stop Loss'], data['Target (1:2.5 RR)'], data['Institutional Setup']))
    conn.commit()
    conn.close()

# ==========================================
# 4. NAVIGATION TABS
# ==========================================
tab_scanner, tab_paper, tab_journal, tab_history = st.tabs([
    "🎯 Live Scanner", "📄 Paper Trading Desk", "📖 Trade Journal", "📊 Signal History DB"
])

scrip_master = fetch_dhan_scrip_master()

# ------------------------------------------
# TAB 1: LIVE SCANNER
# ------------------------------------------
with tab_scanner:
    if st.button("🚀 SCAN LIVE INSTITUTIONAL SETUPS"):
        if not client_id or not access_token:
            st.warning("Please enter your Dhan Client ID and Access Token in the sidebar.")
        else:
            dhan = dhanhq(client_id, access_token)
            with st.spinner("Scanning markets for Imbalances & saving signals..."):
                signals = []
                with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
                    futures = [executor.submit(analyze_symbol, dhan, sym, scrip_master[sym], timeframe) 
                               for sym in FNO_UNIVERSE if sym in scrip_master]
                    for f in concurrent.futures.as_completed(futures):
                        res = f.result()
                        if res: signals.append(res)

                if signals:
                    df_sig = pd.DataFrame(signals)
                    st.success(f"Detected {len(df_sig)} Institutional Signals!")
                    st.dataframe(df_sig, use_container_width=True)
                else:
                    st.info("No active Fair Value Gap retest setups at this moment.")

# ------------------------------------------
# TAB 2: PAPER TRADING DESK
# ------------------------------------------
with tab_paper:
    st.subheader("📄 Simulated Options Trading")
    
    col_p1, col_p2 = st.columns(2)
    with col_p1:
        st.markdown("##### Execute New Paper Order")
        p_symbol = st.text_input("Symbol (e.g. NIFTY, RELIANCE)", "NIFTY")
        p_strike = st.text_input("Strike (e.g. 24500 CE)", "24500 CE")
        p_type = st.selectbox("Order Type", ["BUY CE", "BUY PE"])
        p_qty = st.number_input("Lot Quantity / Shares", value=50, step=25)
        p_entry = st.number_input("Estimated Option Premium (₹)", value=120.0, step=1.0)
        
        if st.button("📥 Place Paper Order"):
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute('''
                INSERT INTO paper_trades (symbol, strike, trade_type, qty, entry_price, status)
                VALUES (?, ?, ?, ?, ?, 'OPEN')
            ''', (p_symbol, p_strike, p_type, p_qty, p_entry))
            conn.commit()
            conn.close()
            st.success("Paper order executed successfully!")

    with col_p2:
        st.markdown("##### Active Paper Positions")
        conn = sqlite3.connect(DB_FILE)
        df_open = pd.read_sql_query("SELECT * FROM paper_trades WHERE status = 'OPEN'", conn)
        conn.close()

        if not df_open.empty:
            st.dataframe(df_open[['id', 'timestamp', 'symbol', 'strike', 'trade_type', 'qty', 'entry_price']], use_container_width=True)
            
            close_id = st.number_input("Position ID to Close", min_value=1, step=1)
            exit_price = st.number_input("Exit Premium Price (₹)", value=150.0, step=1.0)
            
            if st.button("❌ Close Paper Position"):
                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()
                row = c.execute("SELECT qty, entry_price FROM paper_trades WHERE id = ?", (close_id,)).fetchone()
                if row:
                    qty, entry = row
                    pnl = (exit_price - entry) * qty
                    c.execute('''
                        UPDATE paper_trades 
                        SET exit_price = ?, pnl = ?, status = 'CLOSED' 
                        WHERE id = ?
                    ''', (exit_price, pnl, close_id))
                    conn.commit()
                    st.success(f"Position closed! Realized P&L: ₹{pnl:,.2f}")
                conn.close()
        else:
            st.info("No open paper positions.")

# ------------------------------------------
# TAB 3: TRADE JOURNAL
# ------------------------------------------
with tab_journal:
    st.subheader("📖 Executive Trade Journal")

    with st.expander("➕ Add New Journal Entry", expanded=True):
        col_j1, col_j2 = st.columns(2)
        with col_j1:
            j_symbol = st.text_input("Traded Symbol", "BANKNIFTY")
            j_type = st.selectbox("Trade Direction", ["BUY CE", "BUY PE", "SELL CE", "SELL PE"])
            j_qty = st.number_input("Quantity", value=30, step=15)
            j_entry = st.number_input("Entry Price (₹)", value=250.0)
            j_exit = st.number_input("Exit Price (₹)", value=310.0)
        
        with col_j2:
            j_tag = st.text_input("Setup Tag", "#FVG_Discount_Retest")
            j_rating = st.slider("Trade Execution Rating", 1, 5, 5)
            j_notes = st.text_area("Trade Notes / Psychological Observations", "Entered on FVG pullback with Option Chain volume confirmation. Stuck strictly to SL.")

        if st.button("💾 Save Journal Entry"):
            j_pnl = (j_exit - j_entry) * j_qty
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute('''
                INSERT INTO trade_journal (symbol, trade_type, entry_price, exit_price, qty, pnl, setup_tag, rating, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (j_symbol, j_type, j_entry, j_exit, j_qty, j_pnl, j_tag, j_rating, j_notes))
            conn.commit()
            conn.close()
            st.success("Trade entry successfully logged!")

    st.markdown("##### Historical Journal Entries")
    conn = sqlite3.connect(DB_FILE)
    df_journal = pd.read_sql_query("SELECT * FROM trade_journal ORDER BY timestamp DESC", conn)
    conn.close()

    if not df_journal.empty:
        total_pnl = df_journal['pnl'].sum()
        win_rate = (len(df_journal[df_journal['pnl'] > 0]) / len(df_journal)) * 100
        
        st.metric("Total Cumulative Journal P&L", f"₹{total_pnl:,.2f}", delta=f"{win_rate:.1f}% Win Rate")
        st.dataframe(df_journal, use_container_width=True)
    else:
        st.info("No journal entries logged yet.")

# ------------------------------------------
# TAB 4: SIGNAL HISTORY DATABASE
# ------------------------------------------
with tab_history:
    st.subheader("📊 Signal History Database (Auto-Logged)")
    
    conn = sqlite3.connect(DB_FILE)
    df_history = pd.read_sql_query("SELECT * FROM signal_history ORDER BY timestamp DESC", conn)
    conn.close()

    if not df_history.empty:
        st.dataframe(df_history, use_container_width=True)
        
        if st.button("🗑️ Clear Signal History"):
            conn = sqlite3.connect(DB_FILE)
            conn.cursor().execute("DELETE FROM signal_history")
            conn.commit()
            conn.close()
            st.rerun()
    else:
        st.info("No historical signals recorded yet. Run the scanner in Tab 1 to start populating data.")
 
