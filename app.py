import os
import sys
import time
import math
import sqlite3
import datetime
import concurrent.futures
import requests
import numpy as np
import pandas as pd
import streamlit as st

# ==========================================
# 1. DATABASE & PERSISTENT CONFIG STORE
# ==========================================
DB_FILE = "trading_terminal.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS app_config (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS signal_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            symbol TEXT, signal TEXT, strike TEXT, spot_price REAL,
            opt_entry REAL, opt_sl REAL, opt_target REAL,
            lot_size INTEGER, max_risk_amount REAL, setup_type TEXT,
            telegram_sent INTEGER DEFAULT 0
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS paper_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            symbol TEXT, strike TEXT, trade_type TEXT, qty INTEGER,
            entry_price REAL, exit_price REAL, pnl REAL, status TEXT DEFAULT 'OPEN',
            setup_tag TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS trade_journal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            symbol TEXT, trade_type TEXT, entry_price REAL, exit_price REAL,
            qty INTEGER, pnl REAL, setup_tag TEXT, rating INTEGER, notes TEXT,
            execution_type TEXT DEFAULT 'PAPER'
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def get_config(key, default=""):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT value FROM app_config WHERE key = ?", (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else default

def set_config(key, value):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO app_config (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()

# Anti-Duplicate Memory Engine (15-Minute Cooldown Window)
def is_duplicate_signal(symbol, signal, strike, cooldown_minutes=15):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    time_threshold = (datetime.datetime.now() - datetime.timedelta(minutes=cooldown_minutes)).strftime('%Y-%m-%d %H:%M:%S')
    c.execute('''
        SELECT id FROM signal_history 
        WHERE symbol = ? AND signal = ? AND strike = ? AND timestamp >= ?
    ''', (symbol, signal, strike, time_threshold))
    row = c.fetchone()
    conn.close()
    return row is not None

def log_signal_to_db(sig, telegram_sent=0):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        INSERT INTO signal_history (symbol, signal, strike, spot_price, opt_entry, opt_sl, opt_target, lot_size, max_risk_amount, setup_type, telegram_sent)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (sig['Symbol'], sig['Signal'], sig['Strike'], sig['Spot Price'], sig['Opt Entry (₹)'], sig['Opt StopLoss (₹)'], sig['Opt Target (₹)'], sig['Total Qty'], sig['Max Risk (₹)'], sig['Setup Type'], telegram_sent))
    conn.commit()
    conn.close()

# ==========================================
# 2. NATIVE DHAN API REST CLIENT
# ==========================================
class NativeDhanClient:
    """Native REST client for Dhan API v2 with zero external SDK dependencies."""
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

    def validate_connection(self):
        url = f"{self.base_url}/fundlimit"
        try:
            res = requests.get(url, headers=self.headers, timeout=6)
            if res.status_code == 200:
                return True, "Connected successfully to Dhan HQ API v2!"
            return False, f"HTTP Error {res.status_code}: {res.text}"
        except Exception as e:
            return False, f"Connection Failed: {str(e)}"

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
            res = requests.post(url, headers=self.headers, json=payload, timeout=8)
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

    def execute_live_order(self, security_id, exchange_segment, transaction_type, quantity, order_type="MARKET", price=0.0, product_type="INTRADAY"):
        """Executes real-money order on Dhan API."""
        url = f"{self.base_url}/orders"
        payload = {
            "dhanClientId": self.client_id,
            "correlationId": f"SMC_{int(time.time())}",
            "transactionType": transaction_type.upper(),  # BUY or SELL
            "exchangeSegment": exchange_segment,         # e.g., NSE_FNO, NSE_EQ
            "productType": product_type,                 # INTRADAY, MARGIN, CNC
            "orderType": order_type,                     # MARKET, LIMIT
            "validity": "DAY",
            "securityId": str(security_id),
            "quantity": int(quantity),
            "disclosedQuantity": 0,
            "price": float(price),
            "triggerPrice": 0.0,
            "afterMarketOrder": False
        }
        try:
            res = requests.post(url, headers=self.headers, json=payload, timeout=8)
            return res.json()
        except Exception as e:
            return {"orderStatus": "REJECTED", "remarks": str(e)}

