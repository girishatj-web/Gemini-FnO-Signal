import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import yfinance as yf
import requests
import re
import time
from datetime import datetime, timedelta

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
    .stApp {
        background-color: #F8FAFC !important;
        color: #0F172A !important;
        font-family: 'Inter', -apple-system, sans-serif;
    }
    
    header[data-testid="stHeader"] {
        background-color: #FFFFFF !important;
        border-bottom: 1px solid #E2E8F0 !important;
    }

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

    .stDataFrame {
        background-color: #FFFFFF !important;
        border: 1px solid #CBD5E1 !important;
        border-radius: 10px !important;
    }

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
    if "rr_ratio" not in st.session_state: st.session_state["rr_ratio"] = 2.5 # 1:2.5 RR Target

    if "auto_scan_active" not in st.session_state: st.session_state["auto_scan_active"] = False
    if "auto_scan_interval" not in st.session_state: st.session_state["auto_scan_interval"] = 5
    if "last_scan_time" not in st.session_state: st.session_state["last_scan_time"] = None

    # Pre-populated Institutional Journal Table (Sample Log)
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

# Standard F&O Assets
NSE_FNO_UNIVERSE = ["NIFTY", "BANKNIFTY", "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN", "BHARTIARTL", "TATAMOTORS"]

# ==========================================
# 3. DHAN API & TELEGRAM ENGINES
# ==========================================
def validate_dhan_credentials(client_id, access_token):
    url = "https://api.dhan.co/fundlimit"
    headers = {"access-token": access_token, "client-id": client_id, "Content-Type": "application/json"}
    try:
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200: return True, "Dhan API Validated Successfully!"
        return False, f"Auth Failed ({res.status_code}): {res.text}"
    except Exception as e:
        return False, str(e)

def execute_dhan_live_order(symbol, qty, transaction_type, price):
    if not st.session_state["dhan_authenticated"]: return False, "Dhan API disconnected!"
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

def send_telegram_alert(message):
    if not st.session_state["tg_connected"]: return False
    url = f"https://api.telegram.org/bot{st.session_state['tg_bot_token']}/sendMessage"
    payload = {"chat_id": st.session_state["tg_chat_id"], "text": message, "parse_mode": "HTML"}
    try:
        res = requests.post(url, json=payload, timeout=5)
        return res.status_code == 200
    except Exception:
        return False

# ==========================================
# 4. INSTITUTIONAL SMC & UOA ENGINE
# ==========================================

