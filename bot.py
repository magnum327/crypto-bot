import logging
import requests
import yfinance as yf
import os
from threading import Thread
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# --- CONFIGURATION ---
TOKEN = "8266373667:AAE_Qrfq8VzMJTNE9Om9_rdbzscWFyBmgJU"
# REPLACE THIS with your numeric Chat ID (e.g., "-100..." or "123...")
TARGET_CHAT_ID = "REPLACE_WITH_YOUR_CHAT_ID"
CMC_API_KEY = "9891d93949c7466cb1c8c762f7e6e600"

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

# --- WEB SERVER FOR RENDER (Keep Alive) ---
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Market Bot is active!"

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- DATA FETCHING ---
def get_crypto_data():
    try:
        headers = {
            "X-CMC_PRO_API_KEY": CMC_API_KEY,
            "Accepts": "application/json"
        }

        # 1. Global Metrics (Cap, BTC Dom, Volume)
        url_global = "https://pro-api.coinmarketcap.com/v1/global-metrics/quotes/latest"
        r_global = requests.get(url_global, headers=headers)
        r_global.raise_for_status()
        global_data = r_global.json()['data']
        usd_data = global_data['quote']['USD']
        
        btc_dom = global_data['btc_dominance']
        total_mcap = usd_data['total_market_cap']
        mcap_change = usd_data['total_market_cap_change_24h']
        vol_24h = usd_data['total_volume_24h']
        vol_change = usd_data['total_volume_24h_yesterday_percentage_change']

        # 2. USDT Dominance Calculation
        url_usdt = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest?symbol=USDT"
        r_usdt = requests.get(url_usdt, headers=headers)
        usdt_mcap = r_usdt.json()['data']['USDT']['quote']['USD']['market_cap']
        usdt_dom = (usdt_mcap / total_mcap) * 100

        # 3. TVL from DefiLlama
        dl_url = "https://api.llama.fi/v2/chains"
        dl_data = requests.get(dl_url).json()
        total_tvl = sum([chain['tvl'] for chain in dl_data])

        return {
            "btc_dom": btc_dom,
            "usdt_dom": usdt_dom,
            "total_mcap": total_mcap,
            "mcap_change": mcap_change,
            "vol_24h": vol_24h,
            "vol_change": vol_change,
            "tvl": total_tvl
        }
    except Exception as e:
        return f"Crypto Error: {str(e)}"

def get_stock_data():
    try:
        tickers = yf.Tickers("^GSPC ^IXIC")
        sp500 = tickers.tickers["^GSPC"].history(period="5d")
        nasdaq = tickers.tickers["^IXIC"].history(period="5d")
        
        if sp500.empty or nasdaq.empty:
            return "Stock Error: Empty data"

        sp_price = sp500['Close'].iloc[-1]
        sp_change = ((sp_price - sp500['Close'].iloc[-2]) / sp500['Close'].iloc[-2]) * 100
        
        nd_price = nasdaq['Close'].iloc[-1]
        nd_change = ((nd_price - nasdaq['Close'].iloc[-2]) / nasdaq['Close'].iloc[-2]) * 100

        return {
            "sp_price": sp_price, "sp_change": sp_change,
            "nd_price": nd_price, "nd_change": nd_change
        }
    except Exception as e:
        return f"Stock Error: {str(e)}"

def format_number(num):
    if not isinstance(num, (int, float)): return str(num)
    if num >= 1_000_000_000_000: return f"${num / 1_000_000_000_000:.2f}T"
    elif num >= 1_000_000_000: return f"${num / 1_000_000_000:.2f}B"
    else: return f"${num:,.2f}"

def construct_message():
    crypto = get_crypto_data()
    stocks = get_stock_data()
    
    msg = "📊 *MARKET SNAPSHOT* 📊\n\n"

    if isinstance(crypto, dict):
        mc_arr = "🟢" if crypto['mcap_change'] >= 0 else "🔴"
        v_arr = "🟢" if crypto['vol_change'] >= 0 else "🔴"
        msg += (
            f"💎 *CRYPTO METRICS*\n"
            f"• *BTC Dom:* `{crypto['btc_dom']:.2f}%`\n"
            f"• *USDT Dom:* `{crypto['usdt_dom']:.2f}%`\n"
            f"• *Total M.Cap:* {format_number(crypto['total_mcap'])} ({mc_arr} `{crypto['mcap_change']:.2f}%`)\n"
            f"• *24h Volume:* {format_number(crypto['vol_24h'])} ({v_arr} `{crypto['vol_change']:.2f}%`)\n"
            f"• *Total TVL:* {format_number(crypto['tvl'])}\n\n"
        )
    else:
        msg += f"⚠️ `{crypto}`\n\n"

    if isinstance(stocks, dict):
        sp_arr = "🟢" if stocks['sp_change'] >= 0 else "🔴"
        nd_arr = "🟢" if stocks['nd_change'] >= 0 else "🔴"
        msg += (
            f"📈 *TRADITIONAL MARKETS*\n"
            f"• *S&P 500:* `{stocks['sp_price']:.2f}` ({sp_arr} `{stocks['sp_change']:.2f}%`)\n"
            f"• *Nasdaq:* `{stocks['nd_price']:.2f}` ({nd_arr} `{stocks['nd_change']:.2f}%`)"
        )
    else:
        msg += f"⚠️ `{stocks}`"

    return msg

# --- HANDLERS ---
async def market_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"Chat ID: {update.effective_chat.id}") # View in Render logs
    await update.message.reply_text(construct_message(), parse_mode='Markdown')

async def auto_post_job(context: ContextTypes.DEFAULT_TYPE):
    if "REPLACE" not in TARGET_CHAT_ID:
        await context.bot.send_message(chat_id=TARGET_CHAT_ID, text=construct_message(), parse_mode='Markdown')

def main():
    Thread(target=run_web_server, daemon=True).start()
    app_bot = Application.builder().token(TOKEN).build()
    app_bot.add_handler(CommandHandler("market", market_command))
    if app_bot.job_queue:
        app_bot.job_queue.run_repeating(auto_post_job, interval=14400, first=10)
    app_bot.run_polling()

if __name__ == "__main__":
    main()
