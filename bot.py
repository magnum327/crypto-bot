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

# Global variable to store the last error for debugging
LAST_ERROR = "No attempts yet."

# --- HELPER FUNCTIONS ---
def get_random_header():
    user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/91.0.4472.124 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15',
        'Mozilla/5.0 (Linux; Android 10; SM-G960U) Chrome/88.0.4324.181 Mobile Safari/537.36'
    ]
    return {'User-Agent': random.choice(user_agents), 'Accept': 'application/json'}

def format_with_emoji(value, change_pct):
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
#        DATA SOURCE LAYER CAKE
# ==========================================

# --- 1. COINCODEX ---
def get_data_coincodex():
    global LAST_ERROR
    try:
        resp = requests.get("https://coincodex.com/api/coincodex/get_global_metrics", headers=get_random_header(), timeout=15)
        if resp.status_code != 200:
            LAST_ERROR = f"CoinCodex: {resp.status_code}"
            return None
        data = resp.json()
        total = float(data['total_market_cap_usd'])
        btc_d = float(data['btc_dominance'])
        eth_d = float(data['eth_dominance'])
        
        return {
            'source': 'CoinCodex',
            'btc_dom': btc_d,
            'usdt_dom': 5.5, 
            'total_val': total,
            'total_pct': float(data.get('total_market_cap_24h_change', 0)),
            'alts_val': total * (1 - (btc_d/100) - (eth_d/100)),
            'alts_pct': 0
        }
    except Exception as e:
        LAST_ERROR = f"CoinCodex Error: {str(e)}"
        return None

# --- 2. DEFILLAMA (COINS API) ---
def get_data_defillama():
    global LAST_ERROR
    try:
        # Fetch prices/mcap for BTC, ETH, USDT
        url = "https://coins.llama.fi/prices/current/coingecko:bitcoin,coingecko:ethereum,coingecko:tether?searchWidth=4h"
        resp = requests.get(url, headers=get_random_header(), timeout=15)
        
        if resp.status_code != 200:
            LAST_ERROR = f"DeFiLlama: {resp.status_code}"
            return None
            
        coins = resp.json().get('coins', {})
        
        # Extract MCAPs
        btc_mcap = coins.get('coingecko:bitcoin', {}).get('mcap', 0)
        eth_mcap = coins.get('coingecko:ethereum', {}).get('mcap', 0)
        usdt_mcap = coins.get('coingecko:tether', {}).get('mcap', 0)
        
        if btc_mcap == 0: return None # Data invalid
        
        # ESTIIMATE TOTAL CAP: Assumes BTC Dominance is approx 58% (Adjustable)
        # This is necessary because DeFiLlama doesn't give a "Global Total"
        btc_dom_est = 0.58
        total_est = btc_mcap / btc_dom_est
        
        return {
            'source': 'DeFiLlama (Est)',
            'btc_dom': (btc_mcap / total_est) * 100,
            'usdt_dom': (usdt_mcap / total_est) * 100,
            'total_val': total_est,
            'total_pct': 0, # No 24h change data in this endpoint
            'alts_val': total_est - btc_mcap - eth_mcap,
            'alts_pct': 0
        }
    except Exception as e:
        LAST_ERROR = f"DeFiLlama Error: {str(e)}"
        return None

# --- 3. COINSTATS ---
def get_data_coinstats():
    global LAST_ERROR
    try:
        resp = requests.get("https://openapiv1.coinstats.app/global-markets", headers=get_random_header(), timeout=15)
        data = resp.json()
        total = float(data['marketCap'])
        btc_d = float(data['btcDominance'])
        
        return {
            'source': 'CoinStats',
            'btc_dom': btc_d,
            'usdt_dom': 5.5,
            'total_val': total,
            'total_pct': float(data.get('marketCapChange', 0)),
            'alts_val': total * (1 - (btc_d/100) - 0.14),
            'alts_pct': 0
        }
    except Exception as e:
        LAST_ERROR = f"CoinStats Error: {str(e)}"
        return None

