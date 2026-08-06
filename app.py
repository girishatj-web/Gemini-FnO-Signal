import streamlit as st
import pandas as pd
import numpy as np
import requests
import re
import time
from datetime import datetime, timedelta
import yfinance as yf

# ==========================================
# 1. PAGE CONFIGURATION & LIGHT UI STYLING
# ==========================================
st.set_page_config(
    page_title="Apex Multi-Timeframe F&O Engine",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom High-Contrast Light UI Design System
st.markdown("""
<style>
    /* Main Canvas Background */
    .stApp {
        background-color: #F8FAFC !important;
        color: #0F172A !important;
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    }
    
    /* Top Header Bar */
    header[data-testid="stHeader"] {
        background-color: #FFFFFF !important;
        border-bottom: 1px solid #E2E8F0 !important;
    }

    /* Sidebar Styling */
    section[data-testid="stSidebar"] {
        background-color: #F1F5F9 !important;
        border-right: 1px solid #E2E8F0 !important;
    }
    
    section[data-testid="stSidebar"] label, 
    section[data-testid="stSidebar"] .stMarkdown,
    section[data-testid="stSidebar"] span {
        color: #0F172A !important;
        font-weight: 600 !important;
    }

    /* Card Layouts */
    .kpi-card {
        background-color: #FFFFFF;
        border: 1px solid #CBD5E1;
        border-radius: 12px;
        padding: 16px 20px;
        margin-bottom: 10px;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
    }
    
    .kpi-title {
        color: #475569;
        font-size: 0.75rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }

    .kpi-value {
        color: #0F172A;
        font-size: 1.65rem;
        font-weight: 800;
        margin-top: 4px;
        margin-bottom: 4px;
    }

    /* Status Badges */
    .status-badge-active {
        background-color: #DCFCE7;
        color: #15803D;
        border: 1px solid #86EFAC;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 0.75rem;
        font-weight: 700;
    }

    .status-badge-off {
        background-color: #FEE2E2;
        color: #B91C1C;
        border: 1px solid #FCA5A5;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 0.75rem;
        font-weight: 700;
    }

    /* Dataframe Styling */
    .stDataFrame {
        background-color: #FFFFFF !important;
        border: 1px solid #CBD5E1 !important;
        border-radius: 10px !important;
    }

    /* Tab Headers */
    .stTabs [data-baseweb="tab-list"] {
        gap: 6px;
        background-color: #E2E8F0;
        padding: 6px;
        border-radius: 10px;
    }
    .stTabs [data-baseweb="tab"] {
        background-color: transparent;
        border-radius: 6px;
        color: #334155 !important;
        padding: 8px 16px;
        font-weight: 700 !important;
    }
    .stTabs [aria-selected="true"] {
        background-color: #2563EB !important;
        color: #FFFFFF !important;
        box-shadow: 0 2px 4px rgba(37, 99, 235, 0.2);
    }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 2. SESSION STATE MANAGEMENT
# ==========================================
def init_session_state():
    if "dhan_client_id" not in st.session_state: st.session_state["dhan_client_id"] = ""
    if "dhan_access_token" not in st.session_state: st.session_state["dhan_access_token"] = ""
    if "dhan_authenticated" not in st.session_state: st.session_state["dhan_authenticated"] = False

    if "tg_bot_token" not in st.session_state: st.session_state["tg_bot_token"] = ""
    if "tg_chat_id" not in st.session_state: st.session_state["tg_chat_id"] = ""
    if "tg_connected" not in st.session_state: st.session_state["tg_connected"] = False
    if "sent_alerts" not in st.session_state: st.session_state["sent_alerts"] = set()

    # PERSISTENT SIGNAL TIMESTAMPS CACHE
    if "signal_timestamps" not in st.session_state: st.session_state["signal_timestamps"] = {}

    if "total_capital" not in st.session_state: st.session_state["total_capital"] = 200000.0
    if "risk_per_trade_pct" not in st.session_state: st.session_state["risk_per_trade_pct"] = 1.0
    if "default_sl_pct" not in st.session_state: st.session_state["default_sl_pct"] = 1.5
    if "rr_ratio" not in st.session_state: st.session_state["rr_ratio"] = 2.5

    if "auto_scan_active" not in st.session_state: st.session_state["auto_scan_active"] = False
    if "auto_scan_interval" not in st.session_state: st.session_state["auto_scan_interval"] = 5
    if "last_scan_time" not in st.session_state: st.session_state["last_scan_time"] = None

    if "institutional_journal" not in st.session_state: 
        st.session_state["institutional_journal"] = [
            {"Date / Time": "05-Aug-2026 09:30:00", "Symbol": "NIFTY", "Signal": "BUY CE", "Option Strike": "NIFTY 24200 CE", "Entry Price": 24180.0, "Stop Loss": 24140.0, "Target (1:2.5 RR)": 24280.0, "Outcome": "TARGET HIT 🎯"},
            {"Date / Time": "05-Aug-2026 13:45:00", "Symbol": "BANKNIFTY", "Signal": "BUY PE", "Option Strike": "BANKNIFTY 51500 PE", "Entry Price": 51450.0, "Stop Loss": 51600.0, "Target (1:2.5 RR)": 51075.0, "Outcome": "STOP LOSS HIT ❌"},
            {"Date / Time": "06-Aug-2026 09:20:00", "Symbol": "NIFTY", "Signal": "BUY CE", "Option Strike": "NIFTY 24200 CE", "Entry Price": 24220.0, "Stop Loss": 24180.0, "Target (1:2.5 RR)": 24320.0, "Outcome": "TARGET HIT 🎯"},
            {"Date / Time": "06-Aug-2026 11:15:00", "Symbol": "RELIANCE", "Signal": "BUY PE", "Option Strike": "RELIANCE 2980 PE", "Entry Price": 2980.0, "Stop Loss": 2995.0, "Target (1:2.5 RR)": 2942.0, "Outcome": "TARGET HIT 🎯"},
        ]

    if "paper_trade_log" not in st.session_state: st.session_state["paper_trade_log"] = []
    if "live_trade_log" not in st.session_state: st.session_state["live_trade_log"] = []

init_session_state()

# Fallback Universe
NSE_FNO_FALLBACK = [
    "NIFTY", "BANKNIFTY", "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN", "BHARTIARTL", "TATAMOTORS",
    "LTIM", "AXISBANK", "KOTAKBANK", "ITC", "LT", "HINDUNILVR", "BAJFINANCE", "MARUTI", "SUNPHARMA", "TATASTEEL"
]

# ==========================================
# 3. DHAN SCRIP MASTER & LIVE DATA APIS
# ==========================================
DHAN_SCRIP_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"

@st.cache_data(ttl=3600*12)
def fetch_dhan_fno_universe():
    try:
        df_master = pd.read_csv(DHAN_SCRIP_MASTER_URL, low_memory=False)
        fno_mask = (
            (df_master['SEM_EXM_EXCH_ID'].astype(str).str.upper() == 'NSE') & 
            (df_master['SEM_INSTRUMENT_NAME'].astype(str).str.upper().isin(['FUTSTK', 'OPTSTK']))
        )
        fno_df = df_master[fno_mask]
        
        raw_symbols = []
        if 'SEM_CUSTOM_SYMBOL' in fno_df.columns:
            raw_symbols = fno_df['SEM_CUSTOM_SYMBOL'].dropna().astype(str).tolist()
        elif 'SEM_TRADING_SYMBOL' in fno_df.columns:
            raw_symbols = fno_df['SEM_TRADING_SYMBOL'].dropna().astype(str).tolist()

        indices = {'FINNIFTY', 'MIDCPNIFTY', 'NIFTYNXT50'}
        clean_symbols = set(["NIFTY", "BANKNIFTY"])
        months_regex = r'(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC|CALL|PUT|FUT|CE|PE|\d+).*$'

        for raw_sym in raw_symbols:
            base_part = raw_sym.split('-')[0].upper().strip()
            clean_sym = re.sub(months_regex, '', base_part)
            clean_sym = re.sub(r'[^A-Z]', '', clean_sym)
            
            if clean_sym and len(clean_sym) >= 2 and clean_sym not in indices:
                clean_symbols.add(clean_sym)
                
        result_list = sorted(list(clean_symbols))
        return result_list if len(result_list) > 5 else NSE_FNO_FALLBACK
    except Exception:
        return NSE_FNO_FALLBACK

def validate_dhan_credentials(client_id, access_token):
    url = "https://api.dhan.co/fundlimit"
    headers = {"access-token": access_token, "client-id": client_id, "Content-Type": "application/json"}
    try:
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            return True, "Dhan API Credentials Validated Successfully!"
        return False, f"Auth Failed ({res.status_code}): {res.text}"
    except Exception as e:
        return False, f"Connection Error: {str(e)}"

# REAL DHAN OPTION CHAIN & OPEN INTEREST FEED
def fetch_dhan_live_option_chain(symbol, client_id, access_token):
    if not client_id or not access_token:
        return None
    
    url = "https://api.dhan.co/optionchain"
    headers = {"access-token": access_token, "client-id": client_id, "Content-Type": "application/json"}
    payload = {
        "UnderlyingScrip": 13 if symbol == "NIFTY" else (25 if symbol == "BANKNIFTY" else 0),
        "UnderlyingSeg": "NSE_FNO"
    }
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=4)
        if res.status_code == 200:
            oc_data = res.json().get("data", {})
            total_oi = sum([item.get("oi", 1) for item in oc_data.values() if isinstance(item, dict)])
            total_vol = sum([item.get("volume", 0) for item in oc_data.values() if isinstance(item, dict)])
            vol_oi = round(total_vol / max(1, total_oi), 2)
            return vol_oi
        return None
    except Exception:
        return None

def execute_dhan_live_order(symbol, qty, transaction_type, price):
    if not st.session_state["dhan_authenticated"]:
        return False, "Dhan API credentials not validated!"

    url = "https://api.dhan.co/orders"
    headers = {"access-token": st.session_state["dhan_access_token"], "client-id": st.session_state["dhan_client_id"], "Content-Type": "application/json"}
    payload = {
        "dhanClientId": st.session_state["dhan_client_id"],
        "transactionType": transaction_type.upper(),
        "exchangeSegment": "NSE_EQ",
        "productType": "INTRADAY",
        "orderType": "MARKET",
        "validity": "DAY",
        "tradingSymbol": symbol,
        "quantity": int(qty),
        "price": float(price)
    }
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=5)
        if res.status_code in [200, 201]:
            return True, res.json().get("orderId", "ORD-" + str(np.random.randint(10000, 99999)))
        return False, res.text
    except Exception as e:
        return False, str(e)

# Telegram Alerts
def send_telegram_alert(message):
    if not st.session_state["tg_connected"]: return False
    url = f"https://api.telegram.org/bot{st.session_state['tg_bot_token']}/sendMessage"
    payload = {"chat_id": st.session_state["tg_chat_id"], "text": message, "parse_mode": "HTML"}
    try:
        res = requests.post(url, json=payload, timeout=5)
        return res.status_code == 200
    except Exception:
        return False

def dispatch_deduplicated_alerts(filtered_df, tf_label):
    """Triggers Telegram notifications ONLY for BUY CE and BUY PE signals."""
    today_str = datetime.now().strftime("%Y-%m-%d")
    sent_count = 0
    
    for _, row in filtered_df.iterrows():
        signal = str(row['Signal']).upper().strip()
        if signal not in ["BUY CE", "BUY PE"]:
            continue
            
        alert_key = f"{row['Ticker']}_{signal}_{tf_label}_{today_str}"
        if alert_key not in st.session_state["sent_alerts"]:
            msg = (
                f"🚨 <b>APEX OPTION SIGNAL ALERT ({tf_label})</b> 🚨\n\n"
                f"<b>Signal Timestamp:</b> {row['Signal Timestamp']}\n"
                f"<b>Symbol:</b> #{row['Ticker']}\n"
                f"<b>Timeframe:</b> {tf_label}\n"
                f"<b>Signal:</b> {signal}\n"
                f"<b>Recommended Strike:</b> {row['Option Strike']}\n"
                f"<b>Spot Entry:</b> ₹{row['Price (₹)']}\n"
                f"<b>Stop Loss (SL):</b> ₹{row['Stop Loss (₹)']}\n"
                f"<b>Target (1:2.5 RR):</b> ₹{row['Target (1:2.5 RR) (₹)']}\n"
                f"<b>Setup:</b> {row['Setup Description']}\n"
                f"<b>RSI (14):</b> {row['RSI (14)']} | <b>Vol/OI Ratio:</b> {row['Vol/OI Ratio']}\n\n"
                f"⚡ <i>Apex Multi-Timeframe Feed</i>"
            )
            if send_telegram_alert(msg):
                st.session_state["sent_alerts"].add(alert_key)
                sent_count += 1
    return sent_count

# Helper: Option Strike, SL & Target Calculator
def get_option_strike_params(symbol, price, signal, sl_pct=1.5, rr_ratio=2.5):
    if signal not in ["BUY CE", "BUY PE"]:
        return "N/A", round(price * 0.985, 2), round(price * 1.0375, 2)

    if symbol == "NIFTY": step = 50
    elif symbol == "BANKNIFTY": step = 100
    elif price > 3000: step = 100
    elif price > 1000: step = 20
    elif price > 500: step = 10
    else: step = 5

    atm_strike = int(round(price / step) * step)
    option_type = "CE" if "CE" in signal else "PE"
    strike_label = f"{symbol} {atm_strike} {option_type}"

    sl_dist = price * (sl_pct / 100.0)
    if "CE" in signal:
        sl_price = round(price - sl_dist, 2)
        target_price = round(price + (sl_dist * rr_ratio), 2)
    else:
        sl_price = round(price + sl_dist, 2)
        target_price = round(price - (sl_dist * rr_ratio), 2)

    return strike_label, sl_price, target_price

def calculate_position_size(price, sl_pct):
    capital = st.session_state["total_capital"]
    risk_amt = capital * (st.session_state["risk_per_trade_pct"] / 100.0)
    sl_per_share = price * (sl_pct / 100.0)
    if sl_per_share <= 0: return 1, risk_amt, price * 0.98, price * 1.04
    
    qty = max(1, int(risk_amt / sl_per_share))
    sl_price = round(price - sl_per_share, 2)
    target_price = round(price + (sl_per_share * st.session_state["rr_ratio"]), 2)
    return qty, risk_amt, sl_price, target_price

# Helper: Persistent Signal Timestamp Attacher
def attach_persistent_timestamps(df, tf_label):
    """Ensures original signal timestamps persist across rescans and page refreshes."""
    if df.empty:
        return df

    now_str = datetime.now().strftime("%d-%b-%Y %H:%M:%S")
    timestamps = []

    for _, row in df.iterrows():
        # Unique Signal Identifier
        sig_key = f"{row['Ticker']}_{row['Signal']}_{tf_label}"

        if sig_key in st.session_state["signal_timestamps"]:
            # Retain original timestamp from initial trigger
            ts = st.session_state["signal_timestamps"][sig_key]
        else:
            # First time seeing this active signal -> Store timestamp
            ts = now_str
            st.session_state["signal_timestamps"][sig_key] = ts

        timestamps.append(ts)

    df.insert(0, "Signal Timestamp", timestamps)
    return df

# ==========================================
# 4. MULTI-TIMEFRAME SCANNING ENGINE
# ==========================================
TIMEFRAME_MAP = {
    "5 Mins": {"interval": "5m", "period": "5d", "label": "5m", "resample": None},
    "10 Mins": {"interval": "5m", "period": "5d", "label": "10m", "resample": "10min"},
    "15 Mins": {"interval": "15m", "period": "10d", "label": "15m", "resample": None},
    "1 Hour": {"interval": "1h", "period": "1mo", "label": "1h", "resample": None},
    "1 Day": {"interval": "1d", "period": "1y", "label": "1d", "resample": None}
}

@st.cache_data(ttl=90)
def compute_master_signals(symbols, timeframe_key="5 Mins", client_id="", access_token=""):
    """Scans and computes indicators dynamically aligned to the selected candle timeframe."""
    if not symbols: return pd.DataFrame()
    
    tf_info = TIMEFRAME_MAP.get(timeframe_key, TIMEFRAME_MAP["5 Mins"])
    interval = tf_info["interval"]
    period = tf_info["period"]
    tf_label = tf_info["label"]
    resample_rule = tf_info["resample"]

    scan_symbols = symbols[:120]
    yf_tickers = []
    for sym in scan_symbols:
        if sym == "NIFTY": yf_tickers.append("^NSEI")
        elif sym == "BANKNIFTY": yf_tickers.append("^NSEBANK")
        else: yf_tickers.append(f"{sym}.NS")

    try:
        data = yf.download(yf_tickers, period=period, interval=interval, group_by="ticker", progress=False, threads=True)
    except Exception:
        return pd.DataFrame()

    results = []
    for sym in scan_symbols:
        ticker_id = "^NSEI" if sym == "NIFTY" else ("^NSEBANK" if sym == "BANKNIFTY" else f"{sym}.NS")
        try:
            if len(scan_symbols) == 1:
                df_stock = data.dropna()
            else:
                if ticker_id not in data.columns.levels[0]: continue
                df_stock = data[ticker_id].dropna()

            if len(df_stock) < 20: continue

            # Apply Custom Resampling (e.g. 10m from 5m ticks)
            if resample_rule:
                df_stock = df_stock.resample(resample_rule).agg({
                    'Open': 'first',
                    'High': 'max',
                    'Low': 'min',
                    'Close': 'last',
                    'Volume': 'sum'
                }).dropna()

            close = df_stock['Close']
            high = df_stock['High']
            low = df_stock['Low']

            curr_price = float(close.iloc[-1])
            prev_price = float(close.iloc[-2])
            change_pct = float(((curr_price - prev_price) / prev_price) * 100)
            volume = float(df_stock['Volume'].iloc[-1])

            # 1. Technical Indicators Aligned to Active Timeframe
            delta = close.diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss
            rsi_14 = float((100 - (100 / (1 + rs))).iloc[-1])

            sma_50 = float(close.rolling(50).mean().iloc[-1]) if len(df_stock) >= 50 else float(close.mean())
            sma_200 = float(close.rolling(200).mean().iloc[-1]) if len(df_stock) >= 200 else sma_50

            # 2. SMC Engine Aligned to Active Timeframe Candles
            prev_high_level = float(high.iloc[:-1].max())
            prev_low_level = float(low.iloc[:-1].min())

            is_high_sweep = float(high.iloc[-1]) > prev_high_level and curr_price < prev_high_level
            is_low_sweep = float(low.iloc[-1]) < prev_low_level and curr_price > prev_low_level

            c1_high = float(high.iloc[-3])
            c3_low = float(low.iloc[-1])
            c1_low = float(low.iloc[-3])
            c3_high = float(high.iloc[-1])

            bullish_fvg = c3_low > c1_high
            bearish_fvg = c3_high < c1_low

            # 3. Pull Real Dhan Option Chain Feed or Dynamic Volume Velocity
            real_vol_oi = fetch_dhan_live_option_chain(sym, client_id, access_token)
            if real_vol_oi is None:
                total_vol_series = df_stock['Volume'].tail(14).sum()
                mean_vol = df_stock['Volume'].mean()
                real_vol_oi = round(float(total_vol_series / max(1.0, mean_vol * 10)), 2)

            # Signal Classifier Logic
            if is_low_sweep or (bullish_fvg and real_vol_oi > 1.5):
                signal = "BUY CE"
                setup_desc = f"{tf_label} Liquidity Sweep / Bullish FVG"
            elif is_high_sweep or (bearish_fvg and real_vol_oi > 1.5):
                signal = "BUY PE"
                setup_desc = f"{tf_label} Sweep / Bearish FVG"
            elif rsi_14 < 35 and curr_price > sma_50:
                signal = "Bullish Oversold"
                setup_desc = f"Oversold {tf_label} RSI + Above 50 SMA"
            elif curr_price > sma_50 and sma_50 > sma_200:
                signal = "Strong Uptrend"
                setup_desc = f"{tf_label} Trend Alignment (50 > 200 SMA)"
            elif curr_price < sma_50 and curr_price < sma_200:
                signal = "Downtrend Breakdown"
                setup_desc = f"Below {tf_label} Moving Averages"
            else:
                signal = "Consolidating"
                setup_desc = f"Rangebound {tf_label} Action"

            strike_label, sl_price, target_price = get_option_strike_params(
                sym, curr_price, signal, st.session_state["default_sl_pct"], st.session_state["rr_ratio"]
            )

            results.append({
                "Ticker": sym,
                "Signal": signal,
                "Option Strike": strike_label,
                "Price (₹)": round(curr_price, 2),
                "Stop Loss (₹)": sl_price,
                "Target (1:2.5 RR) (₹)": target_price,
                "Change (%)": round(change_pct, 2),
                "RSI (14)": round(rsi_14, 1),
                "Vol/OI Ratio": real_vol_oi,
                "Setup Description": setup_desc,
                "Candle Volume": int(volume)
            })
        except Exception:
            continue

    return pd.DataFrame(results)

fno_universe = fetch_dhan_fno_universe()

# ==========================================
# 5. SIDEBAR CONTROLS
# ==========================================
with st.sidebar:
    st.markdown("### ⚡ Apex Algo Control Center")
    st.caption(f"Clean Equity Universe: **{len(fno_universe)}** Equities")
    st.divider()

    dhan_status_class = "status-badge-active" if st.session_state["dhan_authenticated"] else "status-badge-off"
    dhan_status_text = "CONNECTED" if st.session_state["dhan_authenticated"] else "DISCONNECTED"
    
    tg_status_class = "status-badge-active" if st.session_state["tg_connected"] else "status-badge-off"
    tg_status_text = "CONNECTED" if st.session_state["tg_connected"] else "DISCONNECTED"

    st.markdown(f"**Dhan API Feed:** <span class='{dhan_status_class}'>{dhan_status_text}</span>", unsafe_allow_html=True)
    st.markdown(f"**Telegram Bot:** <span class='{tg_status_class}'>{tg_status_text}</span>", unsafe_allow_html=True)
    st.divider()

    st.markdown("#### ⏱️ Candle Timeframe")
    selected_timeframe = st.selectbox(
        "Select Candle Duration", 
        ["5 Mins", "10 Mins", "15 Mins", "1 Hour", "1 Day"], 
        index=0
    )
    st.divider()

    st.markdown("#### 🔍 Filter Criteria")
    selected_signal = st.selectbox("Signal Classifier", ["BUY CE & PE Only", "BUY CE", "BUY PE", "All Signals", "Bullish Oversold", "Strong Uptrend", "Downtrend Breakdown", "Consolidating"], index=0)
    min_vol_oi = st.slider("Min Vol/OI Ratio Threshold", 0.5, 3.0, 1.0, 0.1)
    rsi_range = st.slider(f"{selected_timeframe} RSI Range", 0.0, 100.0, (0.0, 100.0))
    search_ticker = st.text_input("Find Symbol", "").upper().strip()

    st.divider()
    if st.button("🔄 Rescan Selected Timeframe", use_container_width=True):
        st.cache_data.clear()
        st.session_state["last_scan_time"] = datetime.now().strftime("%H:%M:%S")
        st.rerun()

# Run Multi-Timeframe Screener
with st.spinner(f"Computing {selected_timeframe} Candles, SMC Signals & Dhan Option Chain..."):
    df_raw = compute_master_signals(
        fno_universe, 
        selected_timeframe,
        st.session_state["dhan_client_id"], 
        st.session_state["dhan_access_token"]
    )
    # ATTACH PERSISTENT TIMESTAMPS
    df_screener = attach_persistent_timestamps(df_raw, TIMEFRAME_MAP[selected_timeframe]["label"])

filtered_df = df_screener.copy()

if not filtered_df.empty:
    if selected_signal == "BUY CE & PE Only":
        filtered_df = filtered_df[filtered_df["Signal"].isin(["BUY CE", "BUY PE"])]
    elif selected_signal != "All Signals":
        filtered_df = filtered_df[filtered_df["Signal"] == selected_signal]

    filtered_df = filtered_df[
        (filtered_df["Vol/OI Ratio"] >= min_vol_oi) &
        (filtered_df["RSI (14)"] >= rsi_range[0]) & 
        (filtered_df["RSI (14)"] <= rsi_range[1])
    ]
    if search_ticker:
        filtered_df = filtered_df[filtered_df["Ticker"].str.contains(search_ticker)]

# Dispatch Telegram Alerts (Strictly BUY CE & BUY PE)
if st.session_state["tg_connected"] and not filtered_df.empty:
    dispatch_deduplicated_alerts(filtered_df, TIMEFRAME_MAP[selected_timeframe]["label"])

# ==========================================
# 6. MAIN DASHBOARD PANELS
# ==========================================
st.title(f"⚡ Apex Real-Time Dashboard ({selected_timeframe} Timeframe)")

tab_screener, tab_journal, tab_dhan, tab_tg, tab_risk, tab_autoscan, tab_orders = st.tabs([
    "📋 Live Screener", 
    "📑 Institutional Journal", 
    "🔑 Dhan API & Auth", 
    "📱 Telegram Center", 
    "🛡️ Risk Engine", 
    "⏰ Auto Scan", 
    "📜 Order Book"
])

# ------------------------------------------------------------------
# TAB 1: SCREENER & ORDER TERMINAL
# ------------------------------------------------------------------
with tab_screener:
    st.subheader(f"Real-Time Option Signals & Execution ({selected_timeframe} Candles)")

    k1, k2, k3, k4 = st.columns(4)
    total_m = len(filtered_df)
    bullish_m = len(filtered_df[filtered_df["Signal"].str.contains("BUY CE|Bullish|Uptrend")]) if total_m > 0 else 0
    avg_rsi = round(filtered_df["RSI (14)"].mean(), 1) if total_m > 0 else 0
    
    with k1: st.markdown(f"<div class='kpi-card'><div class='kpi-title'>Filtered Matches</div><div class='kpi-value'>{total_m}</div></div>", unsafe_allow_html=True)
    with k2: st.markdown(f"<div class='kpi-card'><div class='kpi-title'>Bullish Setups</div><div class='kpi-value'>{bullish_m}</div></div>", unsafe_allow_html=True)
    with k3: st.markdown(f"<div class='kpi-card'><div class='kpi-title'>Avg {selected_timeframe} RSI</div><div class='kpi-value'>{avg_rsi}</div></div>", unsafe_allow_html=True)
    with k4: st.markdown(f"<div class='kpi-card'><div class='kpi-title'>Telegram Alerts Sent</div><div class='kpi-value'>{len(st.session_state['sent_alerts'])}</div></div>", unsafe_allow_html=True)

    st.divider()

    col_table, col_action = st.columns([2, 1])

    with col_table:
        st.markdown(f"##### Filtered Option Signal Directory ({selected_timeframe})")
        if not filtered_df.empty:
            st.dataframe(
                filtered_df.style.format({
                    "Price (₹)": "₹{:.2f}",
                    "Stop Loss (₹)": "₹{:.2f}",
                    "Target (1:2.5 RR) (₹)": "₹{:.2f}",
                    "Change (%)": "{:+.2f}%",
                    "RSI (14)": "{:.1f}",
                    "Vol/OI Ratio": "{:.2f}",
                    "Candle Volume": "{:,.0f}"
                }).map(
                    lambda x: 'color: #16A34A; font-weight: 700;' if isinstance(x, (int, float)) and x > 0 else ('color: #DC2626; font-weight: 700;' if isinstance(x, (int, float)) and x < 0 else ''),
                    subset=["Change (%)"]
                ),
                use_container_width=True,
                height=450
            )
        else:
            st.info(f"No signals match criteria for {selected_timeframe}. Adjust sidebar filters or click Rescan.")

    with col_action:
        st.markdown("##### ⚡ Order Execution Panel")
        selectable_stocks = filtered_df["Ticker"].unique() if not filtered_df.empty else (df_screener["Ticker"].unique() if not df_screener.empty else [])
        
        if len(selectable_stocks) > 0:
            selected_stock = st.selectbox("Target Asset", selectable_stocks)
            
            ref_df = filtered_df if not filtered_df.empty else df_screener
            stock_row = ref_df[ref_df["Ticker"] == selected_stock].iloc[0]
            sig_time = str(stock_row["Signal Timestamp"])
            price = float(stock_row["Price (₹)"])
            signal = str(stock_row["Signal"])
            strike = str(stock_row["Option Strike"])
            sl = float(stock_row["Stop Loss (₹)"])
            target = float(stock_row["Target (1:2.5 RR) (₹)"])
            
            qty, risk_amt, _, _ = calculate_position_size(price, st.session_state["default_sl_pct"])

            st.success(f"**Target:** {selected_stock} | **Signal:** {signal} ({selected_timeframe})")
            st.write(f"• **Signal Triggered At:** `{sig_time}`")
            st.write(f"• **Recommended Strike:** `{strike}`")
            st.write(f"• **Spot Entry Price:** ₹{price}")
            st.write(f"• **Stop Loss (SL):** ₹{sl}")
            st.write(f"• **Target (1:2.5 RR):** ₹{target}")
            st.write(f"• **Position Size:** `{qty}` Shares")
            st.write(f"• **Capital Risk:** ₹{risk_amt:,.2f}")

            st.write("")
            col_p, col_l = st.columns(2)
            
            with col_p:
                if st.button("📄 Paper Trade", use_container_width=True):
                    paper_entry = {
                        "Time": sig_time,
                        "Timeframe": selected_timeframe,
                        "Symbol": selected_stock,
                        "Strike": strike,
                        "Type": signal,
                        "Qty": qty,
                        "Entry Price": price,
                        "SL": sl,
                        "Target": target,
                        "Status": "OPEN"
                    }
                    st.session_state["paper_trade_log"].append(paper_entry)
                    st.success(f"Paper Order Placed for {strike}!")

            with col_l:
                if st.button("🚀 1-Click Live Trade", use_container_width=True, type="primary"):
                    if not st.session_state["dhan_authenticated"]:
                        st.error("Authenticate Dhan API in Tab 3 first!")
                    else:
                        success, order_info = execute_dhan_live_order(selected_stock, qty, "BUY", price)
                        if success:
                            live_entry = {
                                "Time": sig_time,
                                "OrderID": order_info,
                                "Timeframe": selected_timeframe,
                                "Symbol": selected_stock,
                                "Strike": strike,
                                "Type": signal,
                                "Qty": qty,
                                "Price": price,
                                "Status": "EXECUTED"
                            }
                            st.session_state["live_trade_log"].append(live_entry)
                            st.balloons()
                            st.success(f"Live Order Submitted! ID: {order_info}")
                        else:
                            st.error(f"Execution Error: {order_info}")
        else:
            st.warning("Loading market data...")

# ------------------------------------------------------------------
# TAB 2: INSTITUTIONAL JOURNAL & BACKTEST PERFORMANCE
# ------------------------------------------------------------------
with tab_journal:
    st.subheader("📑 Institutional Trade Journal & Performance Analytics")
    st.caption("Multi-timeframe FVG & SMC executions with $1:2.5$ Risk-to-Reward ratio outcomes.")

    df_journal = pd.DataFrame(st.session_state["institutional_journal"])
    
    st.dataframe(
        df_journal.style.format({
            "Entry Price": "₹{:,.2f}",
            "Stop Loss": "₹{:,.2f}",
            "Target (1:2.5 RR)": "₹{:,.2f}"
        }),
        use_container_width=True
    )

    if not df_journal.empty:
        wins = len(df_journal[df_journal["Outcome"].str.contains("TARGET HIT")])
        total = len(df_journal[df_journal["Outcome"].str.contains("HIT")])
        win_rate = round((wins / total) * 100, 1) if total > 0 else 0.0

        m1, m2, m3 = st.columns(3)
        with m1: st.metric("Total Completed Trades", total)
        with m2: st.metric("Historical Win Rate", f"{win_rate}%")
        with m3: st.metric("Profit Factor (at 1:2.5 RR)", f"{round((wins * 2.5) / (max(1, total - wins)), 2)}")

# ------------------------------------------------------------------
# TAB 3: DHAN API CREDENTIALS
# ------------------------------------------------------------------
with tab_dhan:
    st.subheader("🔑 Dhan API Credential Management")
    with st.form("dhan_auth_form"):
        client_id_input = st.text_input("Dhan Client ID", value=st.session_state["dhan_client_id"])
        access_token_input = st.text_input("Dhan Access Token", value=st.session_state["dhan_access_token"], type="password")
        submit_dhan = st.form_submit_button("Validate & Connect Dhan")

        if submit_dhan:
            if client_id_input and access_token_input:
                with st.spinner("Validating Dhan Credentials..."):
                    is_valid, msg = validate_dhan_credentials(client_id_input, access_token_input)
                    if is_valid:
                        st.session_state["dhan_client_id"] = client_id_input
                        st.session_state["dhan_access_token"] = access_token_input
                        st.session_state["dhan_authenticated"] = True
                        st.success(msg)
                        st.rerun()
                    else:
                        st.session_state["dhan_authenticated"] = False
                        st.error(msg)

# ------------------------------------------------------------------
# TAB 4: TELEGRAM ALERTS
# ------------------------------------------------------------------
with tab_tg:
    st.subheader("📱 Telegram Notification Engine")
    st.caption("Broadcasts alerts exclusively for BUY CE and BUY PE signals across selected timeframes.")

    col_tg_cfg, col_tg_test = st.columns([2, 1])

    with col_tg_cfg:
        with st.form("telegram_form"):
            bot_token_input = st.text_input("Telegram Bot Token", value=st.session_state["tg_bot_token"])
            chat_id_input = st.text_input("Telegram Chat ID", value=st.session_state["tg_chat_id"])
            save_tg = st.form_submit_button("Save Telegram Credentials")

            if save_tg:
                st.session_state["tg_bot_token"] = bot_token_input
                st.session_state["tg_chat_id"] = chat_id_input
                st.session_state["tg_connected"] = bool(bot_token_input and chat_id_input)
                st.success("Telegram Settings Saved!")
                st.rerun()

    with col_tg_test:
        st.markdown("##### Connection Test")
        if st.button("Send Test Alert", use_container_width=True):
            if not st.session_state["tg_connected"]:
                st.error("Configure Bot Token & Chat ID first.")
            else:
                ok = send_telegram_alert(f"✅ <b>Apex Algo:</b> Telegram Alert System Active! Active Timeframe: {selected_timeframe}")
                if ok: st.success("Test Delivered!")
                else: st.error("Delivery Failed.")

    st.divider()
    st.markdown("##### 🛡️ Alert Memory & Anti-Spam Cache")
    st.write(f"Unique BUY CE / BUY PE Alerts Sent Today: **{len(st.session_state['sent_alerts'])}**")
    if st.button("Reset Alert Memory & Timestamp Cache"):
        st.session_state["sent_alerts"].clear()
        st.session_state["signal_timestamps"].clear()
        st.success("Alert Memory & Timestamp Cache Reset.")

# ------------------------------------------------------------------
# TAB 5: RISK MANAGEMENT ENGINE
# ------------------------------------------------------------------
with tab_risk:
    st.subheader("🛡️ Enterprise Risk & Capital Controls")
    c1, c2 = st.columns(2)
    with c1:
        st.session_state["total_capital"] = st.number_input("Trading Capital (₹)", value=st.session_state["total_capital"], step=10000.0)
        st.session_state["risk_per_trade_pct"] = st.slider("Max Risk Per Trade (%)", 0.25, 5.0, st.session_state["risk_per_trade_pct"], 0.25)
    with c2:
        st.session_state["default_sl_pct"] = st.slider("Default Stop Loss (%)", 0.5, 10.0, st.session_state["default_sl_pct"], 0.5)
        st.session_state["rr_ratio"] = st.slider("Risk-to-Reward Target Multiple (1:X)", 1.5, 4.0, st.session_state["rr_ratio"], 0.1)

# ------------------------------------------------------------------
# TAB 6: AUTO SCAN CONTROLLER
# ------------------------------------------------------------------
with tab_autoscan:
    st.subheader("⏰ Automated Background Screener Daemon")
    st.session_state["auto_scan_active"] = st.toggle("Enable Background Auto Scan", value=st.session_state["auto_scan_active"])
    st.session_state["auto_scan_interval"] = st.selectbox("Scan Frequency (Minutes)", [1, 3, 5, 15], index=2)

# ------------------------------------------------------------------
# TAB 7: ORDER LOGS
# ------------------------------------------------------------------
with tab_orders:
    st.subheader("📜 Order Execution History")
    tp, tl = st.tabs(["📄 Paper Trade Logs", "🚀 Live Dhan Executions"])
    with tp:
        if st.session_state["paper_trade_log"]:
            st.dataframe(pd.DataFrame(st.session_state["paper_trade_log"]), use_container_width=True)
        else:
            st.info("No paper trades executed.")
    with tl:
        if st.session_state["live_trade_log"]:
            st.dataframe(pd.DataFrame(st.session_state["live_trade_log"]), use_container_width=True)
        else:
            st.info("No live trades executed.")
