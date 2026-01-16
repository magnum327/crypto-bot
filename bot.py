import logging
import requests
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

# --- HEADERS ---
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept': 'application/json'
}

# --- HELPER FUNCTIONS ---

def calculate_change(current, previous):
    """Calculates percentage change between two numbers."""
    if previous == 0:
        return 0.0
    return ((current - previous) / previous) * 100

def format_with_emoji(value, change_pct):
    """Formats a number with emoji and percentage."""
    # Determine Emoji
    emoji = "🟢" if change_pct >= 0 else "🔴"
    sign = "+" if change_pct >= 0 else ""
    
    # Format the Value (Trillions/Billions)
    if value >= 1_000_000_000_000:
        val_str = f"${value / 1_000_000_000_000:.2f}T"
    elif value >= 1_000_000_000:
        val_str = f"${value / 1_000_000_000:.2f}B"
    else:
        val_str = f"${value:,.2f}"
        
    return f"{emoji} {val_str} ({sign}{change_pct:.2f}%)"

# --- DATA FETCHING FUNCTIONS ---

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
    try:
        # 1. Global Data (Total Cap & Change)
        global_resp = requests.get("https://api.coinpaprika.com/v1/global", headers=HEADERS, timeout=10)
        g_data = global_resp.json()
        
        # 2. Top 10 Tickers (To calculate Alts & Others)
        # We need 'percent_change_24h' to calculate yesterday's cap for each coin
        tickers_resp = requests.get("https://api.coinpaprika.com/v1/tickers?limit=10&quotes=USD", headers=HEADERS, timeout=10)
        top_10 = tickers_resp.json()

        # --- Current Metrics ---
        total_mcap_now = int(g_data.get('market_cap_usd', 0))
        total_change_pct = float(g_data.get('market_cap_change_24h', 0))
        btc_dom = float(g_data.get('bitcoin_dominance_percentage', 0))
        
        # Calculate Total Cap 24h Ago (Reverse Engineering)
        total_mcap_old = total_mcap_now / (1 + (total_change_pct / 100))

        # --- Process Top 10 to find Sub-Metrics ---
        usdt_mcap = 0
        
        # We need these sums to calculate "Others" and "Alts"
        sum_top10_now = 0
        sum_top10_old = 0
        
        btc_now = 0; btc_old = 0
        eth_now = 0; eth_old = 0

        for coin in top_10:
            symbol = coin['symbol']
            quote = coin['quotes']['USD']
            
            price_now = quote['market_cap']
            pct_change = quote['percent_change_24h']
            
            # Calculate what this coin's mcap was 24h ago
            price_old = price_now / (1 + (pct_change / 100))
            
            # Add to sums
            sum_top10_now += price_now
            sum_top10_old += price_old
            
            if symbol == 'USDT': usdt_mcap = price_now
            if symbol == 'BTC': btc_now = price_now; btc_old = price_old
            if symbol == 'ETH': eth_now = price_now; eth_old = price_old

        # --- 1. USDT Dominance ---
        usdt_dom = (usdt_mcap / total_mcap_now) * 100 if total_mcap_now > 0 else 0

        # --- 2. Total ALTS (Total - BTC - ETH) ---
        alts_now = total_mcap_now - btc_now - eth_now
        alts_old = total_mcap_old - btc_old - eth_old
        alts_change = calculate_change(alts_now, alts_old)

        # --- 3. ALT Excluding Top 10 (Total - Top 10) ---
        others_now = total_mcap_now - sum_top10_now
        others_old = total_mcap_old - sum_top10_old
        others_change = calculate_change(others_now, others_old)

        return {
            'btc_dom': btc_dom,
            'usdt_dom': usdt_dom,
            
            'total_val': total_mcap_now,
            'total_pct': total_change_pct,
            
            'alts_val': alts_now,
            'alts_pct': alts_change,
            
            'others_val': others_now,
            'others_pct': others_change
        }
    except Exception as e:
        logging.error(f"Error crypto: {e}")
        return None

def get_defi_tvl():
    try:
        # Get historical to find today vs yesterday
        url = "https://api.llama.fi/v2/historicalChainTvl"
        resp = requests.get(url, headers=HEADERS, timeout=10)
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
    c_data = get_crypto_data()
    tvl_val, tvl_change = get_defi_tvl()
    
    dow_p, dow_c = get_stock_data("^DJI")
    sp_p, sp_c = get_stock_data("^GSPC")
    ndq_p, ndq_c = get_stock_data("^IXIC")

    if not c_data: return "⚠️ Error: Could not fetch data."

    # Stock formatting
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
