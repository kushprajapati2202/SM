import os
import json
import datetime
import httpx
import pyotp
import pandas as pd
from typing import Optional, Dict

class AngelConnector:
    def __init__(self):
        self.client_id = os.getenv("ANGEL_ONE_CLIENT_ID")
        self.password = os.getenv("ANGEL_ONE_PASSWORD")
        self.api_key = os.getenv("ANGEL_ONE_API_KEY")
        self.totp_key = os.getenv("ANGEL_ONE_TOTP_KEY")
        
        self.jwt_token = None
        self.feed_token = None
        self.headers = {}
        
        # Read-only configuration. Disallow any order placement or portfolio tracking endpoints.
        self._disallowed_endpoints = ["/order/", "/portfolio/", "/trade/", "/position"]
        
        self.symbol_mapping_file = "angel_symbols.json"
        self.symbol_map = {}
        self._load_symbol_map()

    def _load_symbol_map(self):
        # Default static mapping for common watchlist constituents to avoid downloading the database initially
        self.symbol_map = {
            "ADANIENT": "25", "ADANIPORTS": "15083", "APOLLOHOSP": "157", "ASIANPAINT": "236", "AXISBANK": "5900",
            "BAJAJ-AUTO": "16669", "BAJFINANCE": "317", "BAJAJFINSV": "16675", "BEL": "359", "BHARTIARTL": "10604",
            "BPCL": "526", "CIPLA": "694", "COALINDIA": "20374", "DRREDDY": "881", "EICHERMOT": "910",
            "GRASIM": "1232", "HCLTECH": "7229", "HDFCBANK": "1333", "HDFCLIFE": "467", "HEROMOTOCO": "1340",
            "HINDALCO": "1363", "HINDUNILVR": "1330", "ICICIBANK": "4963", "INDUSINDBK": "5258", "INFY": "1594",
            "ITC": "1660", "JSWSTEEL": "1172", "KOTAKBANK": "1922", "LT": "11483", "M&M": "2031",
            "MARUTI": "10940", "NESTLEIND": "17963", "NTPC": "11630", "ONGC": "2475", "POWERGRID": "14977",
            "RELIANCE": "2885", "SBILIFE": "21808", "SBIN": "3045", "SUNPHARMA": "3351", "TATACONSUM": "13611",
            "TATAMOTORS": "3456", "TATASTEEL": "3499", "TCS": "11536", "TECHM": "13538", "TITAN": "3506",
            "ULTRACEMCO": "11532", "WIPRO": "3787", "SHRIRAMFIN": "10447", "TRENT": "1964", "JIOFIN": "14299"
        }
        if os.path.exists(self.symbol_mapping_file):
            try:
                with open(self.symbol_mapping_file, "r") as f:
                    self.symbol_map.update(json.load(f))
            except Exception as e:
                print(f"Failed to load symbol mapping file: {e}")

    def save_symbol_map(self):
        try:
            with open(self.symbol_mapping_file, "w") as f:
                json.dump(self.symbol_map, f, indent=2)
        except Exception as e:
            print(f"Failed to save symbol mapping file: {e}")

    def is_configured(self) -> bool:
        return bool(self.client_id and self.password and self.api_key and self.totp_key)

    def _verify_url_safety(self, url: str):
        for path in self._disallowed_endpoints:
            if path in url:
                raise PermissionError(f"Action Blocked: Call to trading/portfolio endpoint '{url}' is restricted by API security policy.")

    async def login(self) -> bool:
        if not self.is_configured():
            print("Angel One credentials incomplete in .env.")
            return False

        # Generate TOTP Code
        try:
            secret = self.totp_key.replace(" ", "")
            totp = pyotp.TOTP(secret)
            totp_code = totp.now()
        except Exception as e:
            print(f"Failed to generate TOTP: {e}")
            return False

        url = "https://apiconnect.angelone.in/rest/auth/angelbroking/user/v1/loginByPassword"
        self._verify_url_safety(url)
        
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-UserType": "USER",
            "X-SourceID": "WEB",
            "X-ClientLocalIP": "192.168.1.1",
            "X-ClientPublicIP": "1.1.1.1",
            "X-MACAddress": "00-00-00-00-00-00",
            "X-PrivateKey": self.api_key
        }

        payload = {
            "clientcode": self.client_id,
            "password": self.password,
            "totp": totp_code
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                if response.status_code == 200:
                    res_json = response.json()
                    if res_json.get("status") is True:
                        data = res_json.get("data", {})
                        self.jwt_token = data.get("jwtToken")
                        self.feed_token = data.get("feedToken")
                        self.headers = {
                            "Authorization": f"Bearer {self.jwt_token}",
                            "Content-Type": "application/json",
                            "Accept": "application/json",
                            "X-UserType": "USER",
                            "X-SourceID": "WEB",
                            "X-ClientLocalIP": "192.168.1.1",
                            "X-ClientPublicIP": "1.1.1.1",
                            "X-MACAddress": "00-00-00-00-00-00",
                            "X-PrivateKey": self.api_key
                        }
                        print("Angel One login successful.")
                        return True
                    else:
                        print(f"Angel One login failed: {res_json.get('message')}")
                else:
                    print(f"Angel One login HTTP status error: {response.status_code}")
        except Exception as e:
            print(f"Exception during Angel One login: {e}")
        return False

    async def get_historical_candles(self, symbol: str, interval: str = "ONE_DAY", days_back: int = 365) -> Optional[pd.DataFrame]:
        # Log in if headers are empty
        if not self.headers:
            success = await self.login()
            if not success:
                return None

        # Resolve Angel token
        token = self.symbol_map.get(symbol)
        if not token:
            # Try loading/downloading database
            await self.download_and_sync_symbols()
            token = self.symbol_map.get(symbol)
            if not token:
                print(f"Symbol {symbol} not found in Angel One database.")
                return None

        url = "https://apiconnect.angelone.in/rest/secure/angelbroking/historical/v1/getCandleData"
        self._verify_url_safety(url)

        end_date = datetime.datetime.now()
        start_date = end_date - datetime.timedelta(days=days_back)
        
        payload = {
            "exchange": "NSE",
            "symboltoken": token,
            "interval": interval,
            "fromdate": start_date.strftime("%Y-%m-%d 09:15"),
            "todate": end_date.strftime("%Y-%m-%d 15:30")
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, headers=self.headers, json=payload)
                if response.status_code == 200:
                    res_json = response.json()
                    if res_json.get("status") is True:
                        candles_data = res_json.get("data", [])
                        if candles_data:
                            # Parse candles
                            df = pd.DataFrame(candles_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                            # Ensure columns are numeric
                            for col in ['open', 'high', 'low', 'close', 'volume']:
                                df[col] = pd.to_numeric(df[col], errors='coerce')
                            return df
                    else:
                        # If session expired, try re-logging once
                        if res_json.get("errorcode") in ["AG8001", "AB1009", "AB2000"]:
                            print("Angel One session expired. Re-authenticating...")
                            self.headers = {}
                            return await self.get_historical_candles(symbol, interval, days_back)
                        print(f"Failed to fetch historical data: {res_json.get('message')}")
                else:
                    print(f"Historical data endpoint HTTP status error: {response.status_code}")
        except Exception as e:
            print(f"Exception during fetching historical candles: {e}")
        return None

    async def download_and_sync_symbols(self):
        url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPISymbolTokendatabase.json"
        print("Downloading Angel One Symbol Database...")
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url)
                if response.status_code == 200:
                    data = response.json()
                    updated = False
                    for item in data:
                        # Match NSE Equities (usually ends with -EQ)
                        symbol_name = item.get("symbol", "")
                        if symbol_name.endswith("-EQ") and item.get("exch_seg") == "NSE":
                            name = item.get("name", "")
                            token = item.get("token", "")
                            if name and token:
                                self.symbol_map[name] = token
                                updated = True
                    if updated:
                        self.save_symbol_map()
                        print("Angel One Symbol database synchronized successfully.")
        except Exception as e:
            print(f"Failed to sync symbols: {e}")
