import logging
import requests
import random
import cloudscraper
import yfinance as yf
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
def format_with_emoji(value, change_pct=0):
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

def get_tv_batch_data():
    """
    WORKAROUND #1: Direct Batch Scanner API via Cloudscraper
    Fetches ALL crypto data in 1 single request to avoid rate limits.
    """
    try:
        scraper = cloudscraper.create_scraper() # Simulates a real browser
        url = "https://scanner.tradingview.com/crypto/scan"
        
        # We ask for all 4 symbols in one go
        payload = {
            "symbols": {
                "tickers": ["CRYPTOCAP:TOTAL", "CRYPTOCAP:BTC.D", "CRYPTOCAP:USDT.D", "CRYPTOCAP:ETH.D"],
                "query": { "types": [] }
            },
            "columns": ["close", "open", "volume"]
        }
        
        # Crucial Headers to look like a real user
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.tradingview.com/",
            "Origin": "https://www.tradingview.com",
            "Content-Type": "application/x-www-form-urlencoded"
        }

        resp = scraper.post(url, json=payload, headers=headers, timeout=10)
        
        if resp.status_code != 200:
            logging.error(f"Scanner Batch Failed: {resp.status_code}")
            return None

        # Parse the 'd' array from response
        # The order matches our tickers list above
        data = resp.json()['data']
        
        results = {}
        tickers = ["TOTAL", "BTC.D", "USDT.D", "ETH.D"]
        
        for i, ticker in enumerate(tickers):
            # d format: [close, open, volume]
            vals = data[i]['d']
            current = vals[0]
            open_p = vals[1]
            vol = vals[2]
            
            change = 0
            if open_p and open_p != 0:
                change = ((current - open_p) / open_p) * 100
                
            results[ticker] = {'val': current, 'change': change, 'vol': vol}
            
        return results

    except Exception as e:
        logging.error(f"Batch Error: {e}")
        return None

def get_tv_lib_fallback(symbol):
    """
    WORKAROUND #2: TradingView-TA Library (Fallback)
    """
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
        
        change = 0
        if open_p and open_p != 0:
            change = ((current - open_p) / open_p) * 100
            
        return {'val': current, 'change': change, 'vol': vol}
    except:
        return None

def get_crypto_data_aggregated():
    # Try Method 1: Cloudscraper Batch (Best for avoiding blocks)
    batch = get_tv_batch_data()
    
    if batch:
        return {
            'source': 'TradingView(Scanner)',
            'total_cap': batch['TOTAL']['val'],
            'total_change': batch['TOTAL']['change'],
            'total_vol': batch['TOTAL']['vol'],
            'btc_dom': batch['BTC.D']['val'],
            'usdt_dom': batch['USDT.D']['val'],
            'eth_dom': batch['ETH.D']['val'] # Used for calc
        }
        
    # Try Method 2: Library (One by one)
    logging.info("Falling back to Library...")
    total = get_tv_lib_fallback("TOTAL")
    if total:
        btc = get_tv_lib_fallback("BTC.D")
        usdt = get_tv_lib_fallback("USDT.D")
        eth = get_tv_lib_fallback("ETH.D")
        
        return {
            'source': 'TradingView(Lib)',
            'total_cap': total['val'],
            'total_change': total['change'],
            'total_vol': total['vol'],
            'btc_dom': btc['val'] if btc else 0,
            'usdt_dom': usdt['val'] if usdt else 0,
            'eth_dom': eth['val'] if eth else 0
        }
        
    return None

def get_tvl_data():
    try:
        # User-Agent prevents 403 blocks from DefiLlama
        h = {'User-Agent': 'Mozilla/5.0'}
        r = requests.get("https://api.llama.fi/v2/historicalChainTvl", headers=h, timeout=10)
        d = r.json()
        curr = d[-1]['tvl']
        prev = d[-2]['tvl']
        change = ((curr - prev)/prev)*100
        return curr, change, "DeFiLlama"
    except:
        return None, None, "Error"

def get_stock_data(ticker):
    try:
        # Direct Yahoo API (Workaround for yfinance blocks)
        h = {'User-Agent': 'Mozilla/5.0'}
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=2d"
        r = requests.get(url, headers=h, timeout=5)
        d = r.json()['chart']['result'][0]
        quotes = d['indicators']['quote'][0]['close']
        
        # Get last valid price
        valid = [x for x in quotes if x is not None]
        if len(valid) < 2: return None, None, "NoData"
        
        curr = valid[-1]
        prev = valid[-2]
        change = ((curr - prev)/prev)*100
        return curr, change, "Yahoo(API)"
    except:
        return None, None, "Failed"

# --- REPORT GENERATOR ---
def generate_report():
    c = get_crypto_data_aggregated()
    tvl_val, tvl_pct, tvl_src = get_tvl_data()
    sp_val, sp_pct, sp_src = get_stock_data("^GSPC")
    ndq_val, ndq_pct, ndq_src = get_stock_data("^IXIC")

    output = "📊 **MARKET SNAPSHOT**\n\n"
    
    # --- CRYPTO SECTION ---
    output += "**Crypto Market Cap:**\n"
    
    if c:
        src = c['source']
        output += f"🌍 Total: {format_with_emoji(c['total_cap'], c['total_change'])} (Src: {src})\n"
        
        # Volume
        if c['total_vol'] and c['total_vol'] > 0:
             # Sanity check: if volume > 1B, format as Billions
             if c['total_vol'] > 1_000_000_000:
                 output += f"📊 Vol: ${c['total_vol']/1_000_000_000:.2f}B (Src: {src})\n"
             else:
                 output += f"📊 Vol: {c['total_vol']:,.0f} (Src: {src})\n"
        else:
             output += f"📊 Vol: N/A\n"
             
        # Alts Calc
        if c['btc_dom'] and c['eth_dom']:
            alts_val = c['total_cap'] * (1 - (c['btc_dom']/100) - (c['eth_dom']/100))
            output += f"🔵 Total ALTS: {format_with_emoji(alts_val, c['total_change'])} (Calc)\n"
    else:
        output += "🌍 Total: ⚠️ Error (All Workarounds Failed)\n"
        output += "📊 Vol: ⚠️ Error\n"
        output += "🔵 Total ALTS: ⚠️ Waiting for Data\n"

    # TVL
    if tvl_val:
        output += f"🔒 TVL: {format_with_emoji(tvl_val, tvl_pct)} (Src: {tvl_src})\n"
    else:
        output += f"🔒 TVL: ⚠️ Error\n"

    output += "\n**Crypto Dominance:**\n"
    if c and c['btc_dom']:
        output += f"🟠 BTC: `{c['btc_dom']:.2f}%` (Src: {c['source']})\n"
        output += f"🟢 USDT: `{c['usdt_dom']:.2f}%` (Src: {c['source']})\n\n"
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
    msg = await c.bot.send_message(chat_id=u.effective_chat.id, text="🔄 Fetching (Cloudscraper Active)...")
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
