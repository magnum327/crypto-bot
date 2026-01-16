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

# --- HEADERS TO MIMIC A REAL BROWSER ---
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept': 'application/json'
}

# --- DATA FETCHING FUNCTIONS ---

def get_stock_data(ticker_symbol):
    """Fetches price and daily % change using Yahoo Finance."""
    try:
        ticker = yf.Ticker(ticker_symbol)
        history = ticker.history(period="2d")
        
        if len(history) < 2:
            return 0.0, 0.0
            
        current_price = history['Close'].iloc[-1]
        previous_close = history['Close'].iloc[-2]
        
        change_percent = ((current_price - previous_close) / previous_close) * 100
        return current_price, change_percent
    except Exception as e:
        logging.error(f"Error fetching stock {ticker_symbol}: {e}")
        return 0.0, 0.0

def get_crypto_data():
    """Fetches global crypto metrics and Top 10 data from CoinGecko."""
    try:
        # 1. Get Global Data
        global_url = "https://api.coingecko.com/api/v3/global"
        global_resp = requests.get(global_url, headers=HEADERS, timeout=10)
        global_data = global_resp.json().get('data')
        
        if not global_data:
            return None

        # 2. Get Top 10 Coins (to calculate OTHERS)
        # We fetch the top 10 coins by market cap to sum them up
        markets_url = "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=10&page=1"
        markets_resp = requests.get(markets_url, headers=HEADERS, timeout=10)
        top_10_data = markets_resp.json()

        # Metrics
        btc_dom = global_data['market_cap_percentage'].get('btc', 0)
        usdt_dom = global_data['market_cap_percentage'].get('usdt', 0)
        total_mcap = global_data['total_market_cap'].get('usd', 0)
        
        # Calculate TOTAL3 (Total - BTC - ETH)
        btc_mcap = total_mcap * (btc_dom / 100)
        eth_dom = global_data['market_cap_percentage'].get('eth', 0)
        eth_mcap = total_mcap * (eth_dom / 100)
        total3_mcap = total_mcap - btc_mcap - eth_mcap

        # Calculate OTHERS (Total - Top 10)
        top_10_sum = 0
        if isinstance(top_10_data, list):
            for coin in top_10_data:
                top_10_sum += coin.get('market_cap', 0)
        
        others_mcap = total_mcap - top_10_sum
        
        return {
            'btc_dom': btc_dom,
            'usdt_dom': usdt_dom,
            'total_mcap': total_mcap,
            'total3_mcap': total3_mcap, # Alts (No BTC/ETH)
            'others_mcap': others_mcap  # Others (No Top 10)
        }
    except Exception as e:
        logging.error(f"Error fetching crypto data: {e}")
        return None

def get_defi_tvl():
    """Fetches Total Value Locked (TVL) from DeFiLlama."""
    try:
        url = "https://api.llama.fi/v2/historicalChainTvl"
        response = requests.get(url, headers=HEADERS, timeout=10)
        data = response.json()
        
        if not data:
            return 0
            
        latest_tvl = data[-1]['tvl']
        return latest_tvl
    except Exception as e:
        logging.error(f"Error fetching DeFi TVL: {e}")
        return 0

def format_number(num):
    if num >= 1_000_000_000_000:
        return f"${num / 1_000_000_000_000:.2f}T"
    elif num >= 1_000_000_000:
        return f"${num / 1_000_000_000:.2f}B"
    else:
        return f"${num:,.2f}"

def generate_report_text():
    crypto_data = get_crypto_data()
    defi_tvl = get_defi_tvl()
    
    sp500_price, sp500_change = get_stock_data("^GSPC")
    nasdaq_price, nasdaq_change = get_stock_data("^IXIC")

    if not crypto_data:
        return "⚠️ Error: Could not fetch crypto data. (Check logs)"

    sp500_emoji = "🟢" if sp500_change >= 0 else "🔴"
    nasdaq_emoji = "🟢" if nasdaq_change >= 0 else "🔴"

    return (
        f"📊 **MARKET SNAPSHOT**\n\n"
        f"**Crypto Dominance:**\n"
        f"🟠 BTC: `{crypto_data['btc_dom']:.2f}%`\n"
        f"🟢 USDT: `{crypto_data['usdt_dom']:.2f}%`\n\n"
        
        f"**Crypto Market Cap:**\n"
        f"🌍 Total: `{format_number(crypto_data['total_mcap'])}`\n"
        f"🔵 TOTAL3 (Alts): `{format_number(crypto_data['total3_mcap'])}`\n"
        f"🟣 OTHERS (No Top 10): `{format_number(crypto_data['others_mcap'])}`\n"
        f"🔒 DeFi TVL: `{format_number(defi_tvl)}`\n\n"
        
        f"**Traditional Markets:**\n"
        f"{sp500_emoji} S&P 500: `{sp500_price:,.0f}` ({sp500_change:+.2f}%)\n"
        f"{nasdaq_emoji} NASDAQ: `{nasdaq_price:,.0f}` ({nasdaq_change:+.2f}%)"
    )

# --- BOT HANDLERS ---

async def market_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await context.bot.send_message(chat_id=update.effective_chat.id, text="🔄 Fetching data...")
    report = generate_report_text()
    await context.bot.edit_message_text(
        chat_id=update.effective_chat.id,
        message_id=msg.message_id,
        text=report,
        parse_mode=constants.ParseMode.MARKDOWN
    )

async def auto_post_callback(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    report = generate_report_text()
    await context.bot.send_message(chat_id=job.chat_id, text=report, parse_mode=constants.ParseMode.MARKDOWN)

async def start_auto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_message.chat_id
    current_jobs = context.job_queue.get_jobs_by_name(str(chat_id))
    for job in current_jobs:
        job.schedule_removal()
    context.job_queue.run_repeating(auto_post_callback, interval=14400, first=10, chat_id=chat_id, name=str(chat_id))
    await context.bot.send_message(chat_id=chat_id, text="✅ Auto-posting started! I will post market stats every 4 hours.")

async def stop_auto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_message.chat_id
    current_jobs = context.job_queue.get_jobs_by_name(str(chat_id))
    if not current_jobs:
        await context.bot.send_message(chat_id=chat_id, text="❌ No auto-posting job found.")
        return
    for job in current_jobs:
        job.schedule_removal()
    await context.bot.send_message(chat_id=chat_id, text="🛑 Auto-posting stopped.")

if __name__ == '__main__':
    keep_alive()
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler('market', market_command))
    application.add_handler(CommandHandler('start_auto', start_auto))
    application.add_handler(CommandHandler('stop_auto', stop_auto))
    print("Bot is running...")
    application.run_polling()