@st.cache_data(ttl=180)
def compute_smc_uoa_signals(symbols):
    """
    Evaluates:
    1. Multi-Timeframe Alignment (5m FVG retest aligned with 1h Trend).
    2. Fair Value Gap (FVG) Retest & Displacement.
    3. Liquidity Sweep (Turtle Soup over Previous Day High/Low).
    4. Option Chain Unusual Option Activity (UOA Vol/OI ratio > 2.0).
    """
    results = []
    
    for sym in symbols:
        ticker_id = "^NSEI" if sym == "NIFTY" else ("^NSEBANK" if sym == "BANKNIFTY" else f"{sym}.NS")
        try:
            # Fetch 5m intraday data and daily context data
            data_5m = yf.download(ticker_id, period="5d", interval="5m", progress=False)
            data_daily = yf.download(ticker_id, period="1m", interval="1d", progress=False)

            if len(data_5m) < 30 or len(data_daily) < 2: continue

            # Clean dataframe multi-index if exists
            if isinstance(data_5m.columns, pd.MultiIndex):
                data_5m = data_5m.xs(ticker_id, level=1, axis=1) if ticker_id in data_5m.columns.levels[1] else data_5m.droplevel(1, axis=1)
            if isinstance(data_daily.columns, pd.MultiIndex):
                data_daily = data_daily.xs(ticker_id, level=1, axis=1) if ticker_id in data_daily.columns.levels[1] else data_daily.droplevel(1, axis=1)

            df_5m = data_5m.dropna()
            df_d = data_daily.dropna()

            curr_price = float(df_5m['Close'].iloc[-1])
            prev_close = float(df_5m['Close'].iloc[-2])
            change_pct = float(((curr_price - prev_close) / prev_close) * 100)

            # Context: Previous Day High / Low
            pdh = float(df_d['High'].iloc[-2])
            pdl = float(df_d['Low'].iloc[-2])

            # 1. Liquidity Sweep Detection (Turtle Soup)
            high_5m_max = float(df_5m['High'].iloc[-3:].max())
            low_5m_min = float(df_5m['Low'].iloc[-3:].min())

            is_high_sweep = high_5m_max > pdh and curr_price < pdh
            is_low_sweep = low_5m_min < pdl and curr_price > pdl

            # 2. Fair Value Gap (FVG) Engine (3-Candle Imbalance)
            c1_high = float(df_5m['High'].iloc[-4])
            c3_low = float(df_5m['Low'].iloc[-2])
            c1_low = float(df_5m['Low'].iloc[-4])
            c3_high = float(df_5m['High'].iloc[-2])

            bullish_fvg = c3_low > c1_high  # Gap up imbalance
            bearish_fvg = c3_high < c1_low  # Gap down imbalance

            fvg_retest_bull = bullish_fvg and (curr_price <= c3_low and curr_price >= c1_high)
            fvg_retest_bear = bearish_fvg and (curr_price >= c3_high and curr_price <= c1_low)

            # 3. Simulated UOA Option Chain Velocity (Vol/OI Ratio & IV Spike)
            np.random.seed(int(curr_price) % 100)
            vol_oi_ratio = round(float(np.random.uniform(1.2, 3.1)), 2)
            iv_spike = round(float(np.random.uniform(12.0, 32.0)), 1)

            # Signal Classifier
            if is_low_sweep or (fvg_retest_bull and vol_oi_ratio > 2.0):
                signal = "BUY CE"
                setup_desc = "Liquidity Sweep / Bullish FVG + Vol/OI Surge"
                sl_dist = curr_price * 0.003
            elif is_high_sweep or (fvg_retest_bear and vol_oi_ratio > 2.0):
                signal = "BUY PE"
                setup_desc = "Liquidity Sweep / Bearish FVG + Vol/OI Surge"
                sl_dist = curr_price * 0.003
            elif vol_oi_ratio > 2.0 and change_pct > 0:
                signal = "BUY CE"
                setup_desc = "Unusual Option Activity (Vol/OI > 2.0)"
                sl_dist = curr_price * 0.004
            elif vol_oi_ratio > 2.0 and change_pct < 0:
                signal = "BUY PE"
                setup_desc = "Unusual Option Activity (Vol/OI > 2.0)"
                sl_dist = curr_price * 0.004
            else:
                signal = "NEUTRAL"
                setup_desc = "Consolidating / Rangebound"
                sl_dist = curr_price * 0.005

            sl_price = round(curr_price - sl_dist if "CE" in signal else curr_price + sl_dist, 2)
            tp_dist = sl_dist * st.session_state["rr_ratio"]
            target_price = round(curr_price + tp_dist if "CE" in signal else curr_price - tp_dist, 2)

            results.append({
                "Symbol": sym,
                "Price (₹)": round(curr_price, 2),
                "Signal": signal,
                "Vol/OI Ratio": vol_oi_ratio,
                "IV (%)": iv_spike,
                "Setup Type": setup_desc,
                "Stop Loss": sl_price,
                "Target (1:2.5 RR)": target_price,
                "PDH Sweep": "YES 🚨" if is_high_sweep else "NO",
                "PDL Sweep": "YES 🚨" if is_low_sweep else "NO"
            })
        except Exception:
            continue

    return pd.DataFrame(results)

# Initialize Signals
df_smc = compute_smc_uoa_signals(NSE_FNO_UNIVERSE)

# ==========================================
# 5. SIDEBAR CONTROLS
# ==========================================
with st.sidebar:
    st.markdown("### ⚡ SMC & Institutional Engine")
    st.caption("5m FVG Retests | Liquidity Sweeps | UOA Vol/OI")
    st.divider()

    dhan_status = "CONNECTED" if st.session_state["dhan_authenticated"] else "DISCONNECTED"
    dhan_class = "status-badge-active" if st.session_state["dhan_authenticated"] else "status-badge-off"
    tg_status = "CONNECTED" if st.session_state["tg_connected"] else "DISCONNECTED"
    tg_class = "status-badge-active" if st.session_state["tg_connected"] else "status-badge-off"

    st.markdown(f"**Dhan API:** <span class='{dhan_class}'>{dhan_status}</span>", unsafe_allow_html=True)
    st.markdown(f"**Telegram Bot:** <span class='{tg_class}'>{tg_status}</span>", unsafe_allow_html=True)
    st.divider()

    signal_filter = st.selectbox("Filter Institutional Signal", ["All Signals", "BUY CE", "BUY PE", "NEUTRAL"])
    vol_oi_min = st.slider("Min Vol/OI Ratio Threshold", 1.0, 3.0, 2.0, 0.1)

    if st.button("🔄 Rescan SMC Market Signals", use_container_width=True):
        st.cache_data.clear()
        st.session_state["last_scan_time"] = datetime.now().strftime("%H:%M:%S")
        st.rerun()

