import logging
import requests
from telegram import Update, constants
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler
from keep_alive import keep_alive

# --- YOUR KEYS ARE HERE ---
BOT_TOKEN = '8266373667:AAE_Qrfq8VzMJTNE9Om9_rdbzscWFyBmgJU'
ALPHA_VANTAGE_KEY = 'QYX9U4NWWG72RWZ1'

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# --- DATA FETCHING FUNCTIONS ---

def get_stock_data_alpha(symbol):
    """Fetches stock data using Alpha Vantage."""
    try:
        url = f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={symbol}&apikey={ALPHA_VANTAGE_KEY}"
        response = requests.get(url, timeout=10)
        data = response.json()

        # Check if API limit reached or error
        if "Note" in data:
            logging.warning(f"Alpha Vantage Limit Reached for {symbol}")
            return 0.0, 0.0
            
        quote = data.get('Global Quote', {})
        
        if not quote:
            return 0.0, 0.0

        current_price = float(quote.get('05. price', 0))
        change_percent = float(quote.get('10. change percent', '0%').replace('%', ''))
        
        return current_price, change_percent
    except Exception as e:
        logging.error(f"Error fetching {symbol}: {e}")
        return 0.0, 0.0

def get_crypto_data():
    """Fetches global crypto metrics from CoinGecko."""
    try:
        url = "https://api.coingecko.com/api/v3/global"
        response = requests.get(url, timeout=10)
        data = response.json().get('data')
        
        if not data:
            return None

        btc_dom = data['market_cap_percentage'].get('btc', 0)
        usdt_dom = data['market_cap_percentage'].get('usdt', 0)
        total_mcap = data['total_market_cap'].get('usd', 0)
        
        # Calculate Altcoin Market Cap
        btc_mcap = total_mcap * (btc_dom / 100)
        alt_mcap = total_mcap - btc_mcap
        
        return {
            'btc_dom': btc_dom,
            'usdt_dom': usdt_dom,
            'total_mcap': total_mcap,
            'alt_mcap': alt_mcap
        }
    except Exception as e:
        logging.error(f"Error fetching crypto data: {e}")
        return None

def format_number(num):
    if num >= 1_000_000_000_000:
        return f"${num / 1_000_000_000_000:.2f}T"
    elif num >= 1_000_000_000:
        return f"${num / 1_000_000_000:.2f}B"
    else:
        return f"${num:,.2f}"

def generate_report_text():
    """Compiles the text for the message."""
    crypto_data = get_crypto_data()
    
    # Use SPY and QQQ as proxies for S&P 500 and NASDAQ
    spy_price, spy_change = get_stock_data_alpha("SPY")
    qqq_price, qqq_change = get_stock_data_alpha("QQQ")

    if not crypto_data:
        return "⚠️ Error: Could not fetch crypto data."

    spy_emoji = "🟢" if spy_change >= 0 else "🔴"
    qqq_emoji = "🟢" if qqq_change >= 0 else "🔴"

    return (
        f"📊 **MARKET SNAPSHOT**\n\n"
        f"**Crypto Dominance:**\n"
        f"🟠 BTC: `{crypto_data['btc_dom']:.2f}%`\n"
        f"🟢 USDT: `{crypto_data['usdt_dom']:.2f}%`\n\n"
        
        f"**Crypto Market Cap:**\n"
        f"🌍 Total: `{format_number(crypto_data['total_mcap'])}`\n"
        f"🔵 Alts (Excl. BTC): `{format_number(crypto_data['alt_mcap'])}`\n\n"
        
        f"**Wall Street (ETFs):**\n"
        f"{spy_emoji} S&P 500 (SPY): `${spy_price:,.2f}` ({spy_change:+.2f}%)\n"
        f"{qqq_emoji} NASDAQ (QQQ): `${qqq_price:,.2f}` ({qqq_change:+.2f}%)"
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

    # Post every 4 hours (14400 seconds)
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
    # Start the Keep-Alive Web Server
    keep_alive()
    
    # Build the Bot
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # Add Handlers
    application.add_handler(CommandHandler('market', market_command))
    application.add_handler(CommandHandler('start_auto', start_auto))
    application.add_handler(CommandHandler('stop_auto', stop_auto))
    
    print("Bot is running...")
    application.run_polling()
