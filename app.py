import concurrent.futures
import datetime
import sqlite3
import numpy as np
import pandas as pd
import requests
import streamlit as st
from dhanhq import dhanhq, DhanContext

# ==========================================
# 1. DATABASE INITIALIZATION (SQLite)
# ==========================================
DB_FILE = "trading_terminal.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS signal_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            symbol TEXT, signal TEXT, strike TEXT, spot_price REAL,
            entry_zone TEXT, sl REAL, target REAL, setup_type TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS paper_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            symbol TEXT, strike TEXT, trade_type TEXT, qty INTEGER,
            entry_price REAL, exit_price REAL, pnl REAL, status TEXT DEFAULT 'OPEN'
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS trade_journal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            symbol TEXT, trade_type TEXT, entry_price REAL, exit_price REAL,
            qty INTEGER, pnl REAL, setup_tag TEXT, rating INTEGER, notes TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# ==========================================
# 2. STREAMLIT UI SETUP
# ==========================================
st.set_page_config(page_title="Institutional Options Terminal", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
    .main { background-color: #0d1117; color: #c9d1d9; }
    .stButton>button { background-color: #238636; color: white; font-weight: bold; width: 100%; border-radius: 6px; }
    .stButton>button:hover { background-color: #2ea043; }
</style>
""", unsafe_allow_html=True)

st.title("🏛️ Institutional Options Terminal & Journal")

st.sidebar.header("🔑 Dhan API Credentials")
client_id = st.sidebar.text_input("Dhan Client ID", type="password")
access_token = st.sidebar.text_input("Dhan Access Token", type="password")
st.sidebar.markdown("---")
timeframe = st.sidebar.selectbox("Analysis Timeframe", ["3", "5", "15"], index=1)

FNO_UNIVERSE = ["NIFTY", "BANKNIFTY", "FINNIFTY", "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN"]

# ==========================================
# 3. SCRIP MASTER & DATA RETRIEVAL
# ==========================================
@st.cache_data(ttl=86400)
def fetch_dhan_scrip_master():
    url = "https://images.dhan.co/api-data/api-scrip-master.csv"
    try:
        df = pd.read_csv(url, low_memory=False)
        symbol_map = {}
        index_alias = {"NIFTY": "NIFTY 50", "BANKNIFTY": "NIFTY BANK", "FINNIFTY": "NIFTY FIN SERVICE"}

        for _, row in df.iterrows():
            sym = str(row.get('SEM_TRADING_SYMBOL', '')).strip()
            sec_id = str(row.get('SEM_SMST_SECURITY_ID', '')).strip()
            segment = str(row.get('SEM_EXM_EXCH_ID', '')).strip()
            instrument = str(row.get('SEM_SEGMENT', '')).strip()

            if segment == 'NSE' and instrument == 'I':
                for clean_name, dhan_name in index_alias.items():
                    if sym.upper() == dhan_name.upper():
                        symbol_map[clean_name] = {"security_id": sec_id, "exchange_segment": "IDX_I", "instrument_type": "INDEX"}
            elif segment == 'NSE' and instrument == 'E':
                clean_sym = sym.replace("-EQ", "").strip()
                if clean_sym not in symbol_map:
                    symbol_map[clean_sym] = {"security_id": sec_id, "exchange_segment": "NSE_EQ", "instrument_type": "EQUITY"}
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
        c1_high, c1_low = df.iloc[i-2]['high'], df.iloc[i-2]['low']
        c3_high, c3_low = df.iloc[i]['high'], df.iloc[i]['low']

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
        today = datetime.datetime.now()
        from_date = (today - datetime.timedelta(days=5)).strftime('%Y-%m-%d')
        to_date = today.strftime('%Y-%m-%d')

        res = dhan.get_intraday_data(
            security_id=meta_info['security_id'],
            exchange_segment=meta_info['exchange_segment'],
            instrument_type=meta_info['instrument_type'],
            from_date=from_date,
            to_date=to_date,
            interval=str(interval_min)
        )

        if not isinstance(res, dict) or res.get('status') != 'success' or not res.get('data'):
            return None

        df = pd.DataFrame(res['data'])
        if df.empty or len(df) < 25:
            return None
        df.columns = [c.lower() for c in df.columns]

        if 'start_time' in df.columns:
            df['start_time'] = pd.to_numeric(df['start_time'])
            df = df.sort_values(by='start_time', ascending=True).reset_index(drop=True)
        elif 'timestamp' in df.columns:
            df = df.sort_values(by='timestamp', ascending=True).reset_index(drop=True)

        df = detect_fair_value_gaps(df)
        current_price = float(df.iloc[-1]['close'])

        signal, setup_type, entry_zone, option_type = "NEUTRAL", None, "", ""
        stop_loss, target = 0.0, 0.0

        for idx in range(len(df)-6, len(df)-1):
            row = df.iloc[idx]
            if row['FVG_Bullish']:
                fvg_low, fvg_high = float(row['FVG_Low']), float(row['FVG_High'])
                if fvg_low <= current_price <= (fvg_high * 1.002):
                    signal, setup_type, option_type = "EARLY BUY CE", "Bullish FVG Retest", "CE"
                    entry_zone = f"{fvg_low:.2f} - {fvg_high:.2f}"
                    stop_loss = round(fvg_low * 0.996, 2)
                    target = round(current_price + (2.5 * (current_price - stop_loss)), 2)
                    break
            elif row['FVG_Bearish']:
                fvg_low, fvg_high = float(row['FVG_Low']), float(row['FVG_High'])
                if (fvg_low * 0.998) <= current_price <= fvg_high:
                    signal, setup_type, option_type = "EARLY BUY PE", "Bearish FVG Retest", "PE"
                    entry_zone = f"{fvg_low:.2f} - {fvg_high:.2f}"
                    stop_loss = round(fvg_high * 1.004, 2)
                    target = round(current_price - (2.5 * (stop_loss - current_price)), 2)
                    break

        if signal != "NEUTRAL":
            strike_step = 50 if "NIFTY" in symbol else (100 if "BANK" in symbol else 10)
            atm_strike = round(current_price / strike_step) * strike_step

            return {
                "Symbol": symbol, "Signal": signal, "Option Strike": f"{atm_strike} {option_type}",
                "Current Price": round(current_price, 2), "Institutional Entry Zone": entry_zone,
                "Tight Stop Loss": stop_loss, "Target (1:2.5 RR)": target, "Institutional Setup": setup_type
            }
    except Exception:
        return None
    return None

# Navigation Tabs
tab_scanner, tab_paper, tab_journal = st.tabs(["🎯 Live Scanner", "📄 Paper Trading Desk", "📖 Trade Journal"])
scrip_master = fetch_dhan_scrip_master()

with tab_scanner:
    if st.button("🚀 SCAN LIVE INSTITUTIONAL SETUPS"):
        if not client_id or not access_token:
            st.warning("Please enter your Dhan Client ID and Access Token in the sidebar.")
        else:
            try:
                context = DhanContext(client_id, access_token)
                dhan = dhanhq(context)
            except TypeError:
                dhan = dhanhq(client_id, access_token)

            with st.spinner("Scanning markets..."):
                signals = []
                with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
                    futures = [executor.submit(analyze_symbol, dhan, sym, scrip_master[sym], timeframe) 
                               for sym in FNO_UNIVERSE if sym in scrip_master]
                    for f in concurrent.futures.as_completed(futures):
                        res = f.result()
                        if res: signals.append(res)

                if signals:
                    st.dataframe(pd.DataFrame(signals), use_container_width=True)
                else:
                    st.info("No active setups found.")

with tab_paper:
    st.info("Paper Trading Desk is active.")

with tab_journal:
    st.info("Trade Journal is active.")