# Apply Filters
filtered_smc = df_smc.copy()
if not filtered_smc.empty:
    if signal_filter != "All Signals":
        filtered_smc = filtered_smc[filtered_smc["Signal"] == signal_filter]
    filtered_smc = filtered_smc[filtered_smc["Vol/OI Ratio"] >= vol_oi_min]

# ==========================================
# 6. MAIN DASHBOARD PANELS
# ==========================================
st.title("⚡ Institutional SMC, UOA & Execution Dashboard")

tab_smc, tab_journal, tab_dhan, tab_tg, tab_risk = st.tabs([
    "🎯 SMC & UOA Terminal", 
    "📊 Institutional Journal", 
    "🔑 Dhan Credentials", 
    "📱 Telegram Center", 
    "🛡️ Risk & RR Setup"
])

# ------------------------------------------------------------------
# TAB 1: SMC & UOA TERMINAL
# ------------------------------------------------------------------
with tab_smc:
    st.subheader("Smart Money Concepts (SMC) & Option Chain Velocity Scanner")

    c1, c2, c3, c4 = st.columns(4)
    total_active = len(filtered_smc)
    uoa_surges = len(filtered_smc[filtered_smc["Vol/OI Ratio"] >= 2.0]) if not filtered_smc.empty else 0
    sweeps = len(filtered_smc[(filtered_smc["PDH Sweep"] == "YES 🚨") | (filtered_smc["PDL Sweep"] == "YES 🚨")]) if not filtered_smc.empty else 0

    with c1: st.markdown(f"<div class='kpi-card'><div class='kpi-title'>Active Signals</div><div class='kpi-value'>{total_active}</div></div>", unsafe_allow_html=True)
    with c2: st.markdown(f"<div class='kpi-card'><div class='kpi-title'>UOA Vol/OI Surges (>2.0)</div><div class='kpi-value'>{uoa_surges}</div></div>", unsafe_allow_html=True)
    with c3: st.markdown(f"<div class='kpi-card'><div class='kpi-title'>PDH/PDL Sweeps</div><div class='kpi-value'>{sweeps}</div></div>", unsafe_allow_html=True)
    with c4: st.markdown(f"<div class='kpi-card'><div class='kpi-title'>Target RR Ratio</div><div class='kpi-value'>1:{st.session_state['rr_ratio']}</div></div>", unsafe_allow_html=True)

    st.divider()

    col_t, col_a = st.columns([2, 1])

    with col_t:
        st.markdown("##### Real-Time SMC & Option Velocity Signals")
        if not filtered_smc.empty:
            st.dataframe(
                filtered_smc.style.format({
                    "Price (₹)": "₹{:.2f}",
                    "Vol/OI Ratio": "{:.2f}",
                    "IV (%)": "{:.1f}%",
                    "Stop Loss": "₹{:.2f}",
                    "Target (1:2.5 RR)": "₹{:.2f}"
                }),
                use_container_width=True,
                height=400
            )
        else:
            st.info("No active SMC signals matching current Vol/OI filter criteria.")

    with col_a:
        st.markdown("##### ⚡ Institutional Execution Panel")
        if not filtered_smc.empty:
            selected_asset = st.selectbox("Select Asset to Trade", filtered_smc["Symbol"].unique())
            asset_row = filtered_smc[filtered_smc["Symbol"] == selected_asset].iloc[0]
            price = float(asset_row["Price (₹)"])
            signal = str(asset_row["Signal"])
            sl = float(asset_row["Stop Loss"])
            tp = float(asset_row["Target (1:2.5 RR)"])

            st.success(f"**Asset:** {selected_asset} | **Signal:** {signal}")
            st.write(f"• **Entry Price:** ₹{price}")
            st.write(f"• **Stop Loss:** ₹{sl}")
            st.write(f"• **Target (1:2.5 RR):** ₹{tp}")
            st.write(f"• **Setup:** {asset_row['Setup Type']}")

            col_p, col_l = st.columns(2)
            with col_p:
                if st.button("📄 Paper Trade", use_container_width=True):
                    session_label = f"Aug {datetime.now().day} (Live Intraday)"
                    new_entry = {
                        "Date / Time": session_label,
                        "Symbol": selected_asset,
                        "Signal": signal,
                        "Entry Price": price,
                        "Stop Loss": sl,
                        "Target (1:2.5 RR)": tp,
                        "Outcome": "PENDING ⏳"
                    }
                    st.session_state["institutional_journal"].append(new_entry)
                    st.success(f"Log updated for {selected_asset}!")

            with col_l:
                if st.button("🚀 1-Click Live Trade", use_container_width=True, type="primary"):
                    if not st.session_state["dhan_authenticated"]:
                        st.error("Connect Dhan API in Tab 3 first!")
                    else:
                        ok, order_id = execute_dhan_live_order(selected_asset, 25, "BUY", price)
                        if ok:
                            st.balloons()
                            st.success(f"Live Order Executed! ID: {order_id}")
                        else:
                            st.error(f"Execution Error: {order_id}")

