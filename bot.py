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
    """Fetches data from CryptoCompare (Top 100 Sum Method)."""
    try:
        # Fetch Top 100 coins by Market Cap
        url = "https://min-api.cryptocompare.com/data/top/mktcapfull?limit=100&tsym=USD"
        resp = requests.get(url, timeout=10)
        
        if resp.status_code != 200:
            return None, f"CryptoCompare Error: {resp.status_code}"
            
        data = resp.json().get('Data', [])
        if not data:
            return None, "CryptoCompare returned empty data."

        # Variables for Totals
        total_mcap = 0
        total_mcap_weighted_change = 0  # To calculate global % change
        
        sum_top10 = 0
        sum_top10_weighted_change = 0
        
        usdt_mcap = 0
        btc_mcap = 0
        eth_mcap = 0

        # Loop through Top 100
        for index, coin_obj in enumerate(data):
            # CryptoCompare nests data in 'RAW' -> 'USD'
            if 'RAW' not in coin_obj or 'USD' not in coin_obj['RAW']:
                continue
                
            coin = coin_obj['RAW']['USD']
            symbol = coin.get('FROMSYMBOL')
            mcap = coin.get('MKTCAP', 0)
            change_24h = coin.get('CHANGEPCT24HOUR', 0)
            
            # Add to Totals
            total_mcap += mcap
            # Weight the change by market cap to get an accurate "Total % Change"
            total_mcap_weighted_change += (mcap * change_24h)

            # Handle Top 10
            if index < 10:
                sum_top10 += mcap
                sum_top10_weighted_change += (mcap * change_24h)
            
            if symbol == 'USDT': usdt_mcap = mcap
            if symbol == 'BTC': btc_mcap = mcap
            if symbol == 'ETH': eth_mcap = mcap

        # --- Calculate Derived Metrics ---
        
        # 1. Global % Change (Weighted Average)
        total_change_pct = total_mcap_weighted_change / total_mcap if total_mcap > 0 else 0
        
        # 2. Dominance
        btc_dom = (btc_mcap / total_mcap) * 100 if total_mcap > 0 else 0
        usdt_dom = (usdt_mcap / total_mcap) * 100 if total_mcap > 0 else 0
        
        # 3. Alts (Total - BTC - ETH)
        alts_val = total_mcap - btc_mcap - eth_mcap
        # Calculate Alts % Change (Total Weighted - BTC Weighted - ETH Weighted) / Alts Val
        # We need to find BTC/ETH change again to do this accurately
        btc_change = next((c['RAW']['USD']['CHANGEPCT24HOUR'] for c in data if c['RAW']['USD']['FROMSYMBOL'] == 'BTC'), 0)
        eth_change = next((c['RAW']['USD']['CHANGEPCT24HOUR'] for c in data if c['RAW']['USD']['FROMSYMBOL'] == 'ETH'), 0)
        
        alts_weighted_change = total_mcap_weighted_change - (btc_mcap * btc_change) - (eth_mcap * eth_change)
        alts_change_pct = alts_weighted_change / alts_val if alts_val > 0 else 0

        # 4. Others (Total - Top 10)
        others_val = total_mcap - sum_top10
        others_weighted_change = total_mcap_weighted_change - sum_top10_weighted_change
        others_change_pct = others_weighted_change / others_val if others_val > 0 else 0

        return {
            'btc_dom': btc_dom,
            'usdt_dom': usdt_dom,
            'total_val': total_mcap,
            'total_pct': total_change_pct,
            'alts_val': alts_val,
            'alts_pct': alts_change_pct,
            'others_val': others_val,
            'others_pct': others_change_pct
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
        if yesterday == 0: return 0.0, 0.0
        change = ((today - yesterday) / yesterday) * 100
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
    msg = await c.bot.send_message(chat_id=u.effective_chat.id, text="🔄 Fetching from CryptoCompare...")
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
