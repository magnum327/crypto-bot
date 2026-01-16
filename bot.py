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

# --- DATA FETCHING FUNCTIONS ---

def get_stock_data(ticker_symbol):
    """Fetches price and daily % change using Yahoo Finance."""
    try:
        ticker = yf.Ticker(ticker_symbol)
        # Get 2 days of data to calculate change
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
    """Fetches crypto data using CoinPaprika (Global) and CoinCap (Top 10)."""
    try:
        # 1. Get Global Data from CoinPaprika (More reliable for Total Cap)
        global_url = "https://api.coinpaprika.com/v1/global"
        global_resp = requests.get(global_url, timeout=10)
        global_data = global_resp.json()
        
        # 2. Get Top 10 Assets from CoinCap (Fast & Free)
        assets_url = "https://api.coincap.io/v2/assets?limit=10"
        assets_resp = requests.get(assets_url, timeout=10)
        assets_data = assets_resp.json().get('data', [])

        # --- Parse Global Metrics ---
        total_mcap = global_data.get('market_cap_usd', 0)
        btc_dom = global_data.get('bitcoin_dominance_percentage', 0)
        
        # --- Parse Top 10 to find USDT Dom and OTHERS ---
        top_10_mcap_sum = 0
        usdt_mcap = 0
        
        for coin in assets_data:
            mcap = float(coin.get('marketCapUsd', 0))
            top_10_mcap_sum += mcap
            
            if coin.get('symbol') == 'USDT':
                usdt_mcap = mcap
        
        # Calculate USDT Dominance
        usdt_dom = (usdt_mcap / total_mcap) * 100 if total_mcap > 0 else 0
        
        # Calculate OTHERS (Total - Top 10)
        others_mcap = total_mcap - top_10_mcap_sum
        
        # Calculate TOTAL3 (Approximate: Total - BTC MCap - ETH MCap)
        # We can get BTC/ETH mcap from the assets_data list
        btc_mcap = next((float(c['marketCapUsd']) for c in assets_data if c['symbol'] == 'BTC'), 0)
        eth_mcap = next((float(c['marketCapUsd']) for c in assets_data if c['symbol'] == 'ETH'), 0)
        total3_mcap = total_mcap - btc_mcap - eth_mcap

        return {
            'btc_dom': btc_dom,
            'usdt_dom': usdt_dom,
            'total_mcap': total_mcap,
            'total3_mcap': total3_mcap,
            'others_mcap': others_mcap
        }
    except Exception as e:
        logging.error(f"Error fetching crypto data: {e}")
        return None

def get_defi_tvl():
    """Fetches Total Value Locked (TVL) from DeFiLlama."""
    try:
        url = "https://api.llama.fi/v2/historicalChainTvl"
        response = requests.get(url, timeout=10)
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
    
    # Stock Tickers: ^DJI (Dow), ^GSPC (S&P), ^IXIC (Nasdaq)
    dow_price, dow_change = get_stock_data("^DJI")
    sp500_price, sp500_change = get_stock_data("^GSPC")
    nasdaq_price, nasdaq_change = get_stock_data("^IXIC")

    if not crypto_data:
        return "⚠️ Error: Could not fetch crypto data. (Check logs)"

    # Emojis
    dow_emoji = "🟢" if dow_change >= 0 else "🔴"
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
        f"{dow_emoji} Dow Jones: `{dow_price:,.0f}` ({dow_change:+.2f}%)\n"
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
