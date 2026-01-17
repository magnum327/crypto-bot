import logging
import requests
import yfinance as yf
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# --- CONFIGURATION ---

# 1. YOUR TOKEN
TOKEN = "8266373667:AAE_Qrfq8VzMJTNE9Om9_rdbzscWFyBmgJU"

# 2. YOUR TARGET CHAT ID
TARGET_CHAT_ID = "REPLACE_WITH_YOUR_CHAT_ID"

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

# --- DATA FETCHING ---

def get_crypto_data():
    try:
        # HEADERS ARE CRITICAL: They pretend you are a real browser, not a bot.
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        
        # 1. CoinGecko (Global)
        cg_url = "https://api.coingecko.com/api/v3/global"
        cg_response = requests.get(cg_url, headers=headers, timeout=10)
        cg_response.raise_for_status() # Raises error if status is 400/404/429
        cg_data = cg_response.json()['data']
        
        # 2. DefiLlama (TVL)
        dl_url = "https://api.llama.fi/v2/chains"
        dl_response = requests.get(dl_url, headers=headers, timeout=10)
        dl_response.raise_for_status()
        dl_data = dl_response.json()
        total_tvl = sum([chain['tvl'] for chain in dl_data])

        return {
            "btc_dom": cg_data['market_cap_percentage']['btc'],
            "usdt_dom": cg_data['market_cap_percentage']['usdt'],
            "total_mcap": cg_data['total_market_cap']['usd'],
            "mcap_change": cg_data['market_cap_change_percentage_24h_usd'],
            "tvl": total_tvl
        }
    except Exception as e:
        return f"ERROR: {str(e)}" # Return the actual error message

def get_stock_data():
    try:
        # S&P 500 (^GSPC) and Nasdaq (^IXIC)
        tickers = yf.Tickers("^GSPC ^IXIC")
        
        # Fetch history
        sp500 = tickers.tickers["^GSPC"].history(period="5d")
        nasdaq = tickers.tickers["^IXIC"].history(period="5d")
        
        if sp500.empty or nasdaq.empty:
            return "ERROR: Yahoo returned empty data (Likely IP Blocked)"

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
        return f"ERROR: {str(e)}"

def format_number(num):
    if not isinstance(num, (int, float)): return str(num)
    if num >= 1_000_000_000_000: return f"${num / 1_000_000_000_000:.2f}T"
    elif num >= 1_000_000_000: return f"${num / 1_000_000_000:.2f}B"
    else: return f"${num:,.2f}"

def construct_message():
    crypto = get_crypto_data()
    stocks = get_stock_data()
    
    msg = "📊 *MARKET SNAPSHOT* 📊\n\n"

    # CRYPTO SECTION
    if isinstance(crypto, dict):
        mcap_arrow = "🟢" if crypto['mcap_change'] >= 0 else "🔴"
        msg += (
            f"💎 *CRYPTO METRICS*\n"
            f"• *BTC Dom:* `{crypto['btc_dom']:.1f}%`\n"
            f"• *USDT Dom:* `{crypto['usdt_dom']:.1f}%`\n"
            f"• *Total M.Cap:* {format_number(crypto['total_mcap'])} ({mcap_arrow} `{crypto['mcap_change']:.2f}%`)\n"
            f"• *Total TVL:* {format_number(crypto['tvl'])}\n\n"
        )
    else:
        # If it failed, show the specific error
        msg += f"💎 *CRYPTO ERROR:* `{crypto}`\n\n"

    # STOCKS SECTION
    if isinstance(stocks, dict):
        sp_arrow = "🟢" if stocks['sp500_change'] >= 0 else "🔴"
        nd_arrow = "🟢" if stocks['nasdaq_change'] >= 0 else "🔴"
        msg += (
            f"📈 *TRADITIONAL MARKETS*\n"
            f"• *S&P 500:* `{stocks['sp500_price']:.2f}` ({sp_arrow} `{stocks['sp500_change']:.2f}%`)\n"
            f"• *Nasdaq:* `{stocks['nasdaq_price']:.2f}` ({nd_arrow} `{stocks['nasdaq_change']:.2f}%`)"
        )
    else:
        # If it failed, show the specific error
        msg += f"📈 *STOCKS ERROR:* `{stocks}`"

    return msg

# --- COMMAND HANDLERS ---

async def market_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"!!! YOUR CHAT ID IS: {update.effective_chat.id} !!!")
    msg = construct_message()
    await update.message.reply_text(msg, parse_mode='Markdown')

async def auto_post_job(context: ContextTypes.DEFAULT_TYPE):
    if TARGET_CHAT_ID == "REPLACE_WITH_YOUR_CHAT_ID":
        print("⚠️ CANNOT AUTO-POST: TARGET_CHAT_ID is not set.")
        return
    msg = construct_message()
    try:
        await context.bot.send_message(chat_id=TARGET_CHAT_ID, text=msg, parse_mode='Markdown')
    except Exception as e:
        print(f"Error sending auto-post: {e}")

def main():
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("market", market_command))
    job_queue = application.job_queue
    if job_queue:
        job_queue.run_repeating(auto_post_job, interval=14400, first=10)
    
    print("Bot is polling...")
    application.run_polling()

if __name__ == "__main__":
    main()
