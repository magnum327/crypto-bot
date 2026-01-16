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
    """Fetches data from CoinCap (No Key Required, Very Stable)."""
    try:
        # Fetch Top 100 Coins to calculate Global Metrics manually
        # This bypasses the need for a 'Global' endpoint that usually gets blocked
        url = "https://api.coincap.io/v2/assets?limit=100"
        resp = requests.get(url, timeout=10)
        
        if resp.status_code != 200:
            return None, f"CoinCap Error: {resp.status_code}"
            
        data = resp.json().get('data', [])
        
        if not data:
            return None, "CoinCap returned empty data."

        # Initialize Variables
        total_mcap_now = 0
        total_mcap_old = 0
        
        usdt_mcap = 0
        btc_mcap = 0
        eth_mcap = 0
        
        sum_top10_now = 0
        sum_top10_old = 0

        # Loop through Top 100 to build the Total Market Cap
        for index, coin in enumerate(data):
            # Parse numbers (CoinCap sends strings)
            price_usd = float(coin['priceUsd'])
            mcap = float(coin['marketCapUsd'])
            change_24h = float(coin['changePercent24Hr'])
            symbol = coin['symbol']
            
            # Calculate what the mcap was 24h ago
            mcap_old = mcap / (1 + (change_24h / 100))
            
            # Add to Totals
            total_mcap_now += mcap
            total_mcap_old += mcap_old
            
            # Handle Top 10 Specifics
            if index < 10:
                sum_top10_now += mcap
                sum_top10_old += mcap_old
            
            # Handle Specific Coins
            if symbol == 'USDT': usdt_mcap = mcap
            if symbol == 'BTC': btc_mcap = mcap
            if symbol == 'ETH': eth_mcap = mcap

        # --- Derived Calculations ---
        
        # 1. BTC Dominance
        btc_dom = (btc_mcap / total_mcap_now) * 100
        
        # 2. USDT Dominance
        usdt_dom = (usdt_mcap / total_mcap_now) * 100
        
        # 3. Total Change %
        total_change_pct = calculate_change(total_mcap_now, total_mcap_old)
        
        # 4. Total ALTS (Total - BTC - ETH)
        # Note: We use Top 100 Sum as 'Total', which is 95%+ of the real market
        alts_now = total_mcap_now - btc_mcap - eth_mcap
        # Estimate Alts Old (using total old - btc old is hard without specific old values, 
        # so we approximate Alts Change using the weighted average of the rest)
        # Simpler method: Sum of (Top 100 Old) - BTC_Old - ETH_Old
        # We need BTC/ETH Old specific values which we calculated in loop but didn't save?
        # Ah, we didn't save specific old values for BTC/ETH. Let's fix loop logic above briefly.
        # Actually, let's keep it simple:
        
        # Re-Loop to find BTC/ETH Old specifically (It's fast)
        btc_old = btc_mcap / (1 + (float(next(c['changePercent24Hr'] for c in data if c['symbol']=='BTC')) / 100))
        eth_old = eth_mcap / (1 + (float(next(c['changePercent24Hr'] for c in data if c['symbol']=='ETH')) / 100))

        alts_old = total_mcap_old - btc_old - eth_old
        alts_change = calculate_change(alts_now, alts_old)
        
        # 5. Others (Total - Top 10)
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
    
    if error_msg:
        return f"⚠️ **Data Error:**\n`{error_msg}`"

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
    msg = await c.bot.send_message(chat_id=u.effective_chat.id, text="🔄 Fetching from CoinCap (Unblockable)...")
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
