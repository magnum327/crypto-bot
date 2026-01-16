import logging
import requests
import random
import yfinance as yf
from telegram import Update, constants
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler
from keep_alive import keep_alive

# --- CONFIGURATION ---
BOT_TOKEN = '8266373667:AAE_Qrfq8VzMJTNE9Om9_rdbzscWFyBmgJU'
CMC_API_KEY = '9891d939-49c7-466c-b1c8-c762f7e6e600'.strip()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# --- HELPER FUNCTIONS ---
def get_random_header():
    # Browser-like headers to bypass blocks
    user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36'
    ]
    return {
        'User-Agent': random.choice(user_agents),
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Referer': 'https://google.com'
    }

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
#        DATA PROVIDERS (8 LAYERS)
# ==========================================

# 1. CoinCodex (Primary)
def fetch_coincodex():
    try:
        resp = requests.get("https://coincodex.com/api/coincodex/get_global_metrics", headers=get_random_header(), timeout=15)
        if resp.status_code != 200: return None, f"Err {resp.status_code}"
        d = resp.json()
        return {
            'name': 'CoinCodex',
            'total_cap': float(d['total_market_cap_usd']),
            'total_change': float(d.get('total_market_cap_24h_change', 0)),
            'total_vol': float(d.get('total_volume_usd', 0)),
            'vol_change': 0, 
            'btc_dom': float(d['btc_dominance']),
            'eth_dom': float(d['eth_dominance'])
        }, None
    except Exception as e: return None, "Conn Err"

# 2. DeFiLlama (Estimate via Prices)
def fetch_defillama_est():
    try:
        url = "https://coins.llama.fi/prices/current/coingecko:bitcoin,coingecko:ethereum,coingecko:tether"
        resp = requests.get(url, headers=get_random_header(), timeout=15)
        if resp.status_code != 200: return None, f"Err {resp.status_code}"
        
        c = resp.json().get('coins', {})
        btc = c.get('coingecko:bitcoin', {}).get('mcap', 0)
        eth = c.get('coingecko:ethereum', {}).get('mcap', 0)
        usdt = c.get('coingecko:tether', {}).get('mcap', 0)
        
        if btc == 0: return None, "Empty Data"
        
        # Estimate Total Cap based on assumed 57% dominance
        est_total = btc / 0.57
        
        return {
            'name': 'DeFiLlama(Est)',
            'total_cap': est_total,
            'total_change': 0,
            'total_vol': None, # DeFiLlama prices API doesn't give volume
            'vol_change': 0,
            'btc_dom': (btc / est_total) * 100,
            'eth_dom': (eth / est_total) * 100,
            'usdt_dom': (usdt / est_total) * 100
        }, None
    except Exception as e: return None, "Conn Err"

# 3. CoinStats
def fetch_coinstats():
    try:
        resp = requests.get("https://openapiv1.coinstats.app/global-markets", headers=get_random_header(), timeout=15)
        if resp.status_code != 200: return None, f"Err {resp.status_code}"
        d = resp.json()
        return {
            'name': 'CoinStats',
            'total_cap': float(d['marketCap']),
            'total_change': float(d.get('marketCapChange', 0)),
            'total_vol': float(d.get('volume', 0)),
            'vol_change': float(d.get('volumeChange', 0)),
            'btc_dom': float(d['btcDominance']),
            'eth_dom': 13.5 
        }, None
    except Exception as e: return None, "Conn Err"

# 4. CoinCap
def fetch_coincap():
    try:
        resp = requests.get("https://api.coincap.io/v2/assets?limit=100", timeout=15)
        if resp.status_code != 200: return None, f"Err {resp.status_code}"
        d = resp.json().get('data', [])
        if not d: return None, "Empty Data"
        
        total = 0; vol = 0; btc = 0; eth = 0; usdt = 0
        for c in d:
            m = float(c['marketCapUsd'])
            v = float(c['volumeUsd24Hr'])
            total += m
            vol += v
            if c['symbol'] == 'BTC': btc = m
            if c['symbol'] == 'ETH': eth = m
            if c['symbol'] == 'USDT': usdt = m
            
        return {
            'name': 'CoinCap',
            'total_cap': total,
            'total_change': 0,
            'total_vol': vol,
            'vol_change': 0,
            'btc_dom': (btc/total)*100,
            'eth_dom': (eth/total)*100,
            'usdt_dom': (usdt/total)*100
        }, None
    except Exception as e: return None, "Conn Err"

# 5. CoinMarketCap
def fetch_cmc():
    try:
        headers = {'Accept': 'application/json', 'X-CMC_PRO_API_KEY': CMC_API_KEY}
        resp = requests.get("https://pro-api.coinmarketcap.com/v1/global-metrics/quotes/latest", headers=headers, timeout=15)
        if resp.status_code != 200: return None, f"Err {resp.status_code}"
        d = resp.json().get('data', {})
        q = d['quote']['USD']
        return {
            'name': 'CoinMarketCap',
            'total_cap': q['total_market_cap'],
            'total_change': q['total_market_cap_yesterday_percentage_change'],
            'total_vol': q['total_volume_24h'],
            'vol_change': q['total_volume_24h_yesterday_percentage_change'],
            'btc_dom': d['btc_dominance'],
            'eth_dom': d['eth_dominance']
        }, None
    except Exception as e: return None, "Conn Err"

