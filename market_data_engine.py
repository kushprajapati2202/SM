import os
import pandas as pd
import yfinance as yf
from typing import Optional
from angel_connector import AngelConnector

class MarketDataEngine:
    def __init__(self, angel_client: Optional[AngelConnector] = None):
        self.angel = angel_client or AngelConnector()
        self.cache_file = "yf_cache.pkl"

    def get_writable_path(self, filename: str) -> str:
        if os.environ.get("VERCEL") or not os.access(".", os.W_OK):
            return os.path.join("/tmp", filename)
        return filename

    async def get_daily_data(self, watchlist: list, force_refresh: bool = False, feed: str = "auto") -> Optional[pd.DataFrame]:
        cache_path = self.get_writable_path(self.cache_file)
        if not force_refresh and os.path.exists(cache_path):
            try:
                import datetime
                mtime = datetime.datetime.fromtimestamp(os.path.getmtime(cache_path))
                if (datetime.datetime.now() - mtime).total_seconds() < 3600:
                    df = pd.read_pickle(cache_path)
                    if not df.empty:
                        return df
            except Exception as e:
                print(f"Failed to read cache: {e}")

        use_angel = (feed == "angel") or (feed == "auto" and self.angel.is_configured())
        data = None
        if use_angel:
            try:
                import asyncio
                print("Fetching data from Angel One SmartAPI...")
                async def fetch_ticker_data(symbol: str):
                    df_ticker = await self.angel.get_historical_candles(symbol, interval="ONE_DAY", days_back=365)
                    return symbol, df_ticker
                
                tasks = [fetch_ticker_data(s) for s in watchlist]
                results = await asyncio.gather(*tasks)
                
                dfs = []
                keys = []
                for sym, df_ticker in results:
                    if df_ticker is not None and not df_ticker.empty:
                        df_ticker = df_ticker.rename(columns={
                            'open': 'Open',
                            'high': 'High',
                            'low': 'Low',
                            'close': 'Close',
                            'volume': 'Volume'
                        })
                        df_ticker['Date'] = pd.to_datetime(df_ticker['timestamp'])
                        df_ticker = df_ticker.set_index('Date')
                        df_ticker = df_ticker[['Open', 'High', 'Low', 'Close', 'Volume']]
                        dfs.append(df_ticker)
                        keys.append(f"{sym}.NS")
                
                if dfs:
                    data = pd.concat(dfs, axis=1, keys=keys)
            except Exception as e:
                print(f"Angel One data fetch failed: {e}. Falling back to Yahoo Finance...")

        if data is None:
            try:
                print("Fetching data from Yahoo Finance...")
                tickers_str = " ".join([f"{t}.NS" for t in watchlist])
                import datetime
                start_dt = (datetime.datetime.now() - datetime.timedelta(days=365)).strftime("%Y-%m-%d")
                data = yf.download(tickers_str, start=start_dt, progress=False)
            except Exception as e:
                print(f"Failed to fetch market data from YFinance: {e}")
                return None

        if data is not None and not data.empty:
            try:
                data.to_pickle(cache_path)
            except Exception as e:
                print(f"Failed to save cache: {e}")
        
        return data