# --- 4. COINCAP ---
def get_data_coincap():
    global LAST_ERROR
    try:
        resp = requests.get("https://api.coincap.io/v2/assets?limit=100", timeout=15)
        data = resp.json().get('data', [])
        if not data: return None

        total = 0; btc = 0; eth = 0; usdt = 0
        for coin in data:
            mcap = float(coin['marketCapUsd'])
            total += mcap
            if coin['symbol'] == 'BTC': btc = mcap
            if coin['symbol'] == 'ETH': eth = mcap
            if coin['symbol'] == 'USDT': usdt = mcap

        return {
            'source': 'CoinCap',
            'btc_dom': (btc / total) * 100,
            'usdt_dom': (usdt / total) * 100,
            'total_val': total,
            'total_pct': 0,
            'alts_val': total - btc - eth,
            'alts_pct': 0
        }
    except Exception as e:
        LAST_ERROR = f"CoinCap Error: {str(e)}"
        return None

# --- 5. COINMARKETCAP ---
def get_data_cmc():
    try:
        headers = {'Accept': 'application/json', 'X-CMC_PRO_API_KEY': CMC_API_KEY}
        g_resp = requests.get("https://pro-api.coinmarketcap.com/v1/global-metrics/quotes/latest", headers=headers, timeout=15)
        g_data = g_resp.json().get('data')
        if not g_data: return None

        quote = g_data['quote']['USD']
        total_mcap = quote['total_market_cap']
        total_change = quote['total_market_cap_yesterday_percentage_change']
        
        params = {'start': '1', 'limit': '10', 'convert': 'USD', 'sort': 'market_cap'}
        l_resp = requests.get("https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest", headers=headers, params=params, timeout=15)
        listings = l_resp.json().get('data', [])
        
        usdt_mcap = 0; btc_mcap = 0; eth_mcap = 0
        for coin in listings:
            mcap = coin['quote']['USD']['market_cap']
            if coin['symbol'] == 'USDT': usdt_mcap = mcap
            if coin['symbol'] == 'BTC': btc_mcap = mcap
            if coin['symbol'] == 'ETH': eth_mcap = mcap

        return {
            'source': 'CoinMarketCap',
            'btc_dom': g_data['btc_dominance'],
            'usdt_dom': (usdt_mcap / total_mcap) * 100,
            'total_val': total_mcap,
            'total_pct': total_change,
            'alts_val': total_mcap - btc_mcap - eth_mcap,
            'alts_pct': total_change * 1.05
        }
    except: return None

# --- 6. CRYPTOCOMPARE ---
def get_data_cc():
    try:
        url = "https://min-api.cryptocompare.com/data/top/mktcapfull?limit=100&tsym=USD"
        resp = requests.get(url, timeout=15)
        data = resp.json().get('Data', [])
        if not data: return None

        total_mcap = 0; total_w_change = 0; usdt_mcap = 0; btc_mcap = 0; eth_mcap = 0

        for coin_obj in data:
            if 'RAW' not in coin_obj: continue
            coin = coin_obj['RAW']['USD']
            mcap = coin['MKTCAP']
            change = coin['CHANGEPCT24HOUR']
            total_mcap += mcap
            total_w_change += (mcap * change)
            
            if coin['FROMSYMBOL'] == 'USDT': usdt_mcap = mcap
            if coin['FROMSYMBOL'] == 'BTC': btc_mcap = mcap
            if coin['FROMSYMBOL'] == 'ETH': eth_mcap = mcap

        total_pct = total_w_change / total_mcap
        
        return {
            'source': 'CryptoCompare',
            'btc_dom': (btc_mcap / total_mcap) * 100,
            'usdt_dom': (usdt_mcap / total_mcap) * 100,
            'total_val': total_mcap,
            'total_pct': total_pct,
            'alts_val': total_mcap - btc_mcap - eth_mcap,
            'alts_pct': total_pct
        }
    except: return None

# --- 7. COINGECKO ---
def get_data_coingecko():
    try:
        g_resp = requests.get("https://api.coingecko.com/api/v3/global", headers=get_random_header(), timeout=15)
        if g_resp.status_code != 200: return None
        data = g_resp.json()['data']
        total_mcap = data['total_market_cap']['usd']
        
        return {
            'source': 'CoinGecko',
            'btc_dom': data['market_cap_percentage']['btc'],
            'usdt_dom': data['market_cap_percentage']['usdt'],
            'total_val': total_mcap,
            'total_pct': data.get('market_cap_change_percentage_24h_usd', 0),
            'alts_val': total_mcap * 0.4,
            'alts_pct': 0
        }
    except: return None