# 6. CryptoCompare
def fetch_cc():
    try:
        url = "https://min-api.cryptocompare.com/data/top/mktcapfull?limit=100&tsym=USD"
        resp = requests.get(url, timeout=15)
        if resp.status_code != 200: return None, f"Err {resp.status_code}"
        data = resp.json().get('Data', [])
        if not data: return None, "Empty"

        total_cap = 0; total_vol = 0; btc = 0; eth = 0; usdt = 0
        
        for coin_obj in data:
            if 'RAW' not in coin_obj: continue
            c = coin_obj['RAW']['USD']
            m = c.get('MKTCAP', 0)
            v = c.get('TOTALVOLUME24H', c.get('VOLUME24HOURTO', 0))
            
            total_cap += m
            total_vol += v
            
            sym = c.get('FROMSYMBOL')
            if sym == 'BTC': btc = m
            if sym == 'ETH': eth = m
            if sym == 'USDT': usdt = m
            
        return {
            'name': 'CryptoCompare',
            'total_cap': total_cap,
            'total_change': 0,
            'total_vol': total_vol,
            'vol_change': 0,
            'btc_dom': (btc/total_cap)*100,
            'eth_dom': (eth/total_cap)*100,
            'usdt_dom': (usdt/total_cap)*100
        }, None
    except Exception as e: return None, "Conn Err"

# 7. CoinGecko
def fetch_coingecko():
    try:
        resp = requests.get("https://api.coingecko.com/api/v3/global", headers=get_random_header(), timeout=15)
        if resp.status_code != 200: return None, f"Err {resp.status_code}"
        d = resp.json().get('data', {})
        return {
            'name': 'CoinGecko',
            'total_cap': d.get('total_market_cap', {}).get('usd', 0),
            'total_change': d.get('market_cap_change_percentage_24h_usd', 0),
            'total_vol': d.get('total_volume', {}).get('usd', 0),
            'vol_change': 0,
            'btc_dom': d.get('market_cap_percentage', {}).get('btc', 0),
            'eth_dom': d.get('market_cap_percentage', {}).get('eth', 0),
            'usdt_dom': d.get('market_cap_percentage', {}).get('usdt', 0)
        }, None
    except Exception as e: return None, "Conn Err"

# 8. Binance Estimate
def fetch_binance_est():
    try:
        r = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT", timeout=15)
        if r.status_code != 200: return None, "Err"
        price = float(r.json()['price'])
        btc_mcap = price * 19_800_000
        est_total = btc_mcap / 0.57
        return {
            'name': 'Binance(Est)',
            'total_cap': est_total,
            'total_change': 0,
            'total_vol': None,
            'vol_change': 0,
            'btc_dom': 57.0,
            'eth_dom': 13.0,
            'usdt_dom': 5.5
        }, None
    except Exception as e: return None, "Conn Err"


# ==========================================
#        AGGREGATOR LOGIC
# ==========================================

def get_aggregated_crypto_data():
    state = {
        'total_cap': None, 'total_change': None, 'total_src': None, 'total_err': None,
        'total_vol': None, 'vol_change': None, 'vol_src': None,
        'btc_dom': None, 'btc_src': None,
        'usdt_dom': None, 'usdt_src': None,
        'eth_dom': None
    }
    
    # PRIORITY ORDER 1-8
    providers = [
        fetch_coincodex, 
        fetch_defillama_est, 
        fetch_coinstats, 
        fetch_coincap, 
        fetch_cmc, 
        fetch_cc, 
        fetch_coingecko, 
        fetch_binance_est
    ]
    
    for provider in providers:
        # Optimization: Stop if we have everything
        if state['total_cap'] and state['total_vol'] and state['btc_dom'] and state['usdt_dom']:
            break
            
        data, error = provider()
        
        if not data:
            if not state['total_cap']: state['total_err'] = error
            continue
            
        # 1. Total Cap
        if not state['total_cap'] and 'total_cap' in data:
            state['total_cap'] = data['total_cap']
            state['total_change'] = data.get('total_change', 0)
            state['total_src'] = data['name']
            
        # 2. Volume
        if not state['total_vol'] and 'total_vol' in data and data['total_vol']:
            state['total_vol'] = data['total_vol']
            state['vol_change'] = data.get('vol_change', 0)
            state['vol_src'] = data['name']
            
        # 3. BTC Dominance
        if not state['btc_dom'] and 'btc_dom' in data:
            state['btc_dom'] = data['btc_dom']
            state['btc_src'] = data['name']
            
        # 4. USDT Dominance
        if not state['usdt_dom']:
            if 'usdt_dom' in data and data['usdt_dom']:
                state['usdt_dom'] = data['usdt_dom']
                state['usdt_src'] = data['name']
            elif state['total_cap']: 
                state['usdt_dom'] = 5.5
                state['usdt_src'] = "Est"

        # 5. ETH Dominance (Hidden)
        if not state['eth_dom'] and 'eth_dom' in data:
             state['eth_dom'] = data['eth_dom']

    return state

