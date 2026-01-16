import logging
import requests
import random
import yfinance as yf
from telegram import Update, constants
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler
from keep_alive import keep_alive
from tradingview_ta import TA_Handler, Interval, Exchange

# --- CONFIGURATION ---
BOT_TOKEN = '8266373667:AAE_Qrfq8VzMJTNE9Om9_rdbzscWFyBmgJU'

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# --- HELPER FUNCTIONS ---
def format_with_emoji(value, change_pct=0, is_volume=False):
    if value is None: return "N/A"
    if change_pct is None: change_pct = 0
    
    emoji = "🟢" if change_pct >= 0 else "🔴"
    sign = "+" if change_pct >= 0 else ""
    
    if value >= 1_000_000_000_000:
        val_str = f"${value / 1_000_000_000_000:.2f}T"
    elif value >= 1_000_000_000:
        val_str = f"${value / 1_000_000_000:.2f}B"
    else:
        val_str = f"${value:,.2f}"
        
    return f"{emoji} {val_str} ({sign}{change_pct:.2f}%)"

# ==========================================
#        DATA SOURCES
# ==========================================

def get_tv_data(symbol):
    """
    Fetches Crypto Data from TradingView (Bypasses API blocks)
    """
    try:
        handler = TA_Handler(
            symbol=symbol,
            screener="crypto",
            exchange="CRYPTOCAP",
            interval=Interval.INTERVAL_1_DAY
        )
        analysis = handler.get_analysis()
        
        # Get Price and Candle Data
        current = analysis.indicators.get('close')
        open_price = analysis.indicators.get('open')
        volume = analysis.indicators.get('volume')
        
        # Calculate daily change %
        if open_price and open_price != 0:
            change = ((current - open_price) / open_price) * 100
        else:
            change = 0
            
        return current, change, volume
    except Exception as e:
        logging.error(f"TV Error {symbol}: {e}")
        return None, None, None

def get_crypto_data():
    # 1. Total Market Cap (Symbol: TOTAL)
    total_val, total_change, total_vol = get_tv_data("TOTAL")
    
    # 2. BTC Dominance (Symbol: BTC.D)
    btc_dom, btc_change, _ = get_tv_data("BTC.D")
    
    # 3. USDT Dominance (Symbol: USDT.D)
    usdt_dom, usdt_change, _ = get_tv_data("USDT.D")
    
    # 4. ETH Dominance (For Alts Calculation)
    eth_dom, _, _ = get_tv_data("ETH.D")

    return {
        'total_cap': total_val,
        'total_change': total_change,
        'total_vol': total_vol,
        'btc_dom': btc_dom,
        'usdt_dom': usdt_dom,
        'eth_dom': eth_dom
    }

def get_tvl_data():
    # DeFiLlama (TVL) - Usually safe from blocks
    try:
        r = requests.get("https://api.llama.fi/v2/historicalChainTvl", timeout=10)
        d = r.json()
        curr = d[-1]['tvl']
        prev = d[-2]['tvl']
        change = ((curr - prev)/prev)*100
        return curr, change, "DeFiLlama"
    except:
        return None, None, "Error"

def get_stock_data(ticker):
    # Direct Yahoo API (Bypasses yfinance library blocks)
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=2d"
        r = requests.get(url, headers=headers, timeout=5)
        data = r.json()['chart']['result'][0]
        
        # Extract closing prices
        quotes = data['indicators']['quote'][0]['close']
        # Filter out Nones (common in Yahoo data)
        valid_quotes = [q for q in quotes if q is not None]
        
        if len(valid_quotes) < 2: return None, None, "NoData"
        
        curr = valid_quotes[-1]
        prev = valid_quotes[-2]
        change = ((curr - prev)/prev)*100
        
        return curr, change, "Yahoo(API)"
    except:
        return None, None, "Failed"

# --- REPORT GENERATOR ---
def generate_report():
    c = get_crypto_data()
    tvl_val, tvl_pct, tvl_src = get_tvl_data()
    sp_val, sp_pct, sp_src = get_stock_data("^GSPC")
    ndq_val, ndq_pct, ndq_src = get_stock_data("^IXIC")

    output = "📊 **MARKET SNAPSHOT**\n\n"
    
    # --- CRYPTO SECTION ---
    output += "**Crypto Market Cap:**\n"
    
    if c['total_cap']:
        output += f"🌍 Total: {format_with_emoji(c['total_cap'], c['total_change'])} (Src: TradingView)\n"
        
        # Volume Check
        if c['total_vol'] and c['total_vol'] > 0:
             # TradingView volume for 'TOTAL' is often an index, let's verify magnitude
             # If > 1 Billion, assumes standard USD volume
             if c['total_vol'] > 1_000_000_000:
                 output += f"📊 Vol: ${c['total_vol']/1_000_000_000:.2f}B (Src: TradingView)\n"
             else:
                 output += f"📊 Vol: {c['total_vol']:,.0f} (Src: TradingView)\n"
        else:
             output += f"📊 Vol: N/A\n"
             
        # Alts Calculation
        if c['btc_dom'] and c['eth_dom']:
            alts_val = c['total_cap'] * (1 - (c['btc_dom']/100) - (c['eth_dom']/100))
            output += f"🔵 Total ALTS: {format_with_emoji(alts_val, c['total_change'])} (Calc)\n"
    else:
        output += "🌍 Total: ⚠️ Error (TradingView Blocked)\n"
        output += "🔵 Total ALTS: ⚠️ Waiting for Data\n"

    # TVL
    if tvl_val:
        output += f"🔒 TVL: {format_with_emoji(tvl_val, tvl_pct)} (Src: {tvl_src})\n"
    else:
        output += f"🔒 TVL: ⚠️ Error\n"

    output += "\n**Crypto Dominance:**\n"
    if c['btc_dom']:
        output += f"🟠 BTC: `{c['btc_dom']:.2f}%` (Src: TradingView)\n"
        output += f"🟢 USDT: `{c['usdt_dom']:.2f}%` (Src: TradingView)\n\n"
    else:
        output += "🟠 BTC: ⚠️ Error\n🟢 USDT: ⚠️ Error\n\n"

    # --- TRADITIONAL SECTION ---
    output += "**Traditional Markets:**\n"
    if sp_val: 
        output += f"{format_with_emoji(sp_val, sp_pct).split(' (')[0] + f' ({sp_pct:+.2f}%)'} S&P 500 (Src: {sp_src})\n"
    else: 
        output += "⚠️ S&P 500: Failed to Fetch\n"

    if ndq_val: 
        output += f"{format_with_emoji(ndq_val, ndq_pct).split(' (')[0] + f' ({ndq_pct:+.2f}%)'} NASDAQ (Src: {ndq_src})"
    else: 
        output += "⚠️ NASDAQ: Failed to Fetch"

    return output

# --- HANDLERS ---
async def market_cmd(u: Update, c: ContextTypes.DEFAULT_TYPE):
    msg = await c.bot.send_message(chat_id=u.effective_chat.id, text="🔄 Fetching from TradingView...")
    await c.bot.edit_message_text(chat_id=u.effective_chat.id, message_id=msg.message_id, text=generate_report(), parse_mode=constants.ParseMode.MARKDOWN)

async def auto_post(c: ContextTypes.DEFAULT_TYPE):
    await c.bot.send_message(chat_id=c.job.chat_id, text=generate_report(), parse_mode=constants.ParseMode.MARKDOWN)

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
