import logging
import requests
import yfinance as yf
from telegram import Update, constants
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler
from keep_alive import keep_alive

# --- CONFIGURATION ---
BOT_TOKEN = '8266373667:AAE_Qrfq8VzMJTNE9Om9_rdbzscWFyBmgJU'
CMC_API_KEY = '9891d939-49c7-466c-b1c8-c762f7e6e600'

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# --- HELPER FUNCTIONS ---
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
    """Fetches accurate data from CoinMarketCap with DEBUGGING."""
    try:
        headers = {
            'Accept': 'application/json',  # Fixed header name
            'X-CMC_PRO_API_KEY': CMC_API_KEY,
            'User-Agent': 'Mozilla/5.0'
        }

        # 1. Global Metrics
        global_url = "https://pro-api.coinmarketcap.com/v1/global-metrics/quotes/latest"
        g_resp = requests.get(global_url, headers=headers)
        g_json = g_resp.json()

        # --- DEBUG CHECK 1 ---
        # If the API key is wrong, CMC returns a 'status' object with an error_message
        if 'status' in g_json and g_json['status']['error_code'] != 0:
            error_msg = g_json['status']['error_message']
            return None, f"CMC API Error: {error_msg}"

        if 'data' not in g_json:
             return None, f"CMC Unknown Error: {g_resp.text}"

        g_data = g_json['data']
        quote = g_data.get('quote', {}).get('USD', {})
        total_mcap = quote.get('total_market_cap', 0)
        total_change_pct = quote.get('total_market_cap_yesterday_percentage_change', 0)
        btc_dom = g_data.get('btc_dominance', 0)

        # 2. Top 10 Listings
        listings_url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"
        params = {'start': '1', 'limit': '10', 'convert': 'USD', 'sort': 'market_cap'}
        l_resp = requests.get(listings_url, headers=headers, params=params)
        l_json = l_resp.json()

        # --- DEBUG CHECK 2 ---
        if 'status' in l_json and l_json['status']['error_code'] != 0:
             error_msg = l_json['status']['error_message']
             return None, f"CMC Listings Error: {error_msg}"

        listings = l_json['data']

        # Process Top 10
        usdt_mcap = 0
        sum_top10 = 0
        sum_top10_old = 0
        btc_mcap = 0; btc_old = 0
        eth_mcap = 0; eth_old = 0

        for coin in listings:
            symbol = coin['symbol']
            mcap = coin['quote']['USD']['market_cap']
            pct_change = coin['quote']['USD']['percent_change_24h']
            
            mcap_old = mcap / (1 + (pct_change / 100))
            sum_top10 += mcap
            sum_top10_old += mcap_old
            
            if symbol == 'USDT': usdt_mcap = mcap
            if symbol == 'BTC': btc_mcap = mcap; btc_old = mcap_old
            if symbol == 'ETH': eth_mcap = mcap; eth_old = mcap_old

        # Calculations
        usdt_dom = (usdt_mcap / total_mcap) * 100 if total_mcap > 0 else 0
        total_mcap_old = total_mcap / (1 + (total_change_pct / 100))
        
        alts_now = total_mcap - btc_mcap - eth_mcap
        alts_old = total_mcap_old - btc_old - eth_old
        alts_change = calculate_change(alts_now, alts_old)
        
        others_now = total_mcap - sum_top10
        others_old = total_mcap_old - sum_top10_old
        others_change = calculate_change(others_now, others_old)

        return {
            'btc_dom': btc_dom,
            'usdt_dom': usdt_dom,
            'total_val': total_mcap,
            'total_pct': total_change_pct,
            'alts_val': alts_now,
            'alts_pct': alts_change,
            'others_val': others_now,
            'others_pct': others_change
        }, None

    except Exception as e:
        return None, f"Code Exception: {str(e)}"

def get_defi_tvl():
    try:
        url = "https://api.llama.fi/v2/historicalChainTvl"
        resp = requests.get(url, timeout=10)
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
    
    # IF ERROR, RETURN THE ERROR MESSAGE TO TELEGRAM
    if error_msg:
        return f"⚠️ **Debug Error:**\n`{error_msg}`\n\nPlease check your API Key plan or permissions."

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
    msg = await c.bot.send_message(chat_id=u.effective_chat.id, text="🔄 Fetching...")
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
