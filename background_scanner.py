import os
import pandas as pd
import numpy as np
import requests
import re
from datetime import datetime
import yfinance as yf
import json

# Load Environment Variables (Injected via GitHub Actions Secrets)
DHAN_CLIENT_ID = os.environ.get("DHAN_CLIENT_ID", "")
DHAN_ACCESS_TOKEN = os.environ.get("DHAN_ACCESS_TOKEN", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

CACHE_FILE = "sent_alerts_cache.json"

def load_sent_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()

def save_sent_cache(sent_set):
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(list(sent_set), f)
    except Exception:
        pass

NSE_FNO_FALLBACK = [
    "NIFTY", "BANKNIFTY", "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN", "BHARTIARTL", "TATAMOTORS",
    "LTIM", "AXISBANK", "KOTAKBANK", "ITC", "LT", "HINDUNILVR", "BAJFINANCE", "MARUTI", "SUNPHARMA", "TATASTEEL", "HAL", "COCHINSHIP"
]

DHAN_SCRIP_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"

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
        clean_symbols = set(["NIFTY", "BANKNIFTY", "HAL", "COCHINSHIP"])
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

def get_dhan_security_id(symbol):
    try:
        df_master = pd.read_csv(DHAN_SCRIP_MASTER_URL, low_memory=False)
        match = df_master[(df_master['SEM_TRADING_SYMBOL'].astype(str).str.upper() == symbol) & (df_master['SEM_EXM_EXCH_ID'].astype(str).str.upper() == 'NSE')]
        if match.empty:
            match = df_master[df_master['SEM_CUSTOM_SYMBOL'].astype(str).str.upper() == symbol]
        if not match.empty:
            return int(match.iloc[0]['SEM_SECURITY_ID'])
    except Exception:
        pass
    
    defaults = {"NIFTY": 13, "BANKNIFTY": 25, "RELIANCE": 2885, "TCS": 11536, "HAL": 10940, "COCHINSHIP": 15462}
    return defaults.get(symbol, 0)

def fetch_dhan_live_option_contract_price(symbol, strike, option_type):
    if not DHAN_CLIENT_ID or not DHAN_ACCESS_TOKEN:
        return None
    sec_id = get_dhan_security_id(symbol)
    if not sec_id:
        return None
    
    url = "https://api.dhan.co/v2/optionchain"
    headers = {"access-token": DHAN_ACCESS_TOKEN, "client-id": DHAN_CLIENT_ID, "Content-Type": "application/json"}
    payload = {
        "UnderlyingScrip": int(sec_id),
        "UnderlyingSeg": "IDX_I" if symbol in ["NIFTY", "BANKNIFTY"] else "NSE_EQ"
    }
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=5)
        if res.status_code == 200:
            oc_data = res.json().get("data", {}).get("oc", {})
            strike_keys = list(oc_data.keys())
            if not strike_keys:
                return None
            closest_key = min(strike_keys, key=lambda x: abs(float(x) - float(strike)))
            if abs(float(closest_key) - float(strike)) <= (20.0 if symbol in ["NIFTY", "BANKNIFTY"] else 15.0):
                contract_data = oc_data[closest_key].get(option_type.lower(), {})
                ltp = contract_data.get("last_price", 0.0)
                if ltp and ltp > 0:
                    return float(ltp)
        return None
    except Exception:
        return None

def fetch_dhan_live_option_chain_vol_oi(symbol):
    if not DHAN_CLIENT_ID or not DHAN_ACCESS_TOKEN:
        return None
    sec_id = get_dhan_security_id(symbol)
    url = "https://api.dhan.co/v2/optionchain"
    headers = {"access-token": DHAN_ACCESS_TOKEN, "client-id": DHAN_CLIENT_ID, "Content-Type": "application/json"}
    payload = {
        "UnderlyingScrip": int(sec_id) if sec_id else (13 if symbol == "NIFTY" else 25),
        "UnderlyingSeg": "IDX_I" if symbol in ["NIFTY", "BANKNIFTY"] else "NSE_EQ"
    }
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=4)
        if res.status_code == 200:
            oc_data = res.json().get("data", {}).get("oc", {})
            total_oi = sum([item.get(opt, {}).get("oi", 1) for item in oc_data.values() if isinstance(item, dict) for opt in ['ce', 'pe']])
            total_vol = sum([item.get(opt, {}).get("volume", 0) for item in oc_data.values() if isinstance(item, dict) for opt in ['ce', 'pe']])
            return round(total_vol / max(1, total_oi), 2)
        return None
    except Exception:
        return None

