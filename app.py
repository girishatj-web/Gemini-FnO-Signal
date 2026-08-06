import concurrent.futures
import datetime
import math
import sqlite3
import numpy as np
import pandas as pd
import requests
import streamlit as st

# ==========================================
# NATIVE DHAN API CLIENT (No pip install required)
# ==========================================
class NativeDhanClient:
    """Built-in REST wrapper for Dhan HQ API v2 to bypass package installation issues."""
    def __init__(self, client_id, access_token):
        self.client_id = str(client_id).strip()
        self.access_token = str(access_token).strip()
        self.base_url = "https://api.dhan.co/v2"
        self.headers = {
            "access-token": self.access_token,
            "client-id": self.client_id,
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

    def get_intraday_data(self, security_id, exchange_segment, instrument_type, from_date, to_date, interval):
        url = f"{self.base_url}/charts/intraday"
        payload = {
            "securityId": str(security_id),
            "exchangeSegment": str(exchange_segment),
            "instrument": str(instrument_type),
            "fromDate": str(from_date),
            "toDate": str(to_date),
            "interval": str(interval)
        }
        try:
            res = requests.post(url, headers=self.headers, json=payload, timeout=10)
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, dict) and "open" in data:
                    return {"status": "success", "data": data}
                elif isinstance(data, dict) and "data" in data:
                    return {"status": "success", "data": data["data"]}
                return {"status": "success", "data": data}
            return {"status": "error", "message": res.text}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def get_expiry_list(self, underlying_security_id, underlying_type):
        url = f"{self.base_url}/optionchain/expirylist"
        payload = {
            "UnderlyingScrip": int(underlying_security_id) if str(underlying_security_id).isdigit() else underlying_security_id,
            "UnderlyingSeg": str(underlying_type)
        }
        try:
            res = requests.post(url, headers=self.headers, json=payload, timeout=5)
            if res.status_code == 200:
                data = res.json()
                return {"status": "success", "data": data.get("data", [])}
            return {"status": "error", "message": res.text}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def get_option_chain(self, underlying_security_id, underlying_type, expiry_date):
        url = f"{self.base_url}/optionchain"
        payload = {
            "UnderlyingScrip": int(underlying_security_id) if str(underlying_security_id).isdigit() else underlying_security_id,
            "UnderlyingSeg": str(underlying_type),
            "Expiry": str(expiry_date)
        }
        try:
            res = requests.post(url, headers=self.headers, json=payload, timeout=5)
            if res.status_code == 200:
                data = res.json()
                return {"status": "success", "data": data.get("data", {})}
            return {"status": "error", "message": res.text}
        except Exception as e:
            return {"status": "error", "message": str(e)}

# Auto-fallback from dhanhq package to NativeDhanClient
try:
    from dhanhq import dhanhq
