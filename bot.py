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
    user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/91.0.4472.124 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15',
        'Mozilla/5.0 (Linux; Android 10; SM-G960U) Chrome/88.0.4324.181 Mobile Safari/537.36'
    ]
    return {'User-Agent': random.choice(user_agents), 'Accept': 'application/json'}

def calculate_change(current, previous):
    if previous == 0: return 0.0
    return ((current - previous) / previous) * 100

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
#        DATA SOURCE LAYER CAKE (8 LAYERS)
# ==========================================

# --- 1. COINMARKETCAP ---
def get_data_cmc():
    try:
        headers = {'Accept': 'application/json', 'X-CMC_PRO_API_KEY': CMC_API_KEY}
        g_resp = requests.get("https://pro-api.coinmarketcap.com/v1/global-metrics/quotes/latest", headers=headers, timeout=5)
        g_data = g_resp.json().get('data')
        if not g_data: return None

        quote = g_data['quote']['USD']
        total_mcap = quote['total_market_cap']
        total_change = quote['total_market_cap_yesterday_percentage_change']
        btc_dom = g_data['btc_dominance']
        
        # Listings for Alts
        params = {'start': '1', 'limit': '10', 'convert': 'USD', 'sort': 'market_cap'}
        l_resp = requests.get("https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest", headers=headers, params=params, timeout=5)
        listings = l_resp.json().get('data', [])
        
        usdt_mcap = 0; btc_mcap = 0; eth_mcap = 0; sum_top10 = 0
        for coin in listings:
            mcap = coin['quote']['USD']['market_cap']
            sum_top10 += mcap
            if coin['symbol'] == 'USDT': usdt_mcap = mcap
            if coin['symbol'] == 'BTC': btc_mcap = mcap
            if coin['symbol'] == 'ETH': eth_mcap = mcap

        alts_now = total_mcap - btc_mcap - eth_mcap
        others_now = total_mcap - sum_top10

        return {
            'source': 'CoinMarketCap',
            'btc_dom': btc_dom,
            'usdt_dom': (usdt_mcap / total_mcap) * 100,
            'total_val': total_mcap,
            'total_pct': total_change,
            'alts_val': alts_now,
            'alts_pct': total_change * 1.05,
            'others_val': others_now,
            'others_pct': total_change
        }
    except: return None

# --- 2. COINPAPRIKA ---
def get_data_paprika():
    try:
        g_resp = requests.get("https://api.coinpaprika.com/v1/global", headers=get_random_header(), timeout=5)
        g_data = g_resp.json()
        
        total_mcap = int(g_data['market_cap_usd'])
        total_change = float(g_data['market_cap_change_24h'])
        btc_dom = float(g_data['bitcoin_dominance_percentage'])
        
        t_resp = requests.get("https://api.coinpaprika.com/v1/tickers?limit=10&quotes=USD", headers=get_random_header(), timeout=5)
        tickers = t_resp.json()
        
        btc_mcap = 0; eth_mcap = 0; usdt_mcap = 0; sum_top10 = 0
        for coin in tickers:
            mcap = coin['quotes']['USD']['market_cap']
            sum_top10 += mcap
            if coin['symbol'] == 'BTC': btc_mcap = mcap
            if coin['symbol'] == 'ETH': eth_mcap = mcap
            if coin['symbol'] == 'USDT': usdt_mcap = mcap
            
        return {
            'source': 'CoinPaprika',
            'btc_dom': btc_dom,
            'usdt_dom': (usdt_mcap / total_mcap) * 100,
            'total_val': total_mcap,
            'total_pct': total_change,
            'alts_val': total_mcap - btc_mcap - eth_mcap,
            'alts_pct': total_change,
            'others_val': total_mcap - sum_top10,
            'others_pct': total_change
        }
    except: return None

# --- 3. CRYPTOCOMPARE ---
def get_data_cc():
    try:
        url = "https://min-api.cryptocompare.com/data/top/mktcapfull?limit=100&tsym=USD"
        resp = requests.get(url, timeout=10)
        data = resp.json().get('Data', [])
        if not data: return None

        total_mcap = 0; total_w_change = 0; sum_top10 = 0; usdt_mcap = 0; btc_mcap = 0; eth_mcap = 0

        for index, coin_obj in enumerate(data):
            if 'RAW' not in coin_obj: continue
            coin = coin_obj['RAW']['USD']
            mcap = coin['MKTCAP']
            change = coin['CHANGEPCT24HOUR']
            total_mcap += mcap
            total_w_change += (mcap * change)
            if index < 10: sum_top10 += mcap
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
            'alts_pct': total_pct,
            'others_val': total_mcap - sum_top10,
            'others_pct': total_pct
        }
    except: return None

