import logging
import random
import json
import asyncio
import cloudscraper
import requests
from curl_cffi import requests as curl_requests
import yfinance as yf
from telegram import Update, constants
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler
from keep_alive import keep_alive
from tradingview_ta import TA_Handler, Interval

# --- CONFIGURATION ---
BOT_TOKEN = '8266373667:AAE_Qrfq8VzMJTNE9Om9_rdbzscWFyBmgJU'

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# --- HELPER: THE KITCHEN SINK REQUESTER ---
def fetch_url_kitchen_sink(url, method="GET", json_data=None, headers=None):
    """
    Tries 3 different evasion techniques to get data.
    1. curl_cffi (Impersonates Chrome TLS Fingerprint)
    2. cloudscraper (Solves Cloudflare JS Challenges)
    3. Standard Requests (Rotates User-Agents)
    """
    if headers is None:
        headers = {}
    
    # Randomize User Agent for all requests
    user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15'
    ]
    headers['User-Agent'] = random.choice(user_agents)

    # --- ATTEMPT 1: curl_cffi (Best for TLS Blocking) ---
    try:
        # Impersonate Chrome 110 to pass TLS checks
        if method == "GET":
            resp = curl_requests.get(url, headers=headers, impersonate="chrome110", timeout=10)
        else:
            resp = curl_requests.post(url, json=json_data, headers=headers, impersonate="chrome110", timeout=10)
            
        if resp.status_code == 200:
            return resp.json(), None
    except Exception as e:
        pass # Silently fail to next method

    # --- ATTEMPT 2: cloudscraper (Best for JS Challenges) ---
    try:
        scraper = cloudscraper.create_scraper()
        if method == "GET":
            resp = scraper.get(url, headers=headers, timeout=10)
        else:
            resp = scraper.post(url, json=json_data, headers=headers, timeout=10)
            
        if resp.status_code == 200:
            return resp.json(), None
    except Exception as e:
        pass

    # --- ATTEMPT 3: Standard Requests (Last Resort) ---
    try:
        if method == "GET":
            resp = requests.get(url, headers=headers, timeout=10)
        else:
            resp = requests.post(url, json=json_data, headers=headers, timeout=10)
            
        if resp.status_code == 200:
            return resp.json(), None
        return None, f"Status {resp.status_code}"
    except Exception as e:
        return None, f"{type(e).__name__}"

# --- HELPER: FORMATTING ---
def format_with_emoji(value, change_pct=0):
    if value is None: return "N/A"
    if change_pct is None: change_pct = 0
    
    emoji = "🟢" if change_pct >= 0 else "🔴"
    sign = "+" if change_pct >= 0 else ""
    
    if value >= 1_000_000_000_000:
        val_str = f"${value / 1_000_000_000_000:.2f}T"
    elif value >= 1_000_000_000:
        val_str = f"${value / 1_000_000_000:.2f}B"
    else:
        val_str = f"${value:,.2f}"
        
    return f"{emoji} {val_str} ({sign}{change_pct:.2f}%)"

# ==========================================
#        DATA SOURCES
# ==========================================

def get_coincodex_data():
    data, err = fetch_url_kitchen_sink("https://coincodex.com/api/coincodex/get_global_metrics")
    if data:
        return {
            'source': 'CoinCodex',
            'total_cap': float(data['total_market_cap_usd']),
            'total_change': float(data.get('total_market_cap_24h_change', 0)),
            'total_vol': float(data.get('total_volume_usd', 0)),
            'btc_dom': float(data['btc_dominance']),
            'usdt_dom': 5.5, # Fallback
            'eth_dom': float(data['eth_dominance'])
        }, None
    return None, err

def get_coinstats_data():
    data, err = fetch_url_kitchen_sink("https://openapiv1.coinstats.app/global-markets")
    if data:
        return {
            'source': 'CoinStats',
            'total_cap': float(data['marketCap']),
            'total_change': float(data.get('marketCapChange', 0)),
            'total_vol': float(data.get('volume', 0)),
            'btc_dom': float(data['btcDominance']),
            'usdt_dom': 5.5,
            'eth_dom': 13.5
        }, None
    return None, err

