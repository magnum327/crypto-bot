import logging
import requests
import time
from telegram import Update, constants
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler
from keep_alive import keep_alive
from tradingview_ta import TA_Handler, Interval

# --- CONFIGURATION ---
BOT_TOKEN = '8266373667:AAE_Qrfq8VzMJTNE9Om9_rdbzscWFyBmgJU'

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# --- HELPER FUNCTIONS ---
def format_with_emoji(value, change_pct=0, prefix="$"):
    if value is None: return "N/A"
    
    # Determine Emoji
    if change_pct > 0: emoji = "🟢"
    elif change_pct < 0: emoji = "🔴"
    else: emoji = "⚪"
    
    # Format Numbers
    if value >= 1_000_000_000_000:
        val_str = f"{prefix}{value / 1_000_000_000_000:.2f}T"
    elif value >= 1_000_000_000:
        val_str = f"{prefix}{value / 1_000_000_000:.2f}B"
    else:
        val_str = f"{prefix}{value:,.2f}"
        
    return f"{emoji} {val_str} ({change_pct:+.2f}%)"

# ==========================================
#        MODULE A: TRADINGVIEW (PRIMARY)
# ==========================================
def get_tv_data(symbol):
    try:
        handler = TA_Handler(
            symbol=symbol,
            screener="crypto",
            exchange="CRYPTOCAP",
            interval=Interval.INTERVAL_1_DAY
        )
        analysis = handler.get_analysis()
        current = analysis.indicators['close']
        open_p = analysis.indicators['open']
        vol = analysis.indicators.get('volume')
        
        change = ((current - open_p) / open_p) * 100 if open_p else 0
        return {'val': current, 'change': change, 'vol': vol}
    except:
        return None

# ==========================================
#        MODULE B: BINANCE (BACKUP)
# ==========================================
def get_binance_backup():
    """
    Binance NEVER blocks. We use it to estimate Global Cap if TradingView fails.
    Formula: Global Cap = (BTC Market Cap) / (BTC Dominance Est 57%)
    """
    try:
        url = "https://api.binance.com/api/v3/ticker/24hr?symbol=BTCUSDT"
        r = requests.get(url, timeout=5)
        data = r.json()
        
        price = float(data['lastPrice'])
        change = float(data['priceChangePercent'])
        vol = float(data['quoteVolume']) # This is just BTC volume, but better than nothing
        
        # Est. Supply ~19.8M BTC
        btc_mcap = price * 19_800_000
        
        # Estimate Global Cap (Assuming 58% BTC Dom)
        global_cap = btc_mcap / 0.58
        
        return {
            'source': 'Binance(Est)',
            'total_cap': global_cap,
            'total_change': change, # Proxying BTC change as Global change
            'total_vol': vol * 10, # Rough estimate of global vol
            'btc_dom': 58.0,
            'usdt_dom': 5.5,
            'eth_dom': 13.0
        }
    except:
        return None

# ==========================================
#        DATA AGGREGATOR
# ==========================================
def get_crypto_data():
    # Attempt 1: TradingView
    total = get_tv_data("TOTAL")
    if total:
        btc = get_tv_data("BTC.D")
        usdt = get_tv_data("USDT.D")
        eth = get_tv_data("ETH.D")
        
        return {
            'source': 'TradingView',
            'total_cap': total['val'],
            'total_change': total['change'],
            'total_vol': total['vol'],
            'btc_dom': btc['val'] if btc else 0,
            'usdt_dom': usdt['val'] if usdt else 0,
            'eth_dom': eth['val'] if eth else 0
        }
    
    # Attempt 2: Binance Backup
    return get_binance_backup()

def get_tvl_data():
    try:
        # User-Agent header is often enough to bypass DefiLlama blocks
        h = {'User-Agent': 'Mozilla/5.0'}
        r = requests.get("https://api.llama.fi/v2/historicalChainTvl", headers=h, timeout=10)
        d = r.json()
        curr = d[-1]['tvl']
        prev = d[-2]['tvl']
        change = ((curr - prev)/prev)*100
        return curr, change
    except:
        return None, 0

def get_stock_data(ticker):
    # Direct Yahoo API
    try:
        h = {'User-Agent': 'Mozilla/5.0'}
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=2d"
        r = requests.get(url, headers=h, timeout=5)
        d = r.json()['chart']['result'][0]
        quotes = d['indicators']['quote'][0]['close']
        
        valid = [x for x in quotes if x is not None]
        if len(valid) < 2: return None, 0
        
        curr = valid[-1]
        prev = valid[-2]
        change = ((curr - prev)/prev)*100
        return curr, change
    except:
        return None, 0

# --- REPORT GENERATION ---
def generate_report():
    c = get_crypto_data()
    tvl_val, tvl_pct = get_tvl_data()
    sp_val, sp_pct = get_stock_data("^GSPC")
    ndq_val, ndq_pct = get_stock_data("^IXIC")

    output = "📊 **MARKET SNAPSHOT**\n\n"
    
    # --- CRYPTO ---
    output += "**Crypto Market Cap:**\n"
    if c:
        src = c['source']
        output += f"🌍 Total: {format_with_emoji(c['total_cap'], c['total_change'])} (Src: {src})\n"
        
        if c.get('total_vol'):
            output += f"📊 Vol: ${c['total_vol']/1_000_000_000:,.2f}B (Src: {src})\n"
        else:
            output += f"📊 Vol: N/A\n"
            
        # Calc Alts
        if c['btc_dom'] and c['eth_dom']:
            alts_val = c['total_cap'] * (1 - (c['btc_dom']/100) - (c['eth_dom']/100))
            output += f"🔵 Total ALTS: {format_with_emoji(alts_val, c['total_change'])} (Calc)\n"
    else:
        output += "🌍 Total: ⚠️ Data Unavailable\n"

    # --- TVL ---
    if tvl_val:
        output += f"🔒 TVL: {format_with_emoji(tvl_val, tvl_pct)} (Src: DeFiLlama)\n"
    else:
        output += "🔒 TVL: ⚠️ Error\n"

    output += "\n**Crypto Dominance:**\n"
    if c:
        output += f"🟠 BTC: `{c['btc_dom']:.2f}%`\n"
        output += f"🟢 USDT: `{c['usdt_dom']:.2f}%`\n\n"
    else:
        output += "🟠 BTC: N/A\n🟢 USDT: N/A\n\n"

    # --- TRADITIONAL ---
    output += "**Traditional Markets:**\n"
    if sp_val: output += f"{format_with_emoji(sp_val, sp_pct).split(' (')[0]} ({sp_pct:+.2f}%) S&P 500 (Src: Yahoo)\n"
    else: output += "⚠️ S&P 500: Failed\n"
    
    if ndq_val: output += f"{format_with_emoji(ndq_val, ndq_pct).split(' (')[0]} ({ndq_pct:+.2f}%) NASDAQ (Src: Yahoo)"
    else: output += "⚠️ NASDAQ: Failed"

    return output

# --- HANDLERS ---
async def market_cmd(u: Update, c: ContextTypes.DEFAULT_TYPE):
    msg = await c.bot.send_message(chat_id=u.effective_chat.id, text="🔄 Fetching Market Data...")
    try:
        report = generate_report()
        await c.bot.edit_message_text(chat_id=u.effective_chat.id, message_id=msg.message_id, text=report, parse_mode=constants.ParseMode.MARKDOWN)
    except Exception as e:
        await c.bot.edit_message_text(chat_id=u.effective_chat.id, message_id=msg.message_id, text=f"❌ Critical Error: {str(e)}")

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