# --- 4. COINGECKO ---
def get_data_coingecko():
    try:
        g_resp = requests.get("https://api.coingecko.com/api/v3/global", headers=get_random_header(), timeout=5)
        if g_resp.status_code != 200: return None
        data = g_resp.json()['data']
        total_mcap = data['total_market_cap']['usd']
        
        return {
            'source': 'CoinGecko',
            'btc_dom': data['market_cap_percentage']['btc'],
            'usdt_dom': data['market_cap_percentage']['usdt'],
            'total_val': total_mcap,
            'total_pct': data.get('market_cap_change_percentage_24h_usd', 0),
            'alts_val': total_mcap * 0.4, # Approx
            'alts_pct': 0,
            'others_val': total_mcap * 0.15,
            'others_pct': 0
        }
    except: return None

# --- 5. COINCAP ---
def get_data_coincap():
    try:
        resp = requests.get("https://api.coincap.io/v2/assets?limit=100", timeout=5)
        data = resp.json().get('data', [])
        if not data: return None

        total = 0; btc = 0; eth = 0; usdt = 0; sum_10 = 0
        for i, coin in enumerate(data):
            mcap = float(coin['marketCapUsd'])
            total += mcap
            if i < 10: sum_10 += mcap
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
            'alts_pct': 0,
            'others_val': total - sum_10,
            'others_pct': 0
        }
    except: return None

# --- 6. COINCODEX (NEW) ---
def get_data_coincodex():
    try:
        resp = requests.get("https://coincodex.com/api/coincodex/get_global_metrics", headers=get_random_header(), timeout=5)
        data = resp.json()
        total = float(data['total_market_cap_usd'])
        btc_d = float(data['btc_dominance'])
        eth_d = float(data['eth_dominance'])
        
        return {
            'source': 'CoinCodex',
            'btc_dom': btc_d,
            'usdt_dom': 5.5, # Approximate
            'total_val': total,
            'total_pct': float(data.get('total_market_cap_24h_change', 0)),
            'alts_val': total * (1 - (btc_d/100) - (eth_d/100)),
            'alts_pct': 0,
            'others_val': total * 0.15,
            'others_pct': 0
        }
    except: return None

# --- 7. COINSTATS (NEW) ---
def get_data_coinstats():
    try:
        # Public API
        resp = requests.get("https://openapiv1.coinstats.app/global-markets", headers=get_random_header(), timeout=5)
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
            'alts_pct': 0,
            'others_val': total * 0.15,
            'others_pct': 0
        }
    except: return None

# --- 8. BINANCE ESTIMATE (LAST RESORT) ---
def get_data_binance_est():
    try:
        # Get BTC Price
        r = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT", timeout=5)
        price = float(r.json()['price'])
        
        # Est Supply: 19.8M, Est Dom: 57%
        btc_mcap = price * 19_800_000
        total = btc_mcap / 0.57 
        
        return {
            'source': 'Binance Estimate',
            'btc_dom': 57.0,
            'usdt_dom': 5.5,
            'total_val': total,
            'total_pct': 0,
            'alts_val': total * 0.30,
            'alts_pct': 0,
            'others_val': total * 0.15,
            'others_pct': 0
        }
    except: return None

# --- MAIN CONTROLLER ---
def get_best_crypto_data():
    # Order of Priority:
    sources = [
        get_data_cmc,
        get_data_paprika,
        get_data_cc,
        get_data_coingecko,
        get_data_coincap,
        get_data_coincodex,
        get_data_coinstats,
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

def get_tvl():
    try:
        r = requests.get("https://api.llama.fi/v2/historicalChainTvl", timeout=5)
        d = r.json()
        today = d[-1]['tvl']
        change = ((today - d[-2]['tvl'])/d[-2]['tvl'])*100
        return today, change
    except:
        return 0, 0

def generate_report():
    c_data = get_best_crypto_data()
    if not c_data:
        return "⚠️ **CRITICAL:** All 8 API sources failed. Internet connection likely down."

    tvl_val, tvl_c = get_tvl()
    dow_p, dow_c = get_stock_data("^DJI")
    sp_p, sp_c = get_stock_data("^GSPC")
    ndq_p, ndq_c = get_stock_data("^IXIC")

    # Format Strings
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
        f"🟣 ALT Excluding Top 10: {format_with_emoji(c_data['others_val'], c_data['others_pct'])}\n"
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