def get_tradingview_scanner():
    url = "https://scanner.tradingview.com/crypto/scan"
    payload = {
        "symbols": {
            "tickers": ["CRYPTOCAP:TOTAL", "CRYPTOCAP:BTC.D", "CRYPTOCAP:USDT.D", "CRYPTOCAP:ETH.D"],
            "query": { "types": [] }
        },
        "columns": ["close", "open", "volume"]
    }
    # Headers are vital for TradingView
    h = {
        "Origin": "https://www.tradingview.com",
        "Referer": "https://www.tradingview.com/"
    }
    
    data, err = fetch_url_kitchen_sink(url, method="POST", json_data=payload, headers=h)
    
    if data:
        d = data['data']
        res = {}
        tickers = ["TOTAL", "BTC.D", "USDT.D", "ETH.D"]
        for i, t in enumerate(tickers):
            vals = d[i]['d']
            curr = vals[0]
            opn = vals[1]
            chg = ((curr - opn)/opn)*100 if opn else 0
            res[t] = {'val': curr, 'change': chg, 'vol': vals[2]}
            
        return {
            'source': 'TradingView',
            'total_cap': res['TOTAL']['val'],
            'total_change': res['TOTAL']['change'],
            'total_vol': res['TOTAL']['vol'],
            'btc_dom': res['BTC.D']['val'],
            'usdt_dom': res['USDT.D']['val'],
            'eth_dom': res['ETH.D']['val']
        }, None
    return None, err

def get_crypto_aggregated():
    # Priority 1: CoinCodex (Best Data)
    d, err = get_coincodex_data()
    if d: return d
    
    # Priority 2: TradingView (Scanner API)
    d, err = get_tradingview_scanner()
    if d: return d
    
    # Priority 3: CoinStats
    d, err = get_coinstats_data()
    if d: return d
    
    return None

def get_tvl_data():
    data, err = fetch_url_kitchen_sink("https://api.llama.fi/v2/historicalChainTvl")
    if data:
        curr = data[-1]['tvl']
        prev = data[-2]['tvl']
        change = ((curr - prev)/prev)*100
        return curr, change, "DeFiLlama"
    return None, None, f"Error: {err}"

def get_stock_data(ticker):
    # Try Direct API first via Kitchen Sink
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=2d"
    data, err = fetch_url_kitchen_sink(url)
    
    if data:
        try:
            quotes = data['chart']['result'][0]['indicators']['quote'][0]['close']
            valid = [x for x in quotes if x is not None]
            if len(valid) >= 2:
                curr = valid[-1]
                prev = valid[-2]
                return curr, ((curr-prev)/prev)*100, "Yahoo(API)"
        except: pass

    # Fallback to yfinance library
    try:
        t = yf.Ticker(ticker)
        h = t.history(period="2d")
        if len(h) >= 2:
            c = h['Close'].iloc[-1]
            p = h['Close'].iloc[-2]
            return c, ((c-p)/p)*100, "Yahoo(Lib)"
    except: pass
    
    return None, None, "Failed"