def send_telegram_alert(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        res = requests.post(url, json=payload, timeout=5)
        return res.status_code == 200
    except Exception:
        return False

def get_option_contract_pricing(symbol, spot_price, signal, sl_pct=1.5, rr_ratio=2.5):
    if signal not in ["BUY CE", "BUY PE"]:
        return "N/A", 0.0, 0.0, 0.0, 0.0

    step = 50 if symbol == "NIFTY" else (100 if symbol == "BANKNIFTY" else (100 if spot_price > 3000 else (20 if spot_price > 1000 else (10 if spot_price > 500 else 5))))
    atm_strike = int(round(spot_price / step) * step)
    option_type = "CE" if "CE" in signal else "PE"
    strike_label = f"{symbol} {atm_strike} {option_type}"

    live_contract_price = fetch_dhan_live_option_contract_price(symbol, atm_strike, option_type)
    option_price = round(live_contract_price, 2) if live_contract_price and live_contract_price > 0 else round(spot_price * 0.025, 2)

    option_risk = option_price * (sl_pct / 2.0)
    option_sl = round(max(0.5, option_price - option_risk), 2)
    option_target = round(option_price + (option_risk * rr_ratio), 2)
    option_tsl = round(option_sl + (option_risk * 0.4), 2)

    return strike_label, option_price, option_sl, option_target, option_tsl

def run_scanner():
    print("🚀 Starting Automated Background Scan...")
    symbols = fetch_dhan_fno_universe()[:100]
    
    yf_tickers = []
    for sym in symbols:
        if sym == "NIFTY": yf_tickers.append("^NSEI")
        elif sym == "BANKNIFTY": yf_tickers.append("^NSEBANK")
        else: yf_tickers.append(f"{sym}.NS")

    try:
        data = yf.download(yf_tickers, period="5d", interval="5m", group_by="ticker", progress=False, threads=True)
    except Exception as e:
        print(f"Error downloading data: {e}")
        return

    sent_cache = load_sent_cache()
    today_str = datetime.now().strftime("%Y-%m-%d")

    for sym in symbols:
        ticker_id = "^NSEI" if sym == "NIFTY" else ("^NSEBANK" if sym == "BANKNIFTY" else f"{sym}.NS")
        try:
            if len(symbols) == 1:
                df_stock = data.dropna()
            else:
                if ticker_id not in data.columns.levels[0]: continue
                df_stock = data[ticker_id].dropna()

            if len(df_stock) < 30: continue

            close = df_stock['Close']
            curr_price = float(close.iloc[-1])
            
            delta = close.diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss
            rsi_14 = float((100 - (100 / (1 + rs))).iloc[-1])
            sma_50 = float(close.rolling(50).mean().iloc[-1]) if len(df_stock) >= 50 else float(close.mean())

            last_date = df_stock.index[-1].date()
            past_df = df_stock[df_stock.index.date < last_date]
            if not past_df.empty:
                prev_day_candles = past_df[past_df.index.date == past_df.index.date[-1]]
                pdh = float(prev_day_candles['High'].max())
                pdl = float(prev_day_candles['Low'].min())
            else:
                pdh = float(df_stock['High'].iloc[0])
                pdl = float(df_stock['Low'].iloc[0])

            pdh_break = curr_price > pdh and float(close.iloc[-2]) <= pdh
            pdl_break = curr_price < pdl and float(close.iloc[-2]) >= pdl

            real_vol_oi = fetch_dhan_live_option_chain_vol_oi(sym) or 1.5
            is_uptrend = curr_price > sma_50
            is_downtrend = curr_price < sma_50
            strong_volume = real_vol_oi >= 1.5

            signal = "HOLD"
            if pdh_break and is_uptrend and strong_volume and (45 <= rsi_14 <= 75):
                signal = "BUY CE"
            elif pdl_break and is_downtrend and strong_volume and (25 <= rsi_14 <= 55):
                signal = "BUY PE"

            if signal in ["BUY CE", "BUY PE"]:
                alert_key = f"{sym}_{signal}_5m_{today_str}"
                if alert_key not in sent_cache:
                    strike, opt_price, opt_sl, opt_target, opt_tsl = get_option_contract_pricing(sym, curr_price, signal)
                    msg = (
                        f"🚨 <b>APEX AUTOMATED BACKGROUND ALERT</b> 🚨\n\n"
                        f"<b>Symbol:</b> #{sym}\n"
                        f"<b>Signal:</b> {signal}\n"
                        f"<b>Option Contract:</b> {strike}\n"
                        f"<b>Live Contract LTP:</b> ₹{opt_price}\n"
                        f"<b>Stop Loss (SL):</b> ₹{opt_sl}\n"
                        f"<b>Trailing SL:</b> ₹{opt_tsl}\n"
                        f"<b>Target (1:2.5 RR):</b> ₹{opt_target}\n"
                        f"<b>RSI (14):</b> {rsi_14:.1f} | <b>Vol/OI:</b> {real_vol_oi}\n\n"
                        f"⚡ <i>GitHub Actions Autonomous Daemon</i>"
                    )
                    if send_telegram_alert(msg):
                        sent_cache.add(alert_key)
                        print(f"Alert sent successfully for {sym} {signal}")
        except Exception as ex:
            continue

    save_sent_cache(sent_cache)
    print("Background Scan Complete.")

if __name__ == "__main__":
    run_scanner()