# ==========================================
# 3. TELEGRAM BOT NOTIFIER
# ==========================================
def send_telegram_alert(bot_token, chat_id, message):
    if not bot_token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{bot_token.strip()}/sendMessage"
    payload = {
        "chat_id": chat_id.strip(),
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        res = requests.post(url, json=payload, timeout=5)
        return res.status_code == 200
    except Exception:
        return False

# ==========================================
# 4. INSTITUTIONAL SMC & INDICATOR ENGINE
# ==========================================
LOT_SIZES = {
    "NIFTY": 25, "BANKNIFTY": 15, "FINNIFTY": 25, "MIDCPNIFTY": 50,
    "RELIANCE": 250, "TCS": 175, "INFY": 400, "HDFCBANK": 550,
    "ICICIBANK": 700, "SBIN": 750, "BHARTIARTL": 475, "LT": 300
}

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

def calculate_htf_trend(df_htf):
    if len(df_htf) < 50: return "NEUTRAL"
    df_htf['ema20'] = df_htf['close'].ewm(span=20, adjust=False).mean()
    df_htf['ema50'] = df_htf['close'].ewm(span=50, adjust=False).mean()
    last_close = df_htf.iloc[-1]['close']
    last_ema20 = df_htf.iloc[-1]['ema20']
    last_ema50 = df_htf.iloc[-1]['ema50']
    if last_close > last_ema20 > last_ema50: return "BULLISH"
    elif last_close < last_ema20 < last_ema50: return "BEARISH"
    return "NEUTRAL"

def detect_liquidity_sweep(df):
    if len(df) < 20: return False, False
    recent_high = df['high'].iloc[-20:-2].max()
    recent_low = df['low'].iloc[-20:-2].min()
    curr_candle, prev_candle = df.iloc[-1], df.iloc[-2]
    bullish_sweep = (prev_candle['low'] < recent_low or curr_candle['low'] < recent_low) and (curr_candle['close'] > recent_low)
    bearish_sweep = (prev_candle['high'] > recent_high or curr_candle['high'] > recent_high) and (curr_candle['close'] < recent_high)
    return bullish_sweep, bearish_sweep

def detect_choch_and_ob(df):
    if len(df) < 15: return False, False
    df['swing_high'] = df['high'].rolling(5, center=True).max()
    df['swing_low'] = df['low'].rolling(5, center=True).min()
    recent_sh = df['swing_high'].dropna().iloc[-2] if len(df['swing_high'].dropna()) > 1 else df['high'].max()
    recent_sl = df['swing_low'].dropna().iloc[-2] if len(df['swing_low'].dropna()) > 1 else df['low'].min()
    curr_close = df.iloc[-1]['close']
    return curr_close > recent_sh, curr_close < recent_sl

def run_smc_analysis(dhan, symbol, meta_info, interval_5m, capital, max_risk_pct, delta):
    try:
        sec_id = meta_info['security_id']
        exch_seg = meta_info['exchange_segment']
        inst_type = meta_info['instrument_type']

        today = datetime.datetime.now()
        from_date = (today - datetime.timedelta(days=4)).strftime('%Y-%m-%d')
        to_date = today.strftime('%Y-%m-%d')

        res_5m = dhan.get_intraday_data(sec_id, exch_seg, inst_type, from_date, to_date, str(interval_5m))
        if not isinstance(res_5m, dict) or res_5m.get('status') != 'success' or not res_5m.get('data'):
            return None

        df_5m = pd.DataFrame(res_5m['data'])
        if len(df_5m) < 30: return None
        df_5m.columns = [c.lower() for c in df_5m.columns]

        res_15m = dhan.get_intraday_data(sec_id, exch_seg, inst_type, from_date, to_date, "15")
        htf_trend = "NEUTRAL"
        if isinstance(res_15m, dict) and res_15m.get('status') == 'success' and res_15m.get('data'):
            df_15m = pd.DataFrame(res_15m['data'])
            df_15m.columns = [c.lower() for c in df_15m.columns]
            htf_trend = calculate_htf_trend(df_15m)

        bullish_sweep, bearish_sweep = detect_liquidity_sweep(df_5m)
        bullish_choch, bearish_choch = detect_choch_and_ob(df_5m)
        current_price = float(df_5m.iloc[-1]['close'])
        signal, setup_type, option_type = "NEUTRAL", "", ""
        spot_sl, spot_target = 0.0, 0.0

        for idx in range(len(df_5m)-6, len(df_5m)-1):
            c1_high, c1_low = df_5m.iloc[idx-2]['high'], df_5m.iloc[idx-2]['low']
            c3_high, c3_low = df_5m.iloc[idx]['high'], df_5m.iloc[idx]['low']

            if c3_low > c1_high:
                fvg_low, fvg_high = c1_high, c3_low
                if fvg_low <= current_price <= (fvg_high * 1.0025):
                    if htf_trend in ["BULLISH", "NEUTRAL"]:
                        signal = "BUY CE"
                        option_type = "CE"
                        spot_sl = round(fvg_low * 0.996, 2)
                        risk_spot = current_price - spot_sl
                        spot_target = round(current_price + (2.5 * risk_spot), 2)
                        setup_type = "Bullish FVG + HTF Alignment"
                        if bullish_sweep: setup_type += " + Liq Sweep"
                        if bullish_choch: setup_type += " + CHoCH"
                        break

            elif c3_high < c1_low:
                fvg_low, fvg_high = c3_high, c1_low
                if (fvg_low * 0.9975) <= current_price <= fvg_high:
                    if htf_trend in ["BEARISH", "NEUTRAL"]:
                        signal = "BUY PE"
                        option_type = "PE"
                        spot_sl = round(fvg_high * 1.004, 2)
                        risk_spot = spot_sl - current_price
                        spot_target = round(current_price - (2.5 * risk_spot), 2)
                        setup_type = "Bearish FVG + HTF Alignment"
                        if bearish_sweep: setup_type += " + Liq Sweep"
                        if bearish_choch: setup_type += " + CHoCH"
                        break

        if signal != "NEUTRAL":
            strike_step = 50 if "NIFTY" in symbol else (100 if "BANK" in symbol else 10)
            atm_strike = round(current_price / strike_step) * strike_step
            strike_label = f"{atm_strike} {option_type}"

            est_option_premium = round(current_price * 0.012, 2)
            spot_risk = abs(current_price - spot_sl)
            spot_reward = abs(spot_target - current_price)

            opt_sl_gap = round(spot_risk * delta, 2)
            opt_target_gap = round(spot_reward * delta, 2)

            opt_entry = est_option_premium
            opt_sl = round(max(1.0, opt_entry - opt_sl_gap), 2)
            opt_target = round(opt_entry + opt_target_gap, 2)

            max_risk_amount = round(capital * (max_risk_pct / 100.0), 2)
            single_share_risk = max(1.0, opt_entry - opt_sl)
            max_shares = int(max_risk_amount / single_share_risk)
            
            unit_lot_size = LOT_SIZES.get(symbol, 50)
            recommended_lots = max(1, math.floor(max_shares / unit_lot_size))
            total_quantity = recommended_lots * unit_lot_size

            return {
                "Symbol": symbol,
                "SecurityID": sec_id,
                "ExchSegment": exch_seg,
                "Signal": signal,
                "Strike": strike_label,
                "Spot Price": round(current_price, 2),
                "Opt Entry (₹)": opt_entry,
                "Opt StopLoss (₹)": opt_sl,
                "Opt Target (₹)": opt_target,
                "HTF Trend": htf_trend,
                "Lot Size": unit_lot_size,
                "Rec Lots": recommended_lots,
                "Total Qty": total_quantity,
                "Max Risk (₹)": max_risk_amount,
                "Setup Type": setup_type
            }
    except Exception:
        return None
    return None

# ==========================================
# 5. STREAMLIT UI & DASHBOARD REDESIGN
# ==========================================
st.set_page_config(page_title="SMC Institutional Terminal", layout="wide", initial_sidebar_state="expanded")

# CUSTOM EXECUTIVE DARK THEME STYLING
st.markdown("""
<style>
    /* Dark Theme Background */
    .stApp {
        background-color: #0b0e14;
        color: #e0e6ed;
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    }
    /* Sidebar Styling */
    section[data-testid="stSidebar"] {
        background-color: #121721 !important;
        border-right: 1px solid #1e2638;
    }
    /* Executive Card Container */
    .signal-card {
        background: linear-gradient(135deg, #151c28 0%, #10141e 100%);
        border: 1px solid #232d42;
        border-radius: 12px;
        padding: 20px;
        margin-bottom: 20px;
        box-shadow: 0 4px 20px rgba(0,0,0,0.3);
    }
    /* Badge Pills */
    .badge-ce {
        background-color: #00e676;
        color: #000000;
        padding: 4px 12px;
        border-radius: 6px;
        font-weight: 800;
        font-size: 14px;
    }
    .badge-pe {
        background-color: #ff5252;
        color: #ffffff;
        padding: 4px 12px;
        border-radius: 6px;
        font-weight: 800;
        font-size: 14px;
    }
    .badge-htf {
        background-color: #1e293b;
        color: #38bdf8;
        border: 1px solid #0284c7;
        padding: 3px 10px;
        border-radius: 6px;
        font-size: 12px;
        font-weight: 600;
    }
    /* Metric Typography */
    .metric-label {
        color: #8a99ad;
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    .metric-value {
        color: #ffffff;
        font-size: 20px;
        font-weight: 700;
    }
</style>
""", unsafe_allow_html=True)

# Load Saved Config
saved_client_id = get_config("dhan_client_id", "")
saved_access_token = get_config("dhan_access_token", "")
saved_bot_token = get_config("telegram_bot_token", "")
saved_chat_id = get_config("telegram_chat_id", "")

# Sidebar Control Room
st.sidebar.markdown("### 🏛️ **Institutional Terminal**")

with st.sidebar.expander("🔑 Dhan API Gateway", expanded=not bool(saved_client_id)):
    client_id = st.text_input("Client ID", value=saved_client_id, type="password")
    access_token = st.text_input("Access Token", value=saved_access_token, type="password")
    col_v1, col_v2 = st.columns(2)
    with col_v1:
        if st.button("💾 Save", use_container_width=True):
            set_config("dhan_client_id", client_id)
            set_config("dhan_access_token", access_token)
            st.toast("Credentials Saved!", icon="✅")
    with col_v2:
        if st.button("🔌 Test", use_container_width=True):
            client = NativeDhanClient(client_id, access_token)
            ok, msg = client.validate_connection()
            if ok: st.success("Connected!")
            else: st.error("Failed!")

st.sidebar.markdown("---")
st.sidebar.markdown("##### 🛡️ **Risk Engine**")
capital = st.sidebar.number_input("Capital (₹)", value=200000, step=25000)
max_risk_pct = st.sidebar.slider("Max Risk / Trade (%)", 0.5, 5.0, 1.0, 0.25)
opt_delta = st.sidebar.slider("Option Delta", 0.30, 0.90, 0.50, 0.05)
timeframe = st.sidebar.selectbox("Signal Timeframe", ["3", "5", "15"], index=1)

st.sidebar.markdown("---")
with st.sidebar.expander("📱 Telegram Alerts Config", expanded=False):
    bot_token = st.text_input("Bot Token", value=saved_bot_token)
    chat_id = st.text_input("Chat ID", value=saved_chat_id)
    if st.button("💾 Save Telegram Config", use_container_width=True):
        set_config("telegram_bot_token", bot_token)
        set_config("telegram_chat_id", chat_id)
        st.toast("Telegram Saved!", icon="📲")

st.sidebar.markdown("---")
auto_refresh = st.sidebar.checkbox("🔁 Enable Live Auto-Scan")
refresh_interval = st.sidebar.selectbox("Interval (Sec)", [30, 60, 180], index=1)

# Main Navigation Bar
tab_scanner, tab_paper, tab_journal, tab_db = st.tabs([
    "⚡ LIVE SCANNER", "📄 PAPER DESK", "📊 ANALYTICS & JOURNAL", "💾 SIGNAL DB LOGS"
])

scrip_master = fetch_dhan_scrip_master()
FNO_UNIVERSE = ["NIFTY", "BANKNIFTY", "FINNIFTY", "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN", "BHARTIARTL", "LT"]

# ------------------------------------------
# TAB 1: LIVE SMC SCANNER & EXECUTION
# ------------------------------------------
with tab_scanner:
    st.markdown("## 🎯 Live Smart Money Concept Terminal")
    st.caption("Scans FVG, Liquidity Sweeps & CHoCH with Anti-Duplicate Alert Memory & One-Click Live Execution")

    if st.button("🚀 TRIGGER SCANNER NOW", use_container_width=True) or auto_refresh:
        if not client_id or not access_token:
            st.error("⚠️ Please configure Dhan API Credentials in the sidebar.")
        else:
            dhan = NativeDhanClient(client_id, access_token)
            with st.spinner("Analyzing Market Structure & Imbalance Zones..."):
                signals = []
                with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
                    futures = [
                        executor.submit(run_smc_analysis, dhan, sym, scrip_master[sym], timeframe, capital, max_risk_pct, opt_delta)
                        for sym in FNO_UNIVERSE if sym in scrip_master
                    ]
                    for f in concurrent.futures.as_completed(futures):
                        res = f.result()
                        if res: signals.append(res)

                if signals:
                    st.markdown(f"##### 🟢 **Detected {len(signals)} Valid Institutional Setups**")
                    
                    for sig in signals:
                        badge_class = "badge-ce" if "CE" in sig['Signal'] else "badge-pe"
                        
                        # Check Anti-Duplicate System
                        duplicate_flag = is_duplicate_signal(sig['Symbol'], sig['Signal'], sig['Strike'], cooldown_minutes=15)

                        st.markdown(f"""
                        <div class="signal-card">
                            <div style="display: flex; justify-content: space-between; align-items: center;">
                                <div>
                                    <span style="font-size: 22px; font-weight: 800; color: #fff;">{sig['Symbol']}</span>
                                    &nbsp; <span class="{badge_class}">{sig['Signal']}</span>
                                    &nbsp; <span style="font-size: 18px; color: #38bdf8; font-weight: 700;">{sig['Strike']}</span>
                                </div>
                                <div>
                                    <span class="badge-htf">HTF Trend: {sig['HTF Trend']}</span>
                                </div>
                            </div>
                            <hr style="border-color: #232d42; margin: 12px 0;">
                            <div style="display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px;">
                                <div><div class="metric-label">Spot Price</div><div class="metric-value">₹{sig['Spot Price']}</div></div>
                                <div><div class="metric-label">Opt Entry</div><div class="metric-value" style="color: #38bdf8;">₹{sig['Opt Entry (₹)']}</div></div>
                                <div><div class="metric-label">Opt StopLoss</div><div class="metric-value" style="color: #ff5252;">₹{sig['Opt StopLoss (₹)']}</div></div>
                                <div><div class="metric-label">Opt Target</div><div class="metric-value" style="color: #00e676;">₹{sig['Opt Target (₹)']}</div></div>
                                <div><div class="metric-label">Order Sizing</div><div class="metric-value">{sig['Total Qty']} ({sig['Rec Lots']} Lots)</div></div>
                            </div>
                            <div style="margin-top: 10px; font-size: 13px; color: #94a3b8;">
                                💡 <b>Setup:</b> {sig['Setup Type']} | 🛡️ <b>Max Risk:</b> ₹{sig['Max Risk (₹)']}
                            </div>
                        </div>
                        """, unsafe_allow_html=True)

                        col_act1, col_act2, col_act3 = st.columns([2, 2, 3])

                        # 1-CLICK PAPER TRADE
                        with col_act1:
                            if st.button(f"📄 Paper Trade ({sig['Symbol']})", key=f"paper_{sig['Symbol']}"):
                                conn = sqlite3.connect(DB_FILE)
                                conn.cursor().execute('''
                                    INSERT INTO paper_trades (symbol, strike, trade_type, qty, entry_price, status, setup_tag)
                                    VALUES (?, ?, ?, ?, ?, 'OPEN', ?)
                                ''', (sig['Symbol'], sig['Strike'], sig['Signal'], sig['Total Qty'], sig['Opt Entry (₹)'], sig['Setup Type']))
                                conn.commit()
                                conn.close()
                                st.toast(f"Paper Trade Opened for {sig['Symbol']}!", icon="✅")

                        # 1-CLICK LIVE TRADE EXECUTION VIA DHAN API
                        with col_act2:
                            if st.button(f"🔥 LIVE TRADE ({sig['Symbol']})", key=f"live_{sig['Symbol']}", type="primary"):
                                border_res = dhan.execute_live_order(
                                    security_id=sig['SecurityID'],
                                    exchange_segment=sig['ExchSegment'],
                                    transaction_type="BUY",
                                    quantity=sig['Total Qty'],
                                    order_type="MARKET"
                                )
                                if border_res.get("orderStatus") in ["SUCCESS", "PENDING", "TRANSIT"]:
                                    st.success(f"🔥 LIVE ORDER PLACED! Order ID: {border_res.get('orderId')}")
                                else:
                                    st.error(f"Live Execution Failed: {border_res.get('remarks', 'Rejected')}")

                        # ANTI-DUPLICATE TELEGRAM DISPATCH
                        with col_act3:
                            if duplicate_flag:
                                st.caption("🔁 *Telegram alert sent recently (Co-oldown active)*")
                            else:
                                if saved_bot_token and saved_chat_id:
                                    alert_msg = (
                                        f"🎯 *NEW SMC SIGNAL DETECTED*\n\n"
                                        f"*Symbol:* {sig['Symbol']}\n"
                                        f"*Signal:* {sig['Signal']} ({sig['Strike']})\n"
                                        f"*Opt Entry:* ₹{sig['Opt Entry (₹)']}\n"
                                        f"*Opt SL:* ₹{sig['Opt StopLoss (₹)']}\n"
                                        f"*Opt Target:* ₹{sig['Opt Target (₹)']}\n"
                                        f"*Sizing:* {sig['Total Qty']} Shares ({sig['Rec Lots']} Lots)\n"
                                        f"*Setup:* {sig['Setup Type']}"
                                    )
                                    ok = send_telegram_alert(saved_bot_token, saved_chat_id, alert_msg)
                                    log_signal_to_db(sig, telegram_sent=1 if ok else 0)
                                    st.caption("📲 *Pushed to Telegram*")

                        st.markdown("<br>", unsafe_allow_html=True)
                else:
                    st.info("No active high-probability FVG retest setups detected at this time.")

    if auto_refresh:
        time.sleep(refresh_interval)
        st.rerun()

# ------------------------------------------
# TAB 2: PAPER TRADING DESK
# ------------------------------------------
with tab_paper:
    st.markdown("### 📄 Paper Trading Terminal")
    
    conn = sqlite3.connect(DB_FILE)
    df_open = pd.read_sql_query("SELECT * FROM paper_trades WHERE status = 'OPEN' ORDER BY timestamp DESC", conn)
    conn.close()

    if not df_open.empty:
        st.markdown("##### 🟢 **Active Open Positions**")
        st.dataframe(df_open[['id', 'timestamp', 'symbol', 'strike', 'trade_type', 'qty', 'entry_price', 'setup_tag']], use_container_width=True)

        col_c1, col_c2, col_c3 = st.columns(3)
        with col_c1:
            trade_id_to_close = st.number_input("Position ID to Exit", min_value=1, step=1)
        with col_c2:
            exit_premium = st.number_input("Exit Premium Price (₹)", value=150.0, step=1.0)
        with col_c3:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("❌ Close Position & Log Journal", use_container_width=True):
                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()
                trade = c.execute("SELECT symbol, trade_type, qty, entry_price, setup_tag FROM paper_trades WHERE id = ?", (trade_id_to_close,)).fetchone()
                
                if trade:
                    sym, t_type, qty, entry_p, setup_tag = trade
                    realized_pnl = round((exit_premium - entry_p) * qty, 2)
                    c.execute("UPDATE paper_trades SET exit_price = ?, pnl = ?, status = 'CLOSED' WHERE id = ?", (exit_premium, realized_pnl, trade_id_to_close))
                    c.execute('''
                        INSERT INTO trade_journal (symbol, trade_type, entry_price, exit_price, qty, pnl, setup_tag, rating, notes, execution_type)
                        VALUES (?, ?, ?, ?, ?, ?, ?, 5, 'Closed via Paper Desk', 'PAPER')
                    ''', (sym, t_type, entry_p, exit_premium, qty, realized_pnl, setup_tag))
                    conn.commit()
                    st.success(f"Position #{trade_id_to_close} Closed! P&L: ₹{realized_pnl:,.2f}")
                else:
                    st.error("Invalid Trade ID.")
                conn.close()
                st.rerun()
    else:
        st.info("No active open paper trades.")

    st.markdown("---")
    st.markdown("##### 🏁 **Closed Paper Trades History**")
    conn = sqlite3.connect(DB_FILE)
    df_closed = pd.read_sql_query("SELECT * FROM paper_trades WHERE status = 'CLOSED' ORDER BY timestamp DESC", conn)
    conn.close()
    if not df_closed.empty:
        st.dataframe(df_closed, use_container_width=True)

# ------------------------------------------
# TAB 3: ANALYTICS & JOURNAL
# ------------------------------------------
with tab_journal:
    st.markdown("### 📊 Performance Analytics & Executive Journal")

    conn = sqlite3.connect(DB_FILE)
    df_j = pd.read_sql_query("SELECT * FROM trade_journal ORDER BY timestamp ASC", conn)
    conn.close()

    if not df_j.empty:
        df_j['timestamp'] = pd.to_datetime(df_j['timestamp'])
        df_j['cumulative_pnl'] = df_j['pnl'].cumsum()
        
        wins = len(df_j[df_j['pnl'] > 0])
        losses = len(df_j[df_j['pnl'] <= 0])
        total_trades = len(df_j)
        win_rate = round((wins / total_trades) * 100, 2) if total_trades > 0 else 0
        total_pnl = df_j['pnl'].sum()

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Cumulative Realized P&L", f"₹{total_pnl:,.2f}")
        m2.metric("Win Rate (%)", f"{win_rate}%")
        m3.metric("Total Trades", total_trades)
        m4.metric("Profit Factor", f"{round(abs(df_j[df_j['pnl']>0]['pnl'].sum() / (df_j[df_j['pnl']<=0]['pnl'].sum() or 1)), 2)}")

        col_g1, col_g2 = st.columns(2)
        with col_g1:
            st.markdown("##### 📈 **Equity Curve (₹)**")
            st.line_chart(df_j.set_index("timestamp")[["cumulative_pnl"]], color="#00e676")

        with col_g2:
            st.markdown("##### 🎯 **Win vs Loss Count**")
            wl_df = pd.DataFrame({"Trades": [wins, losses]}, index=["Wins 🎯", "Losses ❌"])
            st.bar_chart(wl_df, color="#00e676")

        st.markdown("##### 📖 **Complete Trade Logs**")
        st.dataframe(df_j.sort_values(by="timestamp", ascending=False), use_container_width=True)
    else:
        st.info("No journal records logged yet.")

# ------------------------------------------
# TAB 4: SYSTEM DB LOGS
# ------------------------------------------
with tab_db:
    st.markdown("### 💾 Terminal Signal Database")
    conn = sqlite3.connect(DB_FILE)
    df_sig_db = pd.read_sql_query("SELECT * FROM signal_history ORDER BY timestamp DESC", conn)
    conn.close()
    
    if not df_sig_db.empty:
        st.dataframe(df_sig_db, use_container_width=True)
    else:
        st.info("No signals stored in database history yet.")