except ImportError:
    dhanhq = NativeDhanClient


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
</style>
""", unsafe_allow_html=True)

st.title("🏛️ Institutional Options Terminal & Journal")

# Sidebar Credentials
st.sidebar.header("🔑 Dhan API Credentials")
client_id = st.sidebar.text_input("Dhan Client ID", type="password")
access_token = st.sidebar.text_input("Dhan Access Token", type="password")

st.sidebar.markdown("---")
timeframe = st.sidebar.selectbox("Analysis Timeframe (Mins)", ["3", "5", "15"], index=1)

FNO_UNIVERSE = [
    "NIFTY", "BANKNIFTY", "FINNIFTY", "RELIANCE", "TCS", "INFY", "HDFCBANK", 
    "ICICIBANK", "SBIN", "BHARTIARTL", "ITC", "KOTAKBANK", "LT", "AXISBANK"
]

@st.cache_data(ttl=86400)
def fetch_dhan_scrip_master():
    url = "https://images.dhan.co/api-data/api-scrip-master.csv"
    try:
        df = pd.read_csv(url, low_memory=False)
        eq_df = df[(df['SEM_EXM_EXCH_ID'] == 'NSE') & (df['SEM_SEGMENT'].isin(['E', 'I']))]
        symbol_map = {}
        for _, row in eq_df.iterrows():
            sym = str(row['SEM_TRADING_SYMBOL']).strip()
            sec_id = str(row['SEM_SMST_SECURITY_ID']).strip()
            clean_sym = sym.replace("-EQ", "").replace("-INDEX", "").strip()
            symbol_map[clean_sym] = {
                "security_id": sec_id,
                "exchange_segment": "IDX_I" if row['SEM_SEGMENT'] == 'I' else "NSE_EQ",
                "instrument_type": "INDEX" if row['SEM_SEGMENT'] == 'I' else "EQUITY"
            }
        return symbol_map
    except Exception:
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
        from_date = (today - datetime.timedelta(days=3)).strftime('%Y-%m-%d')
        to_date = today.strftime('%Y-%m-%d')

        res = dhan.get_intraday_data(sec_id, exch_seg, inst_type, from_date, to_date, str(interval_min))
        if not isinstance(res, dict) or res.get('status') != 'success' or not res.get('data'):
            return None

        df = pd.DataFrame(res['data'])
        if len(df) < 25: return None
        df.columns = [c.lower() for c in df.columns]

        df = detect_fair_value_gaps(df)
        current_price = float(df.iloc[-1]['close'])

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
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        INSERT INTO signal_history (symbol, signal, strike, spot_price, entry_zone, sl, target, setup_type)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (data['Symbol'], data['Signal'], data['Option Strike'], data['Current Price'],
          data['Institutional Entry Zone'], data['Tight Stop Loss'], data['Target (1:2.5 RR)'], data['Institutional Setup']))
    conn.commit()
    conn.close()

# Navigation Tabs
tab_scanner, tab_paper, tab_journal, tab_history = st.tabs([
    "🎯 Live Scanner", "📄 Paper Trading Desk", "📖 Trade Journal", "📊 Signal History DB"
])

scrip_master = fetch_dhan_scrip_master()

with tab_scanner:
    if st.button("🚀 SCAN LIVE INSTITUTIONAL SETUPS"):
        if not client_id or not access_token:
            st.warning("Please enter your Dhan Client ID and Access Token in the sidebar.")
        else:
            dhan = dhanhq(client_id, access_token)
            with st.spinner("Scanning markets for Smart Money Imbalances..."):
                signals = []
                with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
                    futures = [executor.submit(analyze_symbol, dhan, sym, scrip_master[sym], timeframe) 
                               for sym in FNO_UNIVERSE if sym in scrip_master]
                    for f in concurrent.futures.as_completed(futures):
                        res = f.result()
                        if res: signals.append(res)

                if signals:
                    st.success(f"Detected {len(signals)} Institutional Signals!")
                    st.dataframe(pd.DataFrame(signals), use_container_width=True)
                else:
                    st.info("No active Fair Value Gap retest setups detected at this moment.")

with tab_paper:
    st.subheader("📄 Simulated Options Trading")
    col_p1, col_p2 = st.columns(2)
    with col_p1:
        st.markdown("##### Execute New Paper Order")
        p_symbol = st.text_input("Symbol", "NIFTY")
        p_strike = st.text_input("Strike", "24500 CE")
        p_type = st.selectbox("Order Type", ["BUY CE", "BUY PE"])
        p_qty = st.number_input("Quantity", value=50, step=25)
        p_entry = st.number_input("Option Premium (₹)", value=120.0, step=1.0)
        
        if st.button("📥 Place Paper Order"):
            conn = sqlite3.connect(DB_FILE)
            conn.cursor().execute('''
                INSERT INTO paper_trades (symbol, strike, trade_type, qty, entry_price, status)
                VALUES (?, ?, ?, ?, ?, 'OPEN')
            ''', (p_symbol, p_strike, p_type, p_qty, p_entry))
            conn.commit()
            conn.close()
            st.success("Paper order executed!")

    with col_p2:
        st.markdown("##### Active Paper Positions")
        conn = sqlite3.connect(DB_FILE)
        df_open = pd.read_sql_query("SELECT * FROM paper_trades WHERE status = 'OPEN'", conn)
        conn.close()

        if not df_open.empty:
            st.dataframe(df_open[['id', 'timestamp', 'symbol', 'strike', 'trade_type', 'qty', 'entry_price']], use_container_width=True)
            close_id = st.number_input("Position ID to Close", min_value=1, step=1)
            exit_price = st.number_input("Exit Premium Price (₹)", value=150.0, step=1.0)
            
            if st.button("❌ Close Position"):
                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()
                row = c.execute("SELECT qty, entry_price FROM paper_trades WHERE id = ?", (close_id,)).fetchone()
                if row:
                    pnl = (exit_price - row[1]) * row[0]
                    c.execute("UPDATE paper_trades SET exit_price = ?, pnl = ?, status = 'CLOSED' WHERE id = ?", (exit_price, pnl, close_id))
                    conn.commit()
                    st.success(f"Closed! Realized P&L: ₹{pnl:,.2f}")
                conn.close()
        else:
            st.info("No open paper positions.")

with tab_journal:
    st.subheader("📖 Executive Trade Journal")
    with st.expander("➕ Add New Entry", expanded=True):
        col_j1, col_j2 = st.columns(2)
        with col_j1:
            j_symbol = st.text_input("Traded Symbol", "BANKNIFTY")
            j_type = st.selectbox("Direction", ["BUY CE", "BUY PE", "SELL CE", "SELL PE"])
            j_qty = st.number_input("Qty", value=30, step=15)
            j_entry = st.number_input("Entry Price", value=250.0)
            j_exit = st.number_input("Exit Price", value=310.0)
        with col_j2:
            j_tag = st.text_input("Setup Tag", "#FVG_Discount_Retest")
            j_rating = st.slider("Rating", 1, 5, 5)
            j_notes = st.text_area("Notes", "Entered on FVG pullback with volume confirmation.")

        if st.button("💾 Save Journal Entry"):
            j_pnl = (j_exit - j_entry) * j_qty
            conn = sqlite3.connect(DB_FILE)
            conn.cursor().execute('''
                INSERT INTO trade_journal (symbol, trade_type, entry_price, exit_price, qty, pnl, setup_tag, rating, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (j_symbol, j_type, j_entry, j_exit, j_qty, j_pnl, j_tag, j_rating, j_notes))
            conn.commit()
            conn.close()
            st.success("Entry saved!")

    conn = sqlite3.connect(DB_FILE)
    df_journal = pd.read_sql_query("SELECT * FROM trade_journal ORDER BY timestamp DESC", conn)
    conn.close()

    if not df_journal.empty:
        st.metric("Total Cumulative Journal P&L", f"₹{df_journal['pnl'].sum():,.2f}")
        st.dataframe(df_journal, use_container_width=True)

with tab_history:
    st.subheader("📊 Signal History Database")
    conn = sqlite3.connect(DB_FILE)
    df_history = pd.read_sql_query("SELECT * FROM signal_history ORDER BY timestamp DESC", conn)
    conn.close()
    if not df_history.empty:
        st.dataframe(df_history, use_container_width=True)
    else:
        st.info("No recorded signals yet.")