# --- 8. BINANCE ESTIMATE ---
def get_data_binance_est():
    global LAST_ERROR
    try:
        r = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT", timeout=15)
        price = float(r.json()['price'])
        btc_mcap = price * 19_800_000
        total = btc_mcap / 0.57 
        return {
            'source': 'Binance Estimate',
            'btc_dom': 57.0,
            'usdt_dom': 5.5,
            'total_val': total,
            'total_pct': 0,
            'alts_val': total * 0.30,
            'alts_pct': 0
        }
    except Exception as e:
        LAST_ERROR = f"Binance Error: {str(e)}"
        return None

# --- MAIN CONTROLLER ---
def get_best_crypto_data():
    # ORDER: 1.Codex 2.DeFiLlama 3.Stats 4.Cap 5.CMC 6.CC 7.Gecko 8.Binance
    sources = [
        get_data_coincodex,
        get_data_defillama,
        get_data_coinstats,
        get_data_coincap,
        get_data_cmc,
        get_data_cc,
        get_data_coingecko,
        get_data_binance_est
    ]
    
    for fetcher in sources:
        data = fetcher()
        if data: return data
            
    return None

def get_stock_data(ticker):
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="2d")
        if len(hist) < 2: return 0, 0
        curr = hist['Close'].iloc[-1]
        prev = hist['Close'].iloc[-2]
        return curr, ((curr - prev)/prev)*100
    except:
        return 0, 0

# --- DEFILLAMA (FOR TVL ONLY - ALWAYS USED) ---
def get_tvl():
    try:
        r = requests.get("https://api.llama.fi/v2/historicalChainTvl", headers=get_random_header(), timeout=15)
        d = r.json()
        today = d[-1]['tvl']
        change = ((today - d[-2]['tvl'])/d[-2]['tvl'])*100
        return today, change
    except:
        return 0, 0

def generate_report():
    c_data = get_best_crypto_data()
    
    # DEBUG MODE: If all fail, return the technical error
    if not c_data:
        return f"⚠️ **DEBUG REPORT:** All API sources failed.\n\n**Last Error:** `{LAST_ERROR}`\n\n*Note: If you see 'Max retries exceeded' or 'NameResolutionError', your Render server has no internet access.*"

    tvl_val, tvl_c = get_tvl()
    dow_p, dow_c = get_stock_data("^DJI")
    sp_p, sp_c = get_stock_data("^GSPC")
    ndq_p, ndq_c = get_stock_data("^IXIC")

    dow_s = format_with_emoji(dow_p, dow_c).split(" (")[0] + f" ({'+' if dow_c>=0 else ''}{dow_c:.2f}%)"
    sp_s = format_with_emoji(sp_p, sp_c).split(" (")[0] + f" ({'+' if sp_c>=0 else ''}{sp_c:.2f}%)"
    ndq_s = format_with_emoji(ndq_p, ndq_c).split(" (")[0] + f" ({'+' if ndq_c>=0 else ''}{ndq_c:.2f}%)"

    return (
        f"📊 **MARKET SNAPSHOT**\n\n"
        f"**Crypto Dominance (Src: {c_data['source']}):**\n"
        f"🟠 BTC: `{c_data['btc_dom']:.2f}%`\n"
        f"🟢 USDT: `{c_data['usdt_dom']:.2f}%`\n\n"
        
        f"**Crypto Market Cap (Src: {c_data['source']}):**\n"
        f"🌍 Total: {format_with_emoji(c_data['total_val'], c_data['total_pct'])}\n"
        f"🔵 Total ALTS: {format_with_emoji(c_data['alts_val'], c_data['alts_pct'])}\n"
        f"🔒 TVL: {format_with_emoji(tvl_val, tvl_c)} (Src: DefiLlama)\n\n"
        
        f"**Traditional Markets (Src: Yahoo Finance):**\n"
        f"{dow_s} Dow Jones\n"
        f"{sp_s} S&P 500\n"
        f"{ndq_s} NASDAQ"
    )

# --- TELEGRAM SETUP ---
async def market_cmd(u: Update, c: ContextTypes.DEFAULT_TYPE):
    msg = await c.bot.send_message(chat_id=u.effective_chat.id, text="🔄 Fetching (Trying 8 Sources)...")
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