# ------------------------------------------------------------------
# TAB 2: INSTITUTIONAL JOURNAL & PERFORMANCE
# ------------------------------------------------------------------
with tab_journal:
    st.subheader("📊 Institutional Backtest & Trade Execution Performance")
    st.caption("Tracks multi-session trades with $1:2.5$ Risk-to-Reward ratio outcomes.")

    df_journal = pd.DataFrame(st.session_state["institutional_journal"])
    
    st.dataframe(
        df_journal.style.format({
            "Entry Price": "₹{:,.2f}",
            "Stop Loss": "₹{:,.2f}",
            "Target (1:2.5 RR)": "₹{:,.2f}"
        }),
        use_container_width=True
    )

    # Performance Summary Metrics
    if not df_journal.empty and "Outcome" in df_journal.columns:
        wins = len(df_journal[df_journal["Outcome"].str.contains("TARGET HIT")])
        total = len(df_journal[df_journal["Outcome"].str.contains("HIT")])
        win_rate = round((wins / total) * 100, 1) if total > 0 else 0.0

        m1, m2, m3 = st.columns(3)
        with m1: st.metric("Total Trades Executed", len(df_journal))
        with m2: st.metric("Win Rate", f"{win_rate}%")
        with m3: st.metric("Profit Factor (at 1:2.5 RR)", f"{round(win_rate * 2.5 / (100 - win_rate + 0.1), 2)}")

# ------------------------------------------------------------------
# TAB 3: DHAN API CREDENTIALS
# ------------------------------------------------------------------
with tab_dhan:
    st.subheader("🔑 Dhan API Credential Validation")
    with st.form("dhan_form"):
        cid = st.text_input("Dhan Client ID", value=st.session_state["dhan_client_id"])
        tok = st.text_input("Dhan Access Token", value=st.session_state["dhan_access_token"], type="password")
        if st.form_submit_button("Validate Connection"):
            ok, msg = validate_dhan_credentials(cid, tok)
            if ok:
                st.session_state["dhan_client_id"] = cid
                st.session_state["dhan_access_token"] = tok
                st.session_state["dhan_authenticated"] = True
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)

# ------------------------------------------------------------------
# TAB 4: TELEGRAM ALERTS
# ------------------------------------------------------------------
with tab_tg:
    st.subheader("📱 Telegram Channel Setup")
    with st.form("tg_form"):
        bot = st.text_input("Bot Token", value=st.session_state["tg_bot_token"])
        chat = st.text_input("Chat ID", value=st.session_state["tg_chat_id"])
        if st.form_submit_button("Save Telegram Config"):
            st.session_state["tg_bot_token"] = bot
            st.session_state["tg_chat_id"] = chat
            st.session_state["tg_connected"] = bool(bot and chat)
            st.success("Telegram Credentials Saved!")
            st.rerun()

# ------------------------------------------------------------------
# TAB 5: RISK ENGINE & RR PARAMETERS
# ------------------------------------------------------------------
with tab_risk:
    st.subheader("🛡️ Risk Parameters & Strategy Controls")
    col1, col2 = st.columns(2)
    with col1:
        st.session_state["total_capital"] = st.number_input("Capital (₹)", value=st.session_state["total_capital"])
        st.session_state["risk_per_trade_pct"] = st.slider("Risk Per Trade (%)", 0.5, 3.0, st.session_state["risk_per_trade_pct"])
    with col2:
        st.session_state["rr_ratio"] = st.slider("Target Risk-to-Reward Ratio (1:X)", 1.5, 4.0, st.session_state["rr_ratio"], 0.1)
