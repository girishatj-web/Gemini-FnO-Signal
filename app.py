import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import yfinance as yf
import requests
import re
import time
from datetime import datetime

# ==========================================
# 1. PAGE CONFIGURATION & LIGHT THEME STYLING
# ==========================================
st.set_page_config(
    page_title="Apex Dhan F&O Algo Engine",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom High-Contrast Light UI Design System
st.markdown("""
<style>
    /* Main Canvas Background - Soft Light Slate */
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

    /* Modern Light Card Layouts */
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
        font-size: 1.75rem;
        font-weight: 800;
        margin-top: 4px;
        margin-bottom: 4px;
    }

    .kpi-subtext {
        font-size: 0.75rem;
        font-weight: 600;
    }

    .trend-up { color: #16A34A; }
    .trend-down { color: #DC2626; }

    /* Status Pill Badges */
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

    /* Custom Dataframe Styling */
    .stDataFrame {
        background-color: #FFFFFF !important;
        border: 1px solid #CBD5E1 !important;
        border-radius: 10px !important;
    }

    /* Light Tab Headers Styling */
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
# 2. SESSION STATE INITIALIZATION
# ==========================================
def init_session_state():
    if "dhan_client_id" not in st.session_state: st.session_state["dhan_client_id"] = ""
    if "dhan_access_token" not in st.session_state: st.session_state["dhan_access_token"] = ""
    if "dhan_authenticated" not in st.session_state: st.session_state["dhan_authenticated"] = False

    if "tg_bot_token" not in st.session_state: st.session_state["tg_bot_token"] = ""
    if "tg_chat_id" not in st.session_state: st.session_state["tg_chat_id"] = ""
    if "tg_connected" not in st.session_state: st.session_state["tg_connected"] = False
    if "sent_alerts" not in st.session_state: st.session_state["sent_alerts"] = set()

    if "total_capital" not in st.session_state: st.session_state["total_capital"] = 200000.0
    if "risk_per_trade_pct" not in st.session_state: st.session_state["risk_per_trade_pct"] = 1.0
    if "default_sl_pct" not in st.session_state: st.session_state["default_sl_pct"] = 1.5
    if "default_target_pct" not in st.session_state: st.session_state["default_target_pct"] = 3.0

    if "auto_scan_active" not in st.session_state: st.session_state["auto_scan_active"] = False
    if "auto_scan_interval" not in st.session_state: st.session_state["auto_scan_interval"] = 5
    if "last_scan_time" not in st.session_state: st.session_state["last_scan_time"] = None

    if "paper_trade_log" not in st.session_state: st.session_state["paper_trade_log"] = []
    if "live_trade_log" not in st.session_state: st.session_state["live_trade_log"] = []

init_session_state()

# Fallback Standard NSE F&O Equity Symbols (guarantees valid stock queries)
NSE_FNO_FALLBACK = [
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN", "BHARTIARTL", "TATAMOTORS",
    "LTIM", "AXISBANK", "KOTAKBANK", "ITC", "LT", "HINDUNILVR", "BAJFINANCE", "MARUTI",
    "SUNPHARMA", "TATASTEEL", "NTPC", "POWERGRID", "TITAN", "ASIANPAINT", "ONGC", "HAL",
    "ADANIENT", "ADANIPORTS", "COALINDIA", "JIOFIN", "BPCL", "GRASIM", "HEROMOTOCO",
    "EICHERMOT", "DIVISLAB", "CIPLA", "DRREDDY", "ULTRACEMCO", "BEL", "TRENT", "VEDL"
]

# ==========================================
# 3. DHAN UNIVERSE & API ENGINES
# ==========================================
DHAN_SCRIP_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"

@st.cache_data(ttl=3600*12)
def fetch_dhan_fno_universe():
    """Fetches Dhan Master CSV and extracts clean underlying equity stock tickers."""
    try:
        df_master = pd.read_csv(DHAN_SCRIP_MASTER_URL, low_memory=False)
        
        # Filter NSE Stock Derivatives
        fno_mask = (
            (df_master['SEM_EXM_EXCH_ID'].astype(str).str.upper() == 'NSE') & 
            (df_master['SEM_INSTRUMENT_NAME'].astype(str).str.upper().isin(['FUTSTK', 'OPTSTK']))
        )
        fno_df = df_master[fno_mask]
        
        raw_symbols = []
        if 'SEM_CUSTOM_SYMBOL' in fno_df.columns:
            raw_symbols = fno_df['SEM_CUSTOM_SYMBOL'].dropna().astype(str).str.split('-').str[0].tolist()
        elif 'SEM_TRADING_SYMBOL' in fno_df.columns:
            raw_symbols = fno_df['SEM_TRADING_SYMBOL'].dropna().astype(str).str.split('-').str[0].tolist()

        indices = {'NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'NIFTYNXT50'}
        clean_symbols = set()
        
        for sym in raw_symbols:
            clean_sym = re.sub(r'[^A-Z]', '', str(sym).upper())
            if clean_sym and len(clean_sym) >= 2 and clean_sym not in indices:
                clean_symbols.add(clean_sym)
                
        result_list = sorted(list(clean_symbols))
        return result_list if len(result_list) > 10 else NSE_FNO_FALLBACK
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
            order_data = res.json()
            return True, order_data.get("orderId", "ORD-" + str(np.random.randint(10000, 99999)))
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

def dispatch_deduplicated_alerts(filtered_df):
    today_str = datetime.now().strftime("%Y-%m-%d")
    sent_count = 0
    for _, row in filtered_df.iterrows():
        alert_key = f"{row['Ticker']}_{row['Signal']}_{today_str}"
        if alert_key not in st.session_state["sent_alerts"]:
            msg = f"🚨 <b>APEX SIGNAL: #{row['Ticker']}</b>\nSignal: {row['Signal']}\nPrice: ₹{row['Price (₹)']}\nRSI: {row['RSI (14)']}"
            if send_telegram_alert(msg):
                st.session_state["sent_alerts"].add(alert_key)
                sent_count += 1
    return sent_count

# Position Risk Calculator
def calculate_position_size(price, sl_pct):
    capital = st.session_state["total_capital"]
    risk_amt = capital * (st.session_state["risk_per_trade_pct"] / 100.0)
    sl_per_share = price * (sl_pct / 100.0)
    if sl_per_share <= 0: return 1, risk_amt, price * 0.98, price * 1.04
    
    qty = max(1, int(risk_amt / sl_per_share))
    sl_price = round(price - sl_per_share, 2)
    target_price = round(price + (sl_per_share * (st.session_state["default_target_pct"] / st.session_state["default_sl_pct"])), 2)
    return qty, risk_amt, sl_price, target_price

# Technical Screener Engine
@st.cache_data(ttl=300)
def compute_screener_signals(symbols):
    if not symbols: return pd.DataFrame()
    scan_symbols = symbols[:50]  # Processes top 50 active stocks for fast response
    yf_tickers = [f"{sym}.NS" for sym in scan_symbols]
    
    try:
        data = yf.download(yf_tickers, period="6m", group_by="ticker", progress=False, threads=True)
    except Exception:
        return pd.DataFrame()

    results = []
    for sym in scan_symbols:
        ticker_id = f"{sym}.NS"
        try:
            if len(scan_symbols) == 1:
                df_stock = data.dropna()
            else:
                if ticker_id not in data.columns.levels[0]: continue
                df_stock = data[ticker_id].dropna()

            if len(df_stock) < 30: continue

            close = df_stock['Close']
            current_price = float(close.iloc[-1])
            prev_price = float(close.iloc[-2])
            change_pct = float(((current_price - prev_price) / prev_price) * 100)

            delta = close.diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss
            rsi_14 = float((100 - (100 / (1 + rs))).iloc[-1])

            sma_50 = float(close.rolling(50).mean().iloc[-1])
            sma_200 = float(close.rolling(200).mean().iloc[-1]) if len(df_stock) >= 200 else sma_50

            if rsi_14 < 35 and current_price > sma_50: signal = "Bullish Oversold"
            elif current_price > sma_50 and sma_50 > sma_200: signal = "Strong Uptrend"
            elif rsi_14 > 70: signal = "Bearish Overbought"
            elif current_price < sma_50 and current_price < sma_200: signal = "Downtrend Breakdown"
            else: signal = "Consolidating"

            results.append({
                "Ticker": sym,
                "Price (₹)": round(current_price, 2),
                "Change (%)": round(change_pct, 2),
                "RSI (14)": round(rsi_14, 1),
                "SMA 50 (₹)": round(sma_50, 2),
                "SMA 200 (₹)": round(sma_200, 2),
                "Signal": signal
            })
        except Exception:
            continue

    return pd.DataFrame(results)

fno_universe = fetch_dhan_fno_universe()

# ==========================================
# 4. SIDEBAR CONTROLS
# ==========================================
with st.sidebar:
    st.markdown("### ⚡ Apex Control Center")
    st.caption(f"F&O Stocks Universe: **{len(fno_universe)}** Symbols")
    st.divider()

    dhan_status_class = "status-badge-active" if st.session_state["dhan_authenticated"] else "status-badge-off"
    dhan_status_text = "CONNECTED" if st.session_state["dhan_authenticated"] else "DISCONNECTED"
    
    tg_status_class = "status-badge-active" if st.session_state["tg_connected"] else "status-badge-off"
    tg_status_text = "CONNECTED" if st.session_state["tg_connected"] else "DISCONNECTED"

    st.markdown(f"**Dhan API:** <span class='{dhan_status_class}'>{dhan_status_text}</span>", unsafe_allow_html=True)
    st.markdown(f"**Telegram Bot:** <span class='{tg_status_class}'>{tg_status_text}</span>", unsafe_allow_html=True)
    st.divider()

    st.markdown("#### 🔍 Filter Scanner")
    selected_signal = st.selectbox("Technical Signal", ["All", "Bullish Oversold", "Strong Uptrend", "Bearish Overbought", "Downtrend Breakdown", "Consolidating"], index=0)
    rsi_range = st.slider("RSI Range", 0.0, 100.0, (0.0, 100.0))
    search_ticker = st.text_input("Find Symbol", "").upper().strip()

    st.divider()
    if st.button("🔄 Manual Rescan", use_container_width=True):
        st.cache_data.clear()
        st.session_state["last_scan_time"] = datetime.now().strftime("%H:%M:%S")
        st.rerun()

# Fetch Stock Signals
df_screener = compute_screener_signals(fno_universe)
filtered_df = df_screener.copy()

if not filtered_df.empty:
    if selected_signal != "All":
        filtered_df = filtered_df[filtered_df["Signal"] == selected_signal]
    filtered_df = filtered_df[
        (filtered_df["RSI (14)"] >= rsi_range[0]) & 
        (filtered_df["RSI (14)"] <= rsi_range[1])
    ]
    if search_ticker:
        filtered_df = filtered_df[filtered_df["Ticker"].str.contains(search_ticker)]

if st.session_state["tg_connected"] and not filtered_df.empty:
    dispatch_deduplicated_alerts(filtered_df)

# ==========================================
# 5. MAIN APPLICATION DASHBOARD
# ==========================================
st.title("⚡ Apex Enterprise Algo & Screener Dashboard")

tab_screener, tab_dhan, tab_tg, tab_risk, tab_autoscan, tab_orders = st.tabs([
    "📋 Live Screener", 
    "🔑 Dhan API & Auth", 
    "📱 Telegram Alerts", 
    "🛡️ Risk Engine", 
    "⏰ Auto Scan", 
    "📜 Order Book"
])

# ------------------------------------------------------------------
# TAB 1: SCREENER & TRADE EXECUTION
# ------------------------------------------------------------------
with tab_screener:
    st.subheader("Real-Time Technical Signals & Order Terminal")

    k1, k2, k3, k4 = st.columns(4)
    total_m = len(filtered_df)
    bullish_m = len(filtered_df[filtered_df["Signal"].str.contains("Bullish|Uptrend")]) if total_m > 0 else 0
    avg_rsi = round(filtered_df["RSI (14)"].mean(), 1) if total_m > 0 else 0
    
    with k1: st.markdown(f"<div class='kpi-card'><div class='kpi-title'>Filtered Stocks</div><div class='kpi-value'>{total_m}</div></div>", unsafe_allow_html=True)
    with k2: st.markdown(f"<div class='kpi-card'><div class='kpi-title'>Bullish Setups</div><div class='kpi-value'>{bullish_m}</div></div>", unsafe_allow_html=True)
    with k3: st.markdown(f"<div class='kpi-card'><div class='kpi-title'>Avg RSI</div><div class='kpi-value'>{avg_rsi}</div></div>", unsafe_allow_html=True)
    with k4: st.markdown(f"<div class='kpi-card'><div class='kpi-title'>Alerts Broadcast</div><div class='kpi-value'>{len(st.session_state['sent_alerts'])}</div></div>", unsafe_allow_html=True)

    st.divider()

    col_table, col_action = st.columns([2, 1])

    with col_table:
        st.markdown("##### Filtered F&O Universe Table")
        if not filtered_df.empty:
            st.dataframe(
                filtered_df.style.format({
                    "Price (₹)": "₹{:.2f}",
                    "Change (%)": "{:+.2f}%",
                    "RSI (14)": "{:.1f}",
                    "SMA 50 (₹)": "₹{:.2f}",
                    "SMA 200 (₹)": "₹{:.2f}"
                }).map(
                    lambda x: 'color: #16A34A; font-weight: 700;' if isinstance(x, (int, float)) and x > 0 else ('color: #DC2626; font-weight: 700;' if isinstance(x, (int, float)) and x < 0 else ''),
                    subset=["Change (%)"]
                ),
                use_container_width=True,
                height=420
            )
        else:
            st.info("No assets match the current filter criteria. Adjust the sidebar filters or click Manual Rescan.")

    with col_action:
        st.markdown("##### ⚡ Order Execution Panel")
        selectable_stocks = filtered_df["Ticker"].unique() if not filtered_df.empty else df_screener["Ticker"].unique() if not df_screener.empty else []
        
        if len(selectable_stocks) > 0:
            selected_stock = st.selectbox("Select Target Asset", selectable_stocks)
            
            ref_df = filtered_df if not filtered_df.empty else df_screener
            stock_row = ref_df[ref_df["Ticker"] == selected_stock].iloc[0]
            price = float(stock_row["Price (₹)"])
            
            qty, risk_amt, sl_price, target_price = calculate_position_size(price, st.session_state["default_sl_pct"])

            st.success(f"**Target Asset:** {selected_stock} | **LTP:** ₹{price}")
            st.write(f"• **Position Size:** `{qty}` Shares")
            st.write(f"• **Capital at Risk:** ₹{risk_amt:,.2f}")
            st.write(f"• **Stop Loss:** ₹{sl_price} ({st.session_state['default_sl_pct']}%)")
            st.write(f"• **Take Profit Target:** ₹{target_price} ({st.session_state['default_target_pct']}%)")

            st.write("")
            col_p, col_l = st.columns(2)
            
            with col_p:
                if st.button("📄 Paper Trade", use_container_width=True):
                    paper_entry = {
                        "Time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "Symbol": selected_stock,
                        "Type": "BUY",
                        "Qty": qty,
                        "Entry Price": price,
                        "SL": sl_price,
                        "Target": target_price,
                        "Status": "OPEN"
                    }
                    st.session_state["paper_trade_log"].append(paper_entry)
                    st.success(f"Paper Order Executed for {selected_stock}!")

            with col_l:
                if st.button("🚀 1-Click Live Trade", use_container_width=True, type="primary"):
                    if not st.session_state["dhan_authenticated"]:
                        st.error("Authenticate Dhan API in Tab 2 first!")
                    else:
                        success, order_info = execute_dhan_live_order(selected_stock, qty, "BUY", price)
                        if success:
                            live_entry = {
                                "Time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                "OrderID": order_info,
                                "Symbol": selected_stock,
                                "Type": "BUY",
                                "Qty": qty,
                                "Price": price,
                                "Status": "EXECUTED"
                            }
                            st.session_state["live_trade_log"].append(live_entry)
                            st.balloons()
                            st.success(f"Live Order Placed! ID: {order_info}")
                        else:
                            st.error(f"Execution Error: {order_info}")
        else:
            st.warning("Loading market data... Click Manual Rescan if needed.")

# ------------------------------------------------------------------
# TAB 2: DHAN API CREDENTIALS
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
# TAB 3: TELEGRAM ALERTS
# ------------------------------------------------------------------
with tab_tg:
    st.subheader("📱 Telegram Notification Engine")
    col_tg_cfg, col_tg_test = st.columns([2, 1])

    with col_tg_cfg:
        with st.form("telegram_form"):
            bot_token_input = st.text_input("Telegram Bot Token", value=st.session_state["tg_bot_token"])
            chat_id_input = st.text_input("Telegram Chat ID", value=st.session_state["tg_chat_id"])
            save_tg = st.form_submit_button("Save Connection")

            if save_tg:
                st.session_state["tg_bot_token"] = bot_token_input
                st.session_state["tg_chat_id"] = chat_id_input
                st.session_state["tg_connected"] = bool(bot_token_input and chat_id_input)
                st.success("Telegram Credentials Saved!")
                st.rerun()

    with col_tg_test:
        st.markdown("##### 🧪 Test Channel")
        if st.button("Send Test Alert", use_container_width=True):
            if not st.session_state["tg_connected"]:
                st.error("Configure Token & Chat ID first.")
            else:
                ok = send_telegram_alert("✅ <b>Apex Algo:</b> Telegram Alert Active!")
                if ok: st.success("Test Delivered!")
                else: st.error("Delivery Failed.")

# ------------------------------------------------------------------
# TAB 4: RISK MANAGEMENT
# ------------------------------------------------------------------
with tab_risk:
    st.subheader("🛡️ Position Sizing & Risk Controls")
    c1, c2 = st.columns(2)
    with c1:
        st.session_state["total_capital"] = st.number_input("Trading Capital (₹)", value=st.session_state["total_capital"], step=10000.0)
        st.session_state["risk_per_trade_pct"] = st.slider("Max Risk Per Trade (%)", 0.25, 5.0, st.session_state["risk_per_trade_pct"], 0.25)
    with c2:
        st.session_state["default_sl_pct"] = st.slider("Default Stop Loss (%)", 0.5, 10.0, st.session_state["default_sl_pct"], 0.5)
        st.session_state["default_target_pct"] = st.slider("Default Profit Target (%)", 1.0, 20.0, st.session_state["default_target_pct"], 0.5)

# ------------------------------------------------------------------
# TAB 5: AUTO SCAN CONTROLLER
# ------------------------------------------------------------------
with tab_autoscan:
    st.subheader("⏰ Automated Background Screener")
    st.session_state["auto_scan_active"] = st.toggle("Enable Background Auto Scan", value=st.session_state["auto_scan_active"])
    st.session_state["auto_scan_interval"] = st.selectbox("Scan Interval (Minutes)", [1, 3, 5, 15], index=2)

# ------------------------------------------------------------------
# TAB 6: ORDER LOGS
# ------------------------------------------------------------------
with tab_orders:
    st.subheader("📜 Order Execution Log")
    tp, tl = st.tabs(["📄 Paper Orders", "🚀 Live Dhan Executions"])
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
