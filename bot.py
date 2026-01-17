import logging
import requests
import yfinance as yf
import asyncio
from datetime import time
from telegram import Bot
from telegram.ext import Application, CommandHandler, ContextTypes

# --- CONFIGURATION ---
# Replace with your actual Bot Token from BotFather
TOKEN = "YOUR_TELEGRAM_BOT_TOKEN_HERE"
# Replace with your Chat ID (or a channel ID) where auto-posts should go
# You can find this by messaging your bot and checking updates, or using @userinfobot
TARGET_CHAT_ID = "YOUR_CHAT_ID_HERE" 

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

# --- DATA FETCHING FUNCTIONS ---

def get_crypto_data():
    try:
        # 1. Global Metrics (Market Cap, Dominance) from CoinGecko
        # Note: CoinGecko has a free API rate limit.
        cg_url = "https://api.coingecko.com/api/v3/global"
        cg_data = requests.get(cg_url).json()['data']
        
        btc_dom = cg_data['market_cap_percentage']['btc']
        usdt_dom = cg_data['market_cap_percentage']['usdt']
        total_mcap = cg_data['total_market_cap']['usd']
        mcap_change = cg_data['market_cap_change_percentage_24h_usd']
        
        # 2. TVL from DefiLlama
        dl_url = "https://api.llama.fi/v2/chains"
        dl_data = requests.get(dl_url).json()
        # Summing up TVL from all chains
        total_tvl = sum([chain['tvl'] for chain in dl_data])

        return {
            "btc_dom": btc_dom,
            "usdt_dom": usdt_dom,
            "total_mcap": total_mcap,
            "mcap_change": mcap_change,
            "tvl": total_tvl
        }
    except Exception as e:
        logging.error(f"Error fetching crypto data: {e}")
        return None

def get_stock_data():
    try:
        # Fetch S&P 500 (^GSPC) and Nasdaq (^IXIC)
        tickers = yf.Tickers("^GSPC ^IXIC")
        
        sp500 = tickers.tickers["^GSPC"].history(period="2d")
        nasdaq = tickers.tickers["^IXIC"].history(period="2d")
        
        # Calculate changes
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
        logging.error(f"Error fetching stock data: {e}")
        return None

def format_number(num):
    # Helper to format large numbers (Trillions, Billions)
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

    # Arrows for positive/negative change
    mcap_arrow = "🟢" if crypto['mcap_change'] >= 0 else "🔴"
    sp_arrow = "🟢" if stocks['sp500_change'] >= 0 else "🔴"
    nd_arrow = "🟢" if stocks['nasdaq_change'] >= 0 else "🔴"

    message = (
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
    return message

# --- BOT COMMANDS & JOBS ---

async def market_command(update, context):
    """Responds to /market command"""
    msg = construct_message()
    await update.message.reply_text(msg, parse_mode='Markdown')

async def auto_post_job(context: ContextTypes.DEFAULT_TYPE):
    """Job to run every 4 hours"""
    msg = construct_message()
    await context.bot.send_message(chat_id=TARGET_CHAT_ID, text=msg, parse_mode='Markdown')

def main():
    # Build the application
    application = Application.builder().token(TOKEN).build()

    # Add command handler
    application.add_handler(CommandHandler("market", market_command))

    # Add JobQueue for the 4-hour auto post
    job_queue = application.job_queue
    # 14400 seconds = 4 hours
    job_queue.run_repeating(auto_post_job, interval=14400, first=10)

    # Run the bot
    application.run_polling()

if __name__ == "__main__":
    main()