def get_tvl_data():
    try:
        r = requests.get("https://api.llama.fi/v2/historicalChainTvl", headers=get_random_header(), timeout=15)
        if r.status_code != 200: return None, None, f"Err {r.status_code}"
        d = r.json()
        curr = d[-1]['tvl']
        prev = d[-2]['tvl']
        change = ((curr - prev)/prev)*100
        return curr, change, "DeFiLlama"
    except Exception as e:
        return None, None, "Conn Err"

def get_stock_data(ticker):
    # FALLBACK: Try Direct Yahoo API if yfinance fails
    try:
        # Method 1: yfinance library
        t = yf.Ticker(ticker)
        h = t.history(period="2d")
        if len(h) >= 2:
            curr = h['Close'].iloc[-1]
            prev = h['Close'].iloc[-2]
            change = ((curr - prev)/prev)*100
            return curr, change, "Yahoo"
    except: pass
    
    try:
        # Method 2: Direct Request (Bypasses some blocks)
        h = {'User-Agent': 'Mozilla/5.0'}
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=2d"
        r = requests.get(url, headers=h, timeout=5)
        d = r.json()['chart']['result'][0]
        close = d['indicators']['quote'][0]['close']
        
        # Filter Nones
        valid_close = [x for x in close if x is not None]
        if len(valid_close) < 2: return None, None, "NoData"
        
        curr = valid_close[-1]
        prev = valid_close[-2]
        change = ((curr - prev)/prev)*100
        return curr, change, "Yahoo(API)"
    except:
        return None, None, "Failed"

def generate_report():
    c = get_aggregated_crypto_data()
    tvl_val, tvl_pct, tvl_src = get_tvl_data()
    sp_val, sp_pct, sp_src = get_stock_data("^GSPC")
    ndq_val, ndq_pct, ndq_src = get_stock_data("^IXIC")

    # --- FORMATTING ---
    output = "📊 **MARKET SNAPSHOT**\n\n"
    output += "**Crypto Market Cap:**\n"
    
    # Total Cap
    if c['total_cap']:
        output += f"🌍 Total: {format_with_emoji(c['total_cap'], c['total_change'])} (Src: {c['total_src']})\n"
    else:
        output += f"🌍 Total: ⚠️ Error ({c['total_err']})\n"
    
    # Volume
    if c['total_vol']:
        output += f"📊 Vol: {format_with_emoji(c['total_vol'], c['vol_change'])} (Src: {c['vol_src']})\n"
    else:
        output += f"📊 Vol: ⚠️ Error\n"
        
    # Total Alts
    if c['total_cap'] and c['btc_dom']:
        eth_d = c['eth_dom'] if c['eth_dom'] else 13.0
        alts_val = c['total_cap'] * (1 - (c['btc_dom']/100) - (eth_d/100))
        output += f"🔵 Total ALTS: {format_with_emoji(alts_val, c['total_change'])} (Calc)\n"
    else:
        output += f"🔵 Total ALTS: ⚠️ Waiting for Total/BTC data\n"

    # TVL
    if tvl_val:
        output += f"🔒 TVL: {format_with_emoji(tvl_val, tvl_pct)} (Src: {tvl_src})\n"
    else:
        output += f"🔒 TVL: ⚠️ Error ({tvl_src})\n"

    output += "\n**Crypto Dominance:**\n"
    
    # BTC
    if c['btc_dom']:
        output += f"🟠 BTC: `{c['btc_dom']:.2f}%` (Src: {c['btc_src']})\n"
    else:
        output += f"🟠 BTC: ⚠️ Error\n"
        
    # USDT
    if c['usdt_dom']:
        output += f"🟢 USDT: `{c['usdt_dom']:.2f}%` (Src: {c['usdt_src']})\n\n"
    else:
        output += f"🟢 USDT: ⚠️ Error\n\n"

    # Traditional
    output += "**Traditional Markets:**\n"
    if sp_val: output += f"{format_with_emoji(sp_val, sp_pct).split(' (')[0] + f' ({sp_pct:+.2f}%)'} S&P 500 (Src: {sp_src})\n"
    else: output += "⚠️ S&P 500: Failed to Fetch\n"

    if ndq_val: output += f"{format_with_emoji(ndq_val, ndq_pct).split(' (')[0] + f' ({ndq_pct:+.2f}%)'} NASDAQ (Src: {ndq_src})"
    else: output += "⚠️ NASDAQ: Failed to Fetch"

    return output

# --- HANDLERS ---
async def market_cmd(u: Update, c: ContextTypes.DEFAULT_TYPE):
    msg = await c.bot.send_message(chat_id=u.effective_chat.id, text="🔄 Fetching...")
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
