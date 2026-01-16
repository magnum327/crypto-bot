import requests
import json
import time

def get_crypto_prices(limit=10):
    """
    Fetches the top 'limit' cryptocurrencies from CoinCap API.
    Source: https://docs.coincap.io/
    """
    url = "https://api.coincap.io/v2/assets"
    
    params = {
        'limit': limit
    }
    
    try:
        # CoinCap does not strictly require headers, but adding a User-Agent 
        # is a best practice to avoid being flagged as a bot.
        headers = {
            'User-Agent': 'Mozilla/5.0 (python-requests/2.28.0)'
        }

        response = requests.get(url, params=params, headers=headers)
        
        # Check if the request was successful
        if response.status_code != 200:
            print(f"⚠️ API Error: Status Code {response.status_code}")
            print(f"Reason: {response.text}")
            return None

        # Parse JSON
        data = response.json()
        
        # CoinCap wraps the actual list inside a 'data' key
        assets = data.get('data', [])
        
        results = []
        for asset in assets:
            name = asset.get('name')
            symbol = asset.get('symbol')
            # Prices come as strings, convert to float for formatting
            price = float(asset.get('priceUsd', 0))
            change_24h = float(asset.get('changePercent24Hr', 0))
            
            results.append({
                "name": name,
                "symbol": symbol,
                "price": price,
                "change_24h": change_24h
            })
            
        return results

    except requests.exceptions.JSONDecodeError:
        print("❌ Error: The API returned non-JSON data (likely a block or HTML page).")
    except Exception as e:
        print(f"❌ An unexpected error occurred: {e}")

# --- Execute ---
if __name__ == "__main__":
    print("Fetching latest crypto data from CoinCap...")
    prices = get_crypto_prices(5)
    
    if prices:
        print(f"{'Name':<15} {'Symbol':<10} {'Price (USD)':<15} {'24h Change':<10}")
        print("-" * 55)
        for coin in prices:
            # Color code the 24h change (Green for positive, Red for negative)
            # Note: ANSI colors might not work in all terminals
            arrow = "▲" if coin['change_24h'] > 0 else "▼"
            print(f"{coin['name']:<15} {coin['symbol']:<10} ${coin['price']:<14.2f} {arrow} {coin['change_24h']:.2f}%")
