import asyncio
import json
import ccxt.async_support as ccxt
from dotenv import load_dotenv
import os

async def main():
    load_dotenv()
    exchange = ccxt.binanceusdm({
        'apiKey': os.getenv('BINANCE_API_KEY'),
        'secret': os.getenv('BINANCE_SECRET_KEY'),
        'enableRateLimit': True,
    })
    try:
        balance = await exchange.fetch_balance()
        usdt_bal = balance.get('USDT', {})
        print("USDT Balance keys:", usdt_bal)
        info = balance.get('info', {})
        print("totalWalletBalance:", info.get('totalWalletBalance'))
        print("Info data:", json.dumps(info, indent=2, default=str))
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await exchange.close()

if __name__ == '__main__':
    asyncio.run(main())