# --- REPORT GENERATOR ---
def generate_report():
    c = get_crypto_aggregated()
    tvl_val, tvl_pct, tvl_src = get_tvl_data()
    sp_val, sp_pct, sp_src = get_stock_data("^GSPC")
    ndq_val, ndq_pct, ndq_src = get_stock_data("^IXIC")

    output = "📊 **MARKET SNAPSHOT**\n\n"
    
    # --- CRYPTO ---
    output += "**Crypto Market Cap:**\n"
    if c:
        src = c['source']
        output += f"🌍 Total: {format_with_emoji(c['total_cap'], c['total_change'])} (Src: {src})\n"
        
        if c['total_vol'] and c['total_vol'] > 1_000_000:
            if c['total_vol'] > 1_000_000_000:
                output += f"📊 Vol: ${c['total_vol']/1_000_000_000:.2f}B (Src: {src})\n"
            else:
                output += f"📊 Vol: {c['total_vol']:,.0f} (Src: {src})\n"
        else:
             output += f"📊 Vol: N/A\n"
             
        # Alts Calc
        if c['btc_dom'] and c['eth_dom']:
            alts_val = c['total_cap'] * (1 - (c['btc_dom']/100) - (c['eth_dom']/100))
            output += f"🔵 Total ALTS: {format_with_emoji(alts_val, c['total_change'])} (Calc)\n"
    else:
        output += "🌍 Total: ⚠️ Error (All Methods Failed)\n"
        output += "📊 Vol: ⚠️ Error\n"
        output += "🔵 Total ALTS: ⚠️ Waiting for Data\n"

    # --- TVL ---
    if tvl_val:
        output += f"🔒 TVL: {format_with_emoji(tvl_val, tvl_pct)} (Src: {tvl_src})\n"
    else:
        output += f"🔒 TVL: ⚠️ {tvl_src}\n"

    output += "\n**Crypto Dominance:**\n"
    if c and c['btc_dom']:
        output += f"🟠 BTC: `{c['btc_dom']:.2f}%` (Src: {c['source']})\n"
        output += f"🟢 USDT: `{c['usdt_dom']:.2f}%` (Src: {c['source']})\n\n"
    else:
        output += "🟠 BTC: ⚠️ Error\n🟢 USDT: ⚠️ Error\n\n"

    # --- STOCKS ---
    output += "**Traditional Markets:**\n"
    if sp_val: output += f"{format_with_emoji(sp_val, sp_pct).split(' (')[0] + f' ({sp_pct:+.2f}%)'} S&P 500 (Src: {sp_src})\n"
    else: output += "⚠️ S&P 500: Failed\n"

    if ndq_val: output += f"{format_with_emoji(ndq_val, ndq_pct).split(' (')[0] + f' ({ndq_pct:+.2f}%)'} NASDAQ (Src: {ndq_src})"
    else: output += "⚠️ NASDAQ: Failed"

    return output

# --- HANDLERS ---
async def market_cmd(u: Update, c: ContextTypes.DEFAULT_TYPE):
    msg = await c.bot.send_message(chat_id=u.effective_chat.id, text="🔄 Fetching (Kitchen Sink Mode)...")
    await c.bot.edit_message_text(chat_id=u.effective_chat.id, message_id=msg.message_id, text=generate_report(), parse_mode=constants.ParseMode.MARKDOWN)

async def auto_post(c: ContextTypes.DEFAULT_TYPE):
    await c.bot.send_message(chat_id=c.job.chat_id, text=generate_report(), parse_mode=constants.ParseMode.MARKDOWN)

async def start_auto(u: Update, c: ContextTypes.DEFAULT_TYPE):
    cid = u.effective_message.chat_id
    for j in c.job_queue.get_jobs_by_name(str(cid)): j.schedule_removal()
    c.job_queue.run_repeating(auto_post, interval=14400, first=10, chat_id=cid, name=str(cid))
    await c.bot.send_message(chat_id=cid, text="✅ Auto-posting started!")

async def stop_auto(u: Update, c: ContextTypes.DEFAULT_TYPE):
    cid = u.effective_message.chat_id
    jobs = c.job_queue.get_jobs_by_name(str(cid))
    if jobs:
        for j in jobs: j.schedule_removal()
        await c.bot.send_message(chat_id=cid, text="🛑 Auto-posting stopped.")
    else:
        await c.bot.send_message(chat_id=cid, text="❌ No active jobs.")

if __name__ == '__main__':
    keep_alive()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler('market', market_cmd))
    app.add_handler(CommandHandler('start_auto', start_auto))
    app.add_handler(CommandHandler('stop_auto', stop_auto))
    print("Bot running...")
    app.run_polling()
