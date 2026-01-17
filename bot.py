import logging
import requests
import yfinance as yf
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# --- CONFIGURATION ---

# 1. The Token you provided
TOKEN = "8266373667:AAE_Qrfq8VzMJTNE9Om9_rdbzscWFyBmgJU"

# 2. TARGET CHAT ID
# YOU MUST REPLACE THIS with your numeric Chat ID (e.g., 123456789)
# If you don't know it, run the bot, type /market, and check your computer's console logs.
TARGET_CHAT_ID = "REPLACE_WITH_YOUR_CHAT_ID"

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

# --- DATA FETCHING ---

def get_crypto_data():
    try:
        # CoinGecko for Global Stats
        cg_url = "https://api.coingecko.com/api/v3/global"
        cg_data = requests.get(cg_url).json()['data']
        
        # DefiLlama for TVL
        dl_url = "https://api.llama.fi/v2/chains"
        dl_data = requests.get(dl_url).json()
        total_tvl = sum([chain['tvl'] for chain in dl_data])

        return {
            "btc_dom": cg_data['market_cap_percentage']['btc'],
            "usdt_dom": cg_data['market_cap_percentage']['usdt'],
            "total_mcap": cg_data['total_market_cap']['usd'],
            "mcap_change": cg_data['market_cap_change_percentage_24h_usd'],
            "tvl": total_tvl
        }
    except Exception as e:
        logging.error(f"Crypto Data Error: {e}")
        return None

def get_stock_data():
    try:
        # S&P 500 (^GSPC) and Nasdaq (^IXIC)
        tickers = yf.Tickers("^GSPC ^IXIC")
        sp500 = tickers.tickers["^GSPC"].history(period="5d")
        nasdaq = tickers.tickers["^IXIC"].history(period="5d")
        
        # Calculate changes based on last two closes
        sp500_close = sp500['Close'].iloc[-1]
        sp500_prev = sp500['Close'].iloc[-2]
        sp500_change = ((sp500_close - sp500_prev) / sp500_prev) * 100
        
        nasdaq_close = nasdaq['Close'].iloc[-1]
        nasdaq_prev = nasdaq['Close'].iloc[-2]
        nasdaq_change = ((nasdaq_close - nasdaq_prev) / nasdaq_prev) * 100

        return {
            "sp500_price": sp500_close,
            "sp500_change": sp500_change,
            "nasdaq_price": nasdaq_close,
            "nasdaq_change": nasdaq_change
        }
    except Exception as e:
        logging.error(f"Stock Data Error: {e}")
        return None

def format_number(num):
    # Formats Trillions (T) and Billions (B)
    if num >= 1_000_000_000_000:
        return f"${num / 1_000_000_000_000:.2f}T"
    elif num >= 1_000_000_000:
        return f"${num / 1_000_000_000:.2f}B"
    else:
        return f"${num:,.2f}"

def construct_message():
    crypto = get_crypto_data()
    stocks = get_stock_data()
    
    if not crypto or not stocks:
        return "⚠️ *Error fetching market data.* Please try again later."

    # Determine Arrows
    mcap_arrow = "🟢" if crypto['mcap_change'] >= 0 else "🔴"
    sp_arrow = "🟢" if stocks['sp500_change'] >= 0 else "🔴"
    nd_arrow = "🟢" if stocks['nasdaq_change'] >= 0 else "🔴"

    # Build Message
    msg = (
        f"📊 *MARKET SNAPSHOT* 📊\n\n"
        f"💎 *CRYPTO METRICS*\n"
        f"• *BTC Dom:* `{crypto['btc_dom']:.1f}%`\n"
        f"• *USDT Dom:* `{crypto['usdt_dom']:.1f}%`\n"
        f"• *Total M.Cap:* {format_number(crypto['total_mcap'])} ({mcap_arrow} `{crypto['mcap_change']:.2f}%`)\n"
        f"• *Total TVL:* {format_number(crypto['tvl'])}\n\n"
        f"📈 *TRADITIONAL MARKETS*\n"
        f"• *S&P 500:* `{stocks['sp500_price']:.2f}` ({sp_arrow} `{stocks['sp500_change']:.2f}%`)\n"
        f"• *Nasdaq:* `{stocks['nasdaq_price']:.2f}` ({nd_arrow} `{stocks['nasdaq_change']:.2f}%`)"
    )
    return msg

# --- COMMAND HANDLERS ---

async def market_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Print Chat ID to console so you can grab it for the config
    print(f"!!! YOUR CHAT ID IS: {update.effective_chat.id} !!!")
    
    msg = construct_message()
    await update.message.reply_text(msg, parse_mode='Markdown')

async def auto_post_job(context: ContextTypes.DEFAULT_TYPE):
    if TARGET_CHAT_ID == "REPLACE_WITH_YOUR_CHAT_ID":
        print("⚠️ CANNOT AUTO-POST: TARGET_CHAT_ID is not set in bot.py")
        return
        
    msg = construct_message()
    try:
        await context.bot.send_message(chat_id=TARGET_CHAT_ID, text=msg, parse_mode='Markdown')
    except Exception as e:
        print(f"Error sending auto-post: {e}")

def main():
    # Build Application
    application = Application.builder().token(TOKEN).build()

    # Commands
    application.add_handler(CommandHandler("market", market_command))

    # Job Queue (Every 4 hours)
    # 14400 seconds = 4 hours
    job_queue = application.job_queue
    if job_queue:
        job_queue.run_repeating(auto_post_job, interval=14400, first=10)
    else:
        print("Error: Job Queue not available. Did you install 'python-telegram-bot[job-queue]'?")

    # Run
    print("Bot is polling...")
    application.run_polling()

if __name__ == "__main__":
    main()
