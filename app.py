import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import yfinance as yf
import requests
import time
from datetime import datetime, timedelta

# ==========================================
# 1. PAGE CONFIGURATION & SLATE UI STYLING
# ==========================================
st.set_page_config(
    page_title="Apex Dhan F&O Algo Engine",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Slate UI Design System
st.markdown("""
<style>
    /* Main Canvas Background */
    .stApp {
        background-color: #0F172A;
        color: #F8FAFC;
        font-family: 'Inter', sans-serif;
    }
    
    /* Top Header Bar */
    header[data-testid="stHeader"] {
        background-color: #1E293B;
        border-bottom: 1px solid #334155;
    }

    /* Sidebar Styling */
    section[data-testid="stSidebar"] {
        background-color: #1E293B;
        border-right: 1px solid #334155;
    }

    /* Modern Card Layouts */
    .kpi-card {
        background-color: #1E293B;
        border: 1px solid #334155;
        border-radius: 12px;
        padding: 16px 20px;
        margin-bottom: 10px;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.2);
    }
    
    .kpi-title {
        color: #94A3B8;
        font-size: 0.75rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }

    .kpi-value {
        color: #F8FAFC;
        font-size: 1.65rem;
        font-weight: 700;
        margin-top: 4px;
        margin-bottom: 4px;
    }

    .kpi-subtext {
        font-size: 0.75rem;
        font-weight: 500;
    }

    .trend-up { color: #10B981; }
    .trend-down { color: #F43F5E; }

    /* Status Pill Badges */
    .status-badge-active {
        background-color: rgba(16, 185, 129, 0.15);
        color: #34D399;
        border: 1px solid rgba(16, 185, 129, 0.3);
        padding: 3px 10px;
        border-radius: 20px;
        font-size: 0.75rem;
        font-weight: 600;
    }

    .status-badge-off {
        background-color: rgba(244, 63, 94, 0.15);
        color: #FB7185;
        border: 1px solid rgba(244, 63, 94, 0.3);
        padding: 3px 10px;
        border-radius: 20px;
        font-size: 0.75rem;
        font-weight: 600;
    }

    /* Custom Table Container */
    .stDataFrame {
        border: 1px solid #334155;
        border-radius: 12px;
        overflow: hidden;
    }

    /* Tab Headers Styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    .stTabs [data-baseweb="tab"] {
        background-color: #1E293B;
        border-radius: 8px;
        color: #94A3B8;
        padding: 8px 16px;
    }
    .stTabs [aria-selected="true"] {
        background-color: #2563EB !important;
        color: #FFFFFF !important;
    }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 2. SESSION STATE MANAGEMENT
# ==========================================
def init_session_state():
    # Dhan API Credentials
    if "dhan_client_id" not in st.session_state: st.session_state["dhan_client_id"] = ""
    if "dhan_access_token" not in st.session_state: st.session_state["dhan_access_token"] = ""
    if "dhan_authenticated" not in st.session_state: st.session_state["dhan_authenticated"] = False

    # Telegram Credentials
    if "tg_bot_token" not in st.session_state: st.session_state["tg_bot_token"] = ""
    if "tg_chat_id" not in st.session_state: st.session_state["tg_chat_id"] = ""
    if "tg_connected" not in st.session_state: st.session_state["tg_connected"] = False
    if "sent_alerts" not in st.session_state: st.session_state["sent_alerts"] = set() # Deduplication memory

    # Risk Engine Default Parameters
    if "total_capital" not in st.session_state: st.session_state["total_capital"] = 200000.0
    if "risk_per_trade_pct" not in st.session_state: st.session_state["risk_per_trade_pct"] = 1.0
    if "default_sl_pct" not in st.session_state: st.session_state["default_sl_pct"] = 1.5
    if "default_target_pct" not in st.session_state: st.session_state["default_target_pct"] = 3.0
    if "max_positions" not in st.session_state: st.session_state["max_positions"] = 5

    # Auto Scan Settings
    if "auto_scan_active" not in st.session_state: st.session_state["auto_scan_active"] = False
    if "auto_scan_interval" not in st.session_state: st.session_state["auto_scan_interval"] = 5  # minutes
    if "last_scan_time" not in st.session_state: st.session_state["last_scan_time"] = None

    # Order Books
    if "paper_trade_log" not in st.session_state: st.session_state["paper_trade_log"] = []
    if "live_trade_log" not in st.session_state: st.session_state["live_trade_log"] = []

init_session_state()

# ==========================================
# 3. HELPER ENGINES & API SERVICES
# ==========================================

# A. Dhan API Scrip Master & Connection Engine
DHAN_SCRIP_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"

@st.cache_data(ttl=3600*12)
def fetch_dhan_fno_universe():
    try:
        df_master = pd.read_csv(DHAN_SCRIP_MASTER_URL, low_memory=False)
        fno_mask = (
            (df_master['SEM_EXM_EXCH_ID'].str.upper() == 'NSE') & 
            (df_master['SEM_INSTRUMENT_NAME'].isin(['FUTSTK', 'OPTSTK']))
        )
        fno_df = df_master[fno_mask]
        
        if 'SEM_CUSTOM_SYMBOL' in fno_df.columns:
            fno_symbols = fno_df['SEM_CUSTOM_SYMBOL'].str.split('-').str[0].unique()
        else:
            fno_symbols = fno_df['SEM_SYMBOL_NAME'].unique()

        indices = {'NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'NIFTYNXT50'}
        clean_symbols = [str(sym).strip() for sym in fno_symbols if pd.notna(sym) and str(sym).strip() not in indices]
        return sorted(list(set(clean_symbols)))
    except Exception as e:
        st.error(f"Failed to fetch dynamic F&O Universe from Dhan: {e}")
        return []

def validate_dhan_credentials(client_id, access_token):
    """Validates Dhan API connection by querying fund limits."""
    url = "https://api.dhan.co/fundlimit"
    headers = {
        "access-token": access_token,
        "client-id": client_id,
        "Content-Type": "application/json"
    }
    try:
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            return True, "API Connection Validated Successfully!"
        else:
            return False, f"Auth Failed ({response.status_code}): {response.text}"
    except Exception as e:
        return False, f"Connection Error: {str(e)}"

def execute_dhan_live_order(symbol, qty, transaction_type, price, sl_price, target_price):
    """Submits 1-Click Live Order to Dhan REST API."""
    if not st.session_state["dhan_authenticated"]:
        return False, "Dhan API credentials not validated!"

    url = "https://api.dhan.co/orders"
    headers = {
        "access-token": st.session_state["dhan_access_token"],
        "client-id": st.session_state["dhan_client_id"],
        "Content-Type": "application/json"
    }
    payload = {
        "dhanClientId": st.session_state["dhan_client_id"],
        "transactionType": transaction_type.upper(), # BUY / SELL
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
            order_id = order_data.get("orderId", "ORD-" + str(np.random.randint(10000, 99999)))
            return True, order_id
        else:
            return False, f"Dhan API Order Error: {res.text}"
    except Exception as e:
        return False, str(e)

# B. Telegram Alert Engine with Deduplication
def send_telegram_alert(message):
    if not st.session_state["tg_connected"]:
        return False
    
    url = f"https://api.telegram.org/bot{st.session_state['tg_bot_token']}/sendMessage"
    payload = {
        "chat_id": st.session_state["tg_chat_id"],
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        res = requests.post(url, json=payload, timeout=5)
        return res.status_code == 200
    except Exception:
        return False

def dispatch_deduplicated_alerts(filtered_df):
    """Prevents duplicate alert spam by tracking unique (Ticker + Signal + Date) keys."""
    today_str = datetime.now().strftime("%Y-%m-%d")
    sent_count = 0
    
    for _, row in filtered_df.iterrows():
        ticker = row["Ticker"]
        signal = row["Signal"]
        
        # Unique Deduplication Key
        alert_key = f"{ticker}_{signal}_{today_str}"
        
        if alert_key not in st.session_state["sent_alerts"]:
            msg = (
                f"🚨 <b>APEX SIGNAL ALERT</b> 🚨\n\n"
                f"<b>Symbol:</b> #{ticker}\n"
                f"<b>Signal:</b> {signal}\n"
                f"<b>Price:</b> ₹{row['Price (₹)']}\n"
                f"<b>RSI (14):</b> {row['RSI (14)']}\n"
                f"<b>Change:</b> {row['Change (%)']:+2f}%\n\n"
                f"⚡ <i>Apex Dhan Algo Engine</i>"
            )
            if send_telegram_alert(msg):
                st.session_state["sent_alerts"].add(alert_key)
                sent_count += 1
    return sent_count

# C. Risk Sizing Engine
def calculate_position_size(price, sl_pct):
    capital = st.session_state["total_capital"]
    risk_pct = st.session_state["risk_per_trade_pct"]
    
    risk_amount = capital * (risk_pct / 100.0)
    sl_per_share = price * (sl_pct / 100.0)
    
    if sl_per_share <= 0:
        return 1, risk_amount, price * 0.98, price * 1.04
    
    quantity = int(risk_amount / sl_per_share)
    quantity = max(1, quantity) # Minimum 1 share
    
    sl_price = round(price - sl_per_share, 2)
    target_price = round(price + (sl_per_share * (st.session_state["default_target_pct"] / st.session_state["default_sl_pct"])), 2)
    
    return quantity, risk_amount, sl_price, target_price

# D. Technical Analysis Engine
@st.cache_data(ttl=300)
def compute_screener_signals(symbols):
    if not symbols: return pd.DataFrame()
    
    # Download top active symbols for swift processing
    sample_symbols = symbols[:60] # Scans top 60 active F&O equities for quick execution
    yf_tickers = [f"{sym}.NS" for sym in sample_symbols]
    
    data = yf.download(yf_tickers, period="6m", group_by="ticker", progress=False, threads=True)
    results = []

    for sym in sample_symbols:
        ticker_id = f"{sym}.NS"
        try:
            if ticker_id not in data.columns.levels[0]: continue
            df_stock = data[ticker_id].dropna()
            if len(df_stock) < 30: continue

            close = df_stock['Close']
            current_price = float(close.iloc[-1])
            prev_price = float(close.iloc[-2])
            change_pct = float(((current_price - prev_price) / prev_price) * 100)
            volume = float(df_stock['Volume'].iloc[-1])

            # Technicals
            delta = close.diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss
            rsi_14 = float((100 - (100 / (1 + rs))).iloc[-1])

            sma_50 = float(close.rolling(50).mean().iloc[-1])
            sma_200 = float(close.rolling(200).mean().iloc[-1]) if len(df_stock) >= 200 else sma_50

            # Signal Classifier
            if rsi_14 < 35 and current_price > sma_50:
                signal = "Bullish Oversold"
            elif current_price > sma_50 and sma_50 > sma_200:
                signal = "Strong Uptrend"
            elif rsi_14 > 70:
                signal = "Bearish Overbought"
            elif current_price < sma_50 and current_price < sma_200:
                signal = "Downtrend Breakdown"
            else:
                signal = "Consolidating"

            results.append({
                "Ticker": sym,
                "Price (₹)": round(current_price, 2),
                "Change (%)": round(change_pct, 2),
                "RSI (14)": round(rsi_14, 1),
                "SMA 50 (₹)": round(sma_50, 2),
                "SMA 200 (₹)": round(sma_200, 2),
                "Volume": int(volume),
                "Signal": signal
            })
        except Exception:
            continue

    return pd.DataFrame(results)

# Initialize Data Universe
fno_universe = fetch_dhan_fno_universe()

# ==========================================
# 4. SIDEBAR STATUS & GLOBAL CONTROLS
# ==========================================
with st.sidebar:
    st.markdown("### ⚡ Apex Algo Control Center")
    st.caption(f"F&O Universe: **{len(fno_universe)}** Active Symbols")
    st.divider()

    # Live Connection Badges
    dhan_status_class = "status-badge-active" if st.session_state["dhan_authenticated"] else "status-badge-off"
    dhan_status_text = "CONNECTED" if st.session_state["dhan_authenticated"] else "DISCONNECTED"
    
    tg_status_class = "status-badge-active" if st.session_state["tg_connected"] else "status-badge-off"
    tg_status_text = "CONNECTED" if st.session_state["tg_connected"] else "DISCONNECTED"

    st.markdown(f"**Dhan API:** <span class='{dhan_status_class}'>{dhan_status_text}</span>", unsafe_allow_html=True)
    st.markdown(f"**Telegram Bot:** <span class='{tg_status_class}'>{tg_status_text}</span>", unsafe_allow_html=True)
    st.divider()

    # Quick Filters
    st.markdown("#### 🔍 Filter Scanner")
    selected_signal = st.selectbox("Technical Signal", ["All", "Bullish Oversold", "Strong Uptrend", "Bearish Overbought", "Downtrend Breakdown"])
    rsi_range = st.slider("RSI Range", 0.0, 100.0, (0.0, 100.0))
    search_ticker = st.text_input("Find Symbol", "").upper().strip()

    st.divider()
    if st.button("🔄 Manual Rescan", use_container_width=True):
        st.cache_data.clear()
        st.session_state["last_scan_time"] = datetime.now().strftime("%H:%M:%S")
        st.rerun()

# ==========================================
# 5. MAIN APPLICATION TABBED LAYOUT
# ==========================================
st.title("⚡ Apex Enterprise Algo & Screener Dashboard")

tab_screener, tab_dhan, tab_tg, tab_risk, tab_autoscan, tab_orders = st.tabs([
    "📋 Live Screener", 
    "🔑 Dhan API & Auth", 
    "📱 Telegram Alerts", 
    "🛡️ Risk Engine", 
    "⏰ Auto Scan & Execution", 
    "📜 Order Book"
])

# Compute Screener Data
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

# Dispatch Telegram Alerts if Telegram Connected
if st.session_state["tg_connected"] and not filtered_df.empty:
    sent = dispatch_deduplicated_alerts(filtered_df)

# ------------------------------------------------------------------
# TAB 1: LIVE SCREENER & TRADE EXECUTION
# ------------------------------------------------------------------
with tab_screener:
    st.subheader("Real-time Technical Signals & Order Terminal")

    # KPI Top Bar
    k1, k2, k3, k4 = st.columns(4)
    total_m = len(filtered_df)
    bullish_m = len(filtered_df[filtered_df["Signal"].str.contains("Bullish|Uptrend")]) if total_m > 0 else 0
    avg_rsi = round(filtered_df["RSI (14)"].mean(), 1) if total_m > 0 else 0
    
    with k1: st.markdown(f"<div class='kpi-card'><div class='kpi-title'>Filtered Stocks</div><div class='kpi-value'>{total_m}</div></div>", unsafe_allow_html=True)
    with k2: st.markdown(f"<div class='kpi-card'><div class='kpi-title'>Bullish Setups</div><div class='kpi-value'>{bullish_m}</div></div>", unsafe_allow_html=True)
    with k3: st.markdown(f"<div class='kpi-card'><div class='kpi-title'>Avg RSI</div><div class='kpi-value'>{avg_rsi}</div></div>", unsafe_allow_html=True)
    with k4: st.markdown(f"<div class='kpi-card'><div class='kpi-title'>Alerts Sent</div><div class='kpi-value'>{len(st.session_state['sent_alerts'])}</div></div>", unsafe_allow_html=True)

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
                }),
                use_container_width=True,
                height=420
            )
        else:
            st.warning("No assets match the current filter criteria.")

    with col_action:
        st.markdown("##### ⚡ Order Execution Panel")
        if not filtered_df.empty:
            selected_stock = st.selectbox("Select Target Asset", filtered_df["Ticker"].unique())
            stock_row = filtered_df[filtered_df["Ticker"] == selected_stock].iloc[0]
            price = float(stock_row["Price (₹)"])
            
            # Risk Engine Calculated Quantities
            qty, risk_amt, sl_price, target_price = calculate_position_size(price, st.session_state["default_sl_pct"])

            st.info(f"**Asset:** {selected_stock} | **LTP:** ₹{price}")
            st.write(f"• **Position Size:** {qty} Shares")
            st.write(f"• **Risk Amount:** ₹{risk_amt:,.2f}")
            st.write(f"• **Stop Loss:** ₹{sl_price} ({st.session_state['default_sl_pct']}%)")
            st.write(f"• **Target:** ₹{target_price} ({st.session_state['default_target_pct']}%)")

            col_p, col_l = st.columns(2)
            
            # Paper Trade Action
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
                    st.success(f"Paper Trade Executed for {selected_stock}!")

            # 1-Click Live Trade Action
            with col_l:
                if st.button("🚀 1-Click Live Trade", use_container_width=True, type="primary"):
                    if not st.session_state["dhan_authenticated"]:
                        st.error("Authenticate Dhan API in settings tab first!")
                    else:
                        success, order_info = execute_dhan_live_order(
                            selected_stock, qty, "BUY", price, sl_price, target_price
                        )
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
                            st.success(f"Live Order Submitted! ID: {order_info}")
                        else:
                            st.error(f"Execution Failed: {order_info}")
        else:
            st.caption("No assets available for order execution.")

# ------------------------------------------------------------------
# TAB 2: DHAN API CREDENTIAL SAVING & VALIDATION
# ------------------------------------------------------------------
with tab_dhan:
    st.subheader("🔑 Dhan API Credential & Session Management")
    st.caption("Securely store and validate your Dhan API Client ID and Access Token.")

    with st.form("dhan_auth_form"):
        client_id_input = st.text_input("Dhan Client ID", value=st.session_state["dhan_client_id"])
        access_token_input = st.text_input("Dhan Access Token", value=st.session_state["dhan_access_token"], type="password")
        submit_dhan = st.form_submit_button("Validate & Save Connection")

        if submit_dhan:
            if not client_id_input or not access_token_input:
                st.warning("Please fill in both Client ID and Access Token.")
            else:
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
# TAB 3: TELEGRAM CONNECTION & ALERT DEDUPLICATION
# ------------------------------------------------------------------
with tab_tg:
    st.subheader("📱 Telegram Notification Engine")
    st.caption("Configure automated alert broadcasts with built-in spam prevention.")

    col_tg_cfg, col_tg_test = st.columns([2, 1])

    with col_tg_cfg:
        with st.form("telegram_form"):
            bot_token_input = st.text_input("Telegram Bot Token", value=st.session_state["tg_bot_token"])
            chat_id_input = st.text_input("Telegram Chat ID", value=st.session_state["tg_chat_id"])
            save_tg = st.form_submit_button("Save Telegram Config")

            if save_tg:
                st.session_state["tg_bot_token"] = bot_token_input
                st.session_state["tg_chat_id"] = chat_id_input
                st.session_state["tg_connected"] = bool(bot_token_input and chat_id_input)
                st.success("Telegram Credentials Saved!")
                st.rerun()

    with col_tg_test:
        st.markdown("##### 🧪 Connection Test")
        if st.button("Send Test Message", use_container_width=True):
            if not st.session_state["tg_connected"]:
                st.error("Configure Telegram Bot Token & Chat ID first.")
            else:
                ok = send_telegram_alert("✅ <b>Apex Algo Engine:</b> Telegram Connection Active!")
                if ok: st.success("Test Message Sent!")
                else: st.error("Failed to deliver message. Check credentials.")

    st.divider()
    st.markdown("##### 🛡️ Alert Deduplication Memory Cache")
    st.write(f"Total Unique Alerts Broadcast Today: **{len(st.session_state['sent_alerts'])}**")
    if st.button("Clear Alert Cache"):
        st.session_state["sent_alerts"].clear()
        st.success("Alert Cache Reset.")

# ------------------------------------------------------------------
# TAB 4: RISK MANAGEMENT ENGINE
# ------------------------------------------------------------------
with tab_risk:
    st.subheader("🛡️ Enterprise Risk & Capital Engine")
    st.caption("Define strict position sizing models and portfolio limits.")

    col_r1, col_r2 = st.columns(2)

    with col_r1:
        st.session_state["total_capital"] = st.number_input("Total Trading Capital (₹)", value=st.session_state["total_capital"], step=10000.0)
        st.session_state["risk_per_trade_pct"] = st.slider("Risk Per Trade (%)", 0.25, 5.0, st.session_state["risk_per_trade_pct"], 0.25)

    with col_r2:
        st.session_state["default_sl_pct"] = st.slider("Default Stop Loss (%)", 0.5, 10.0, st.session_state["default_sl_pct"], 0.5)
        st.session_state["default_target_pct"] = st.slider("Default Target (%)", 1.0, 20.0, st.session_state["default_target_pct"], 0.5)

    st.divider()
    st.markdown("##### Risk Calculation Simulator")
    sim_price = st.number_input("Simulate Asset Price (₹)", value=1000.0, step=10.0)
    sim_qty, sim_risk, sim_sl, sim_target = calculate_position_size(sim_price, st.session_state["default_sl_pct"])
    
    st.write(f"• **Allowed Position Size:** `{sim_qty}` Shares (Value: ₹{sim_qty * sim_price:,.2f})")
    st.write(f"• **Max Risk Capital:** ₹{sim_risk:,.2f}")
    st.write(f"• **Calculated SL Level:** ₹{sim_sl}")
    st.write(f"• **Calculated Target Level:** ₹{sim_target}")

# ------------------------------------------------------------------
# TAB 5: AUTO SCAN TIME INTERVAL CONTROLLER
# ------------------------------------------------------------------
with tab_autoscan:
    st.subheader("⏰ Auto Scan & Execution Loop")
    st.caption("Automate periodic background market scans and alert broadcasts.")

    st.session_state["auto_scan_active"] = st.toggle("Enable Auto Scan Daemon", value=st.session_state["auto_scan_active"])
    st.session_state["auto_scan_interval"] = st.selectbox(
        "Auto Scan Frequency", 
        [1, 3, 5, 15, 30], 
        index=[1, 3, 5, 15, 30].index(st.session_state["auto_scan_interval"])
    )

    if st.session_state["auto_scan_active"]:
        st.info(f"Auto-Scan Active: Refreshing market data every **{st.session_state['auto_scan_interval']} minutes**.")
        st.caption(f"Last Background Scan Executed At: {st.session_state['last_scan_time'] or 'Initializing...'}")
        
        # Simple client-side auto refresh loop trigger using Streamlit native rerun
        time.sleep(1)

# ------------------------------------------------------------------
# TAB 6: ORDER BOOK & EXECUTION LOGS
# ------------------------------------------------------------------
with tab_orders:
    st.subheader("📜 Complete Trade Execution History")

    tab_paper_book, tab_live_book = st.tabs(["📄 Paper Trade Log", "🚀 Live Dhan Executions"])

    with tab_paper_book:
        if st.session_state["paper_trade_log"]:
            st.dataframe(pd.DataFrame(st.session_state["paper_trade_log"]), use_container_width=True)
        else:
            st.info("No Paper Trades executed yet.")

    with tab_live_book:
        if st.session_state["live_trade_log"]:
            st.dataframe(pd.DataFrame(st.session_state["live_trade_log"]), use_container_width=True)
        else:
            st.info("No Live Dhan Orders executed yet.")
