import logging
import requests
import random
import yfinance as yf
from telegram import Update, constants
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler
from keep_alive import keep_alive

# --- CONFIGURATION ---
BOT_TOKEN = '8266373667:AAE_Qrfq8VzMJTNE9Om9_rdbzscWFyBmgJU'

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# --- HELPER FUNCTIONS ---
def get_random_header():
    """Returns a random browser header to avoid blocking."""
    user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0.3 Safari/605.1.15',
        'Mozilla/5.0 (Linux; Android 10; SM-G960U) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/88.0.4324.181 Mobile Safari/537.36',
        'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:88.0) Gecko/20100101 Firefox/88.0'
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

# --- DATA FETCHING ---
def get_stock_data(ticker_symbol):
    try:
        ticker = yf.Ticker(ticker_symbol)
        history = ticker.history(period="2d")
        if len(history) < 2: return 0.0, 0.0
        curr = history['Close'].iloc[-1]
        prev = history['Close'].iloc[-2]
        change = ((curr - prev) / prev) * 100
        return curr, change
    except Exception as e:
        logging.error(f"Error stock {ticker_symbol}: {e}")
        return 0.0, 0.0

def get_crypto_data():
    """Fetches data from CoinGecko using Rotating Headers."""
    try:
        # 1. Get Global Data (Total Cap, BTC Dom)
        global_url = "https://api.coingecko.com/api/v3/global"
        g_resp = requests.get(global_url, headers=get_random_header(), timeout=10)
        
        if g_resp.status_code == 429:
            return None, "CoinGecko Rate Limit (429). Server is busy."
        if g_resp.status_code != 200:
            return None, f"CoinGecko Error: {g_resp.status_code}"
            
        g_data = g_resp.json().get('data', {})
        total_mcap = g_data.get('total_market_cap', {}).get('usd', 0)
        btc_dom = g_data.get('market_cap_percentage', {}).get('btc', 0)
        
        # Calculate Total Change % (Using yesterday's total cap provided by API is unreliable, 
        # so we rely on the market_cap_change_percentage_24h_usd field if available)
        total_change_pct = g_data.get('market_cap_change_percentage_24h_usd', 0)
        total_mcap_old = total_mcap / (1 + (total_change_pct / 100))

        # 2. Get Top 10 Coins (To find USDT Dom, Alts, Others)
        markets_url = "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=10&page=1&sparkline=false"
        m_resp = requests.get(markets_url, headers=get_random_header(), timeout=10)
        
        if m_resp.status_code != 200:
            return None, f"CoinGecko Markets Error: {m_resp.status_code}"
            
        top_10 = m_resp.json()

        # Variables
        usdt_mcap = 0
        sum_top10 = 0
        sum_top10_old = 0
        btc_mcap = 0; btc_old = 0
        eth_mcap = 0; eth_old = 0

        for coin in top_10:
            mcap = coin['market_cap']
            pct_change = coin['price_change_percentage_24h']
            symbol = coin['symbol'].upper()
            
            # Approximate old mcap
            if pct_change is None: pct_change = 0
            mcap_old = mcap / (1 + (pct_change / 100))
            
            sum_top10 += mcap
            sum_top10_old += mcap_old
            
            if symbol == 'USDT': usdt_mcap = mcap
            if symbol == 'BTC': btc_mcap = mcap; btc_old = mcap_old
            if symbol == 'ETH': eth_mcap = mcap; eth_old = mcap_old

        # Calculations
        usdt_dom = (usdt_mcap / total_mcap) * 100 if total_mcap > 0 else 0
        
        # Total ALTS (Total - BTC - ETH)
        alts_now = total_mcap - btc_mcap - eth_mcap
        alts_old = total_mcap_old - btc_old - eth_old
        alts_change_pct = calculate_change(alts_now, alts_old)
        
        # Others (Total - Top 10)
        others_now = total_mcap - sum_top10
        others_old = total_mcap_old - sum_top10_old
        others_change_pct = calculate_change(others_now, others_old)

        return {
            'btc_dom': btc_dom,
            'usdt_dom': usdt_dom,
            'total_val': total_mcap,
            'total_pct': total_change_pct,
            'alts_val': alts_now,
            'alts_pct': alts_change_pct,
            'others_val': others_now,
            'others_pct': others_change_pct
        }, None

    except Exception as e:
        return None, f"Code Exception: {str(e)}"

def get_defi_tvl():
    try:
        url = "https://api.llama.fi/v2/historicalChainTvl"
        resp = requests.get(url, headers=get_random_header(), timeout=10)
        data = resp.json()
        if len(data) < 2: return 0, 0
        today = data[-1]['tvl']
        yesterday = data[-2]['tvl']
        change = calculate_change(today, yesterday)
        return today, change
    except Exception as e:
        logging.error(f"Error TVL: {e}")
        return 0, 0

def generate_report_text():
    c_data, error_msg = get_crypto_data()
    
    if error_msg:
        return f"⚠️ **Data Error:**\n`{error_msg}`\n\n*Try again in a few minutes (CoinGecko limits requests).*"

    tvl_val, tvl_change = get_defi_tvl()
    dow_p, dow_c = get_stock_data("^DJI")
    sp_p, sp_c = get_stock_data("^GSPC")
    ndq_p, ndq_c = get_stock_data("^IXIC")

    dow_str = format_with_emoji(dow_p, dow_c).split(" (")[0] + f" ({'+' if dow_c>=0 else ''}{dow_c:.2f}%)"
    sp_str = format_with_emoji(sp_p, sp_c).split(" (")[0] + f" ({'+' if sp_c>=0 else ''}{sp_c:.2f}%)"
    ndq_str = format_with_emoji(ndq_p, ndq_c).split(" (")[0] + f" ({'+' if ndq_c>=0 else ''}{ndq_c:.2f}%)"

    return (
        f"📊 **MARKET SNAPSHOT**\n\n"
        f"**Crypto Dominance:**\n"
        f"🟠 BTC: `{c_data['btc_dom']:.2f}%`\n"
        f"🟢 USDT: `{c_data['usdt_dom']:.2f}%`\n\n"
        
        f"**Crypto Market Cap:**\n"
        f"🌍 Total: {format_with_emoji(c_data['total_val'], c_data['total_pct'])}\n"
        f"🔵 Total ALTS: {format_with_emoji(c_data['alts_val'], c_data['alts_pct'])}\n"
        f"🟣 ALT Excluding Top 10: {format_with_emoji(c_data['others_val'], c_data['others_pct'])}\n"
        f"🔒 TVL: {format_with_emoji(tvl_val, tvl_change)}\n\n"
        
        f"**Traditional Markets:**\n"
        f"{dow_str} Dow Jones\n"
        f"{sp_str} S&P 500\n"
        f"{ndq_str} NASDAQ"
    )

# --- HANDLERS ---
async def market_cmd(u: Update, c: ContextTypes.DEFAULT_TYPE):
    msg = await c.bot.send_message(chat_id=u.effective_chat.id, text="🔄 Fetching from CoinGecko...")
    await c.bot.edit_message_text(chat_id=u.effective_chat.id, message_id=msg.message_id, text=generate_report_text(), parse_mode=constants.ParseMode.MARKDOWN)

async def auto_post(c: ContextTypes.DEFAULT_TYPE):
    await c.bot.send_message(chat_id=c.job.chat_id, text=generate_report_text(), parse_mode=constants.ParseMode.MARKDOWN)

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
