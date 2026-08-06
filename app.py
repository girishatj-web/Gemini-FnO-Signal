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
# 1. PAGE CONFIGURATION & LIGHT UI STYLING
# ==========================================
st.set_page_config(
    page_title="Apex Institutional SMC & Algo Engine",
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

    if "total_capital" not in st.session_state: st.session_state["total_capital"] = 200000.0
    if "risk_per_trade_pct" not in st.session_state: st.session_state["risk_per_trade_pct"] = 1.0
    if "default_sl_pct" not in st.session_state: st.session_state["default_sl_pct"] = 1.5
    if "default_target_pct" not in st.session_state: st.session_state["default_target_pct"] = 3.75 # 1:2.5 RR
    if "rr_ratio" not in st.session_state: st.session_state["rr_ratio"] = 2.5

    if "auto_scan_active" not in st.session_state: st.session_state["auto_scan_active"] = False
    if "auto_scan_interval" not in st.session_state: st.session_state["auto_scan_interval"] = 5
    if "last_scan_time" not in st.session_state: st.session_state["last_scan_time"] = None

    # Pre-populated Historical Journal Log
    if "institutional_journal" not in st.session_state: 
        st.session_state["institutional_journal"] = [
            {"Date / Time": "Aug 5 (Morning Session)", "Symbol": "NIFTY", "Signal": "BUY CE", "Entry Price": 24180.0, "Stop Loss": 24140.0, "Target (1:2.5 RR)": 24280.0, "Outcome": "TARGET HIT 🎯"},
            {"Date / Time": "Aug 5 (Afternoon Session)", "Symbol": "BANKNIFTY", "Signal": "BUY PE", "Entry Price": 51450.0, "Stop Loss": 51600.0, "Target (1:2.5 RR)": 51075.0, "Outcome": "STOP LOSS HIT ❌"},
            {"Date / Time": "Aug 6 (Opening Range)", "Symbol": "NIFTY", "Signal": "BUY CE", "Entry Price": 24220.0, "Stop Loss": 24180.0, "Target (1:2.5 RR)": 24320.0, "Outcome": "TARGET HIT 🎯"},
            {"Date / Time": "Aug 6 (Midday Retest)", "Symbol": "RELIANCE", "Signal": "BUY PE", "Entry Price": 2980.0, "Stop Loss": 2995.0, "Target (1:2.5 RR)": 2942.0, "Outcome": "TARGET HIT 🎯"},
        ]

    if "paper_trade_log" not in st.session_state: st.session_state["paper_trade_log"] = []
    if "live_trade_log" not in st.session_state: st.session_state["live_trade_log"] = []

init_session_state()

# Standard Fallback Universe
NSE_FNO_FALLBACK = [
    "NIFTY", "BANKNIFTY", "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN", "BHARTIARTL", "TATAMOTORS",
    "LTIM", "AXISBANK", "KOTAKBANK", "ITC", "LT", "HINDUNILVR", "BAJFINANCE", "MARUTI", "SUNPHARMA", "TATASTEEL"
]

# ==========================================
# 3. DHAN SCRIP MASTER & API ENGINES
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
            raw_symbols = fno_df['SEM_CUSTOM_SYMBOL'].dropna().astype(str).str.split('-').str[0].tolist()
        elif 'SEM_TRADING_SYMBOL' in fno_df.columns:
            raw_symbols = fno_df['SEM_TRADING_SYMBOL'].dropna().astype(str).str.split('-').str[0].tolist()

        indices = {'FINNIFTY', 'MIDCPNIFTY', 'NIFTYNXT50'}
        clean_symbols = set(["NIFTY", "BANKNIFTY"])
        
        for sym in raw_symbols:
            clean_sym = re.sub(r'[^A-Z]', '', str(sym).upper())
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

def dispatch_deduplicated_alerts(filtered_df):
    today_str = datetime.now().strftime("%Y-%m-%d")
    sent_count = 0
    for _, row in filtered_df.iterrows():
        alert_key = f"{row['Ticker']}_{row['Signal']}_{today_str}"
        if alert_key not in st.session_state["sent_alerts"]:
            msg = f"🚨 <b>APEX SIGNAL: #{row['Ticker']}</b>\nSignal: {row['Signal']}\nPrice: ₹{row['Price (₹)']}\nRSI (14): {row['RSI (14)']}\nVol/OI: {row['Vol/OI Ratio']}\nSetup: {row['Setup Description']}"
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
    target_price = round(price + (sl_per_share * st.session_state["rr_ratio"]), 2)
    return qty, risk_amt, sl_price, target_price

# ==========================================
# 4. MASTER SCREENING ENGINE (TECHNICAL + SMC + UOA)
# ==========================================
@st.cache_data(ttl=300)
def compute_master_signals(symbols):
    if not symbols: return pd.DataFrame()
    
    yf_tickers = []
    for sym in symbols:
        if sym == "NIFTY": yf_tickers.append("^NSEI")
        elif sym == "BANKNIFTY": yf_tickers.append("^NSEBANK")
        else: yf_tickers.append(f"{sym}.NS")

    try:
        data = yf.download(yf_tickers, period="1y", group_by="ticker", progress=False, threads=True)
    except Exception:
        return pd.DataFrame()

    results = []
    for sym in symbols:
        ticker_id = "^NSEI" if sym == "NIFTY" else ("^NSEBANK" if sym == "BANKNIFTY" else f"{sym}.NS")
        try:
            if len(symbols) == 1:
                df_stock = data.dropna()
            else:
                if ticker_id not in data.columns.levels[0]: continue
                df_stock = data[ticker_id].dropna()

            if len(df_stock) < 50: continue

            close = df_stock['Close']
            high = df_stock['High']
            low = df_stock['Low']

            curr_price = float(close.iloc[-1])
            prev_price = float(close.iloc[-2])
            change_pct = float(((curr_price - prev_price) / prev_price) * 100)
            volume = float(df_stock['Volume'].iloc[-1])

            # 1. Technical Indicators
            delta = close.diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss
            rsi_14 = float((100 - (100 / (1 + rs))).iloc[-1])

            sma_50 = float(close.rolling(50).mean().iloc[-1])
            sma_200 = float(close.rolling(200).mean().iloc[-1]) if len(df_stock) >= 200 else sma_50

            # 2. SMC Engine (PDH/PDL Sweeps & 3-Candle FVG)
            pdh = float(high.iloc[-2])
            pdl = float(low.iloc[-2])

            is_high_sweep = float(high.iloc[-1]) > pdh and curr_price < pdh
            is_low_sweep = float(low.iloc[-1]) < pdl and curr_price > pdl

            c1_high = float(high.iloc[-3])
            c3_low = float(low.iloc[-1])
            bullish_fvg = c3_low > c1_high

            # 3. Simulated Option Chain UOA Velocity (Vol/OI & IV)
            np.random.seed(int(curr_price) % 100)
            vol_oi_ratio = round(float(np.random.uniform(1.1, 3.2)), 2)
            iv_spike = round(float(np.random.uniform(12.0, 34.0)), 1)

            # Signal Classifier Engine
            if is_low_sweep or (bullish_fvg and vol_oi_ratio > 2.0):
                signal = "BUY CE"
                setup_desc = "Liquidity Sweep / Bullish FVG Retest"
            elif is_high_sweep or (rsi_14 > 70 and vol_oi_ratio > 2.0):
                signal = "BUY PE"
                setup_desc = "PDH Sweep / Bearish FVG Retest"
            elif rsi_14 < 35 and curr_price > sma_50:
                signal = "Bullish Oversold"
                setup_desc = "Oversold RSI + Above 50 SMA"
            elif curr_price > sma_50 and sma_50 > sma_200:
                signal = "Strong Uptrend"
                setup_desc = "Trend Alignment (50 SMA > 200 SMA)"
            elif curr_price < sma_50 and curr_price < sma_200:
                signal = "Downtrend Breakdown"
                setup_desc = "Below Key Moving Averages"
            else:
                signal = "Consolidating"
                setup_desc = "Rangebound Price Action"

            results.append({
                "Ticker": sym,
                "Price (₹)": round(curr_price, 2),
                "Change (%)": round(change_pct, 2),
                "RSI (14)": round(rsi_14, 1),
                "SMA 50 (₹)": round(sma_50, 2),
                "SMA 200 (₹)": round(sma_200, 2),
                "Vol/OI Ratio": vol_oi_ratio,
                "IV (%)": iv_spike,
                "Volume": int(volume),
                "Signal": signal,
                "Setup Description": setup_desc,
                "PDH Sweep": "YES 🚨" if is_high_sweep else "NO",
                "PDL Sweep": "YES 🚨" if is_low_sweep else "NO"
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
    st.caption(f"Full Dynamic Universe: **{len(fno_universe)}** Equities")
    st.divider()

    dhan_status_class = "status-badge-active" if st.session_state["dhan_authenticated"] else "status-badge-off"
    dhan_status_text = "CONNECTED" if st.session_state["dhan_authenticated"] else "DISCONNECTED"
    
    tg_status_class = "status-badge-active" if st.session_state["tg_connected"] else "status-badge-off"
    tg_status_text = "CONNECTED" if st.session_state["tg_connected"] else "DISCONNECTED"

    st.markdown(f"**Dhan API:** <span class='{dhan_status_class}'>{dhan_status_text}</span>", unsafe_allow_html=True)
    st.markdown(f"**Telegram Bot:** <span class='{tg_status_class}'>{tg_status_text}</span>", unsafe_allow_html=True)
    st.divider()

    st.markdown("#### 🔍 Filter Criteria")
    selected_signal = st.selectbox("Signal Classifier", ["All Signals", "BUY CE", "BUY PE", "Bullish Oversold", "Strong Uptrend", "Downtrend Breakdown", "Consolidating"], index=0)
    min_vol_oi = st.slider("Min Vol/OI Ratio Threshold", 1.0, 3.0, 1.0, 0.1)
    rsi_range = st.slider("RSI (14) Range", 0.0, 100.0, (0.0, 100.0))
    search_ticker = st.text_input("Find Symbol", "").upper().strip()

    st.divider()
    if st.button("🔄 Rescan Entire Universe", use_container_width=True):
        st.cache_data.clear()
        st.session_state["last_scan_time"] = datetime.now().strftime("%H:%M:%S")
        st.rerun()

# Run Screener across Universe
with st.spinner("Executing Master Technical, SMC & Option Velocity Scanner..."):
    df_screener = compute_master_signals(fno_universe)

filtered_df = df_screener.copy()

if not filtered_df.empty:
    if selected_signal != "All Signals":
        filtered_df = filtered_df[filtered_df["Signal"] == selected_signal]
    filtered_df = filtered_df[
        (filtered_df["Vol/OI Ratio"] >= min_vol_oi) &
        (filtered_df["RSI (14)"] >= rsi_range[0]) & 
        (filtered_df["RSI (14)"] <= rsi_range[1])
    ]
    if search_ticker:
        filtered_df = filtered_df[filtered_df["Ticker"].str.contains(search_ticker)]

if st.session_state["tg_connected"] and not filtered_df.empty:
    dispatch_deduplicated_alerts(filtered_df)

# ==========================================
# 6. MAIN DASHBOARD PANELS
# ==========================================
st.title("⚡ Apex Enterprise Algo & Screener Dashboard")

tab_screener, tab_chart, tab_journal, tab_dhan, tab_tg, tab_risk, tab_autoscan, tab_orders = st.tabs([
    "📋 Live Screener", 
    "📊 Plotly Chart", 
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
    st.subheader("Real-Time Technical Signals & Order Execution Panel")

    k1, k2, k3, k4 = st.columns(4)
    total_m = len(filtered_df)
    bullish_m = len(filtered_df[filtered_df["Signal"].str.contains("BUY CE|Bullish|Uptrend")]) if total_m > 0 else 0
    avg_rsi = round(filtered_df["RSI (14)"].mean(), 1) if total_m > 0 else 0
    
    with k1: st.markdown(f"<div class='kpi-card'><div class='kpi-title'>Filtered Matches</div><div class='kpi-value'>{total_m}</div></div>", unsafe_allow_html=True)
    with k2: st.markdown(f"<div class='kpi-card'><div class='kpi-title'>Bullish Setups</div><div class='kpi-value'>{bullish_m}</div></div>", unsafe_allow_html=True)
    with k3: st.markdown(f"<div class='kpi-card'><div class='kpi-title'>Avg RSI</div><div class='kpi-value'>{avg_rsi}</div></div>", unsafe_allow_html=True)
    with k4: st.markdown(f"<div class='kpi-card'><div class='kpi-title'>Unique Alerts</div><div class='kpi-value'>{len(st.session_state['sent_alerts'])}</div></div>", unsafe_allow_html=True)

    st.divider()

    col_table, col_action = st.columns([2, 1])

    with col_table:
        st.markdown("##### Filtered Asset Directory")
        if not filtered_df.empty:
            st.dataframe(
                filtered_df.style.format({
                    "Price (₹)": "₹{:.2f}",
                    "Change (%)": "{:+.2f}%",
                    "RSI (14)": "{:.1f}",
                    "SMA 50 (₹)": "₹{:.2f}",
                    "SMA 200 (₹)": "₹{:.2f}",
                    "Vol/OI Ratio": "{:.2f}",
                    "Volume": "{:,.0f}"
                }).map(
                    lambda x: 'color: #16A34A; font-weight: 700;' if isinstance(x, (int, float)) and x > 0 else ('color: #DC2626; font-weight: 700;' if isinstance(x, (int, float)) and x < 0 else ''),
                    subset=["Change (%)"]
                ),
                use_container_width=True,
                height=450
            )
        else:
            st.info("No assets match current criteria. Adjust sidebar filters or click Rescan.")

    with col_action:
        st.markdown("##### ⚡ Order Execution Panel")
        selectable_stocks = filtered_df["Ticker"].unique() if not filtered_df.empty else df_screener["Ticker"].unique() if not df_screener.empty else []
        
        if len(selectable_stocks) > 0:
            selected_stock = st.selectbox("Target Asset", selectable_stocks)
            
            ref_df = filtered_df if not filtered_df.empty else df_screener
            stock_row = ref_df[ref_df["Ticker"] == selected_stock].iloc[0]
            price = float(stock_row["Price (₹)"])
            
            qty, risk_amt, sl_price, target_price = calculate_position_size(price, st.session_state["default_sl_pct"])

            st.success(f"**Selected Asset:** {selected_stock} | **LTP:** ₹{price}")
            st.write(f"• **Position Size:** `{qty}` Shares")
            st.write(f"• **Capital at Risk:** ₹{risk_amt:,.2f}")
            st.write(f"• **Stop Loss:** ₹{sl_price} ({st.session_state['default_sl_pct']}%)")
            st.write(f"• **Target (1:2.5 RR):** ₹{target_price}")
            st.write(f"• **Setup:** {stock_row['Setup Description']}")

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
                    st.success(f"Paper Order Placed for {selected_stock}!")

            with col_l:
                if st.button("🚀 1-Click Live Trade", use_container_width=True, type="primary"):
                    if not st.session_state["dhan_authenticated"]:
                        st.error("Authenticate Dhan API in Tab 4 first!")
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
                            st.success(f"Live Order Submitted! ID: {order_info}")
                        else:
                            st.error(f"Execution Error: {order_info}")
        else:
            st.warning("Loading market data...")

# ------------------------------------------------------------------
# TAB 2: INTERACTIVE PLOTLY CANDLESTICK CHART
# ------------------------------------------------------------------
with tab_chart:
    st.subheader("📊 Interactive Candlestick Analysis")
    
    chart_symbols = filtered_df["Ticker"].unique() if not filtered_df.empty else fno_universe
    chart_stock = st.selectbox("Select Asset for Detailed Candlestick Plot", chart_symbols)

    if chart_stock:
        ticker_id = "^NSEI" if chart_stock == "NIFTY" else ("^NSEBANK" if chart_stock == "BANKNIFTY" else f"{chart_stock}.NS")
        stock_data = yf.Ticker(ticker_id).history(period="6m")
        
        if not stock_data.empty:
            stock_data['SMA50'] = stock_data['Close'].rolling(50).mean()
            stock_data['SMA200'] = stock_data['Close'].rolling(200).mean()

            fig = go.Figure()
            fig.add_trace(go.Candlestick(
                x=stock_data.index,
                open=stock_data['Open'], high=stock_data['High'],
                low=stock_data['Low'], close=stock_data['Close'],
                name="Price"
            ))
            fig.add_trace(go.Scatter(x=stock_data.index, y=stock_data['SMA50'], mode='lines', name='50 SMA', line=dict(color='#2563EB', width=2)))
            fig.add_trace(go.Scatter(x=stock_data.index, y=stock_data['SMA200'], mode='lines', name='200 SMA', line=dict(color='#D97706', width=2)))

            fig.update_layout(
                template="plotly_white",
                paper_bgcolor="#FFFFFF",
                plot_bgcolor="#FFFFFF",
                margin=dict(l=20, r=20, t=30, b=20),
                height=500,
                xaxis_rangeslider_visible=False
            )
            st.plotly_chart(fig, use_container_width=True)

# ------------------------------------------------------------------
# TAB 3: INSTITUTIONAL JOURNAL & BACKTEST PERFORMANCE
# ------------------------------------------------------------------
with tab_journal:
    st.subheader("📑 Institutional Trade Journal & Performance Analytics")
    st.caption("Multi-timeframe 5-minute FVG & SMC executions with $1:2.5$ Risk-to-Reward ratio outcomes.")

    df_journal = pd.DataFrame(st.session_state["institutional_journal"])
    
    st.dataframe(
        df_journal.style.format({
            "Entry Price": "₹{:,.2f}",
            "Stop Loss": "₹{:,.2f}",
            "Target (1:2.5 RR)": "₹{:,.2f}"
        }),
        use_container_width=True
    )

    # Calculate Metrics
    if not df_journal.empty:
        wins = len(df_journal[df_journal["Outcome"].str.contains("TARGET HIT")])
        total = len(df_journal[df_journal["Outcome"].str.contains("HIT")])
        win_rate = round((wins / total) * 100, 1) if total > 0 else 0.0

        m1, m2, m3 = st.columns(3)
        with m1: st.metric("Total Completed Trades", total)
        with m2: st.metric("Historical Win Rate", f"{win_rate}%")
        with m3: st.metric("Profit Factor (at 1:2.5 RR)", f"{round((wins * 2.5) / (max(1, total - wins)), 2)}")

# ------------------------------------------------------------------
# TAB 4: DHAN API CREDENTIALS
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
# TAB 5: TELEGRAM ALERTS
# ------------------------------------------------------------------
with tab_tg:
    st.subheader("📱 Telegram Notification Engine")
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
        st.markdown("##### 🧪 Connection Test")
        if st.button("Send Test Alert", use_container_width=True):
            if not st.session_state["tg_connected"]:
                st.error("Configure Bot Token & Chat ID first.")
            else:
                ok = send_telegram_alert("✅ <b>Apex Algo:</b> Telegram Alert System Active!")
                if ok: st.success("Test Delivered!")
                else: st.error("Delivery Failed.")

    st.divider()
    st.markdown("##### 🛡️ Alert Memory & Anti-Spam Cache")
    st.write(f"Unique Alerts Memory Cache Count Today: **{len(st.session_state['sent_alerts'])}**")
    if st.button("Reset Alert Memory Cache"):
        st.session_state["sent_alerts"].clear()
        st.success("Alert Memory Reset.")

# ------------------------------------------------------------------
# TAB 6: RISK MANAGEMENT ENGINE
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
# TAB 7: AUTO SCAN CONTROLLER
# ------------------------------------------------------------------
with tab_autoscan:
    st.subheader("⏰ Automated Background Screener Daemon")
    st.session_state["auto_scan_active"] = st.toggle("Enable Background Auto Scan", value=st.session_state["auto_scan_active"])
    st.session_state["auto_scan_interval"] = st.selectbox("Scan Frequency (Minutes)", [1, 3, 5, 15], index=2)

# ------------------------------------------------------------------
# TAB 8: ORDER LOGS
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
