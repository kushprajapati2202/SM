import os
import json
import uuid
import datetime
import asyncio
from dotenv import load_dotenv
load_dotenv()  # Load .env file variables

import yfinance as yf
import pandas as pd
import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Dict, Any, Optional

from quant_engine import QuantitativeEngine
from pattern_detector import PatternDetector
from ai_sentinel import AISentinel
from angel_connector import AngelConnector

from fastapi.middleware.cors import CORSMiddleware
from fastapi.concurrency import run_in_threadpool

app = FastAPI(
    title="Indian Stock Market Swing Scanner",
    description="Scans top NSE F&O stocks for Bullish (Buy) and Bearish (Short Sell) swing setups.",
    version="1.1.0"
)

# Enable CORS for all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

sentinel = AISentinel()
angel = AngelConnector()

# Predefined list of high-liquidity NSE stocks (Full Nifty 50 constituents)
WATCHLIST = [
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK",
    "BAJAJ-AUTO", "BAJFINANCE", "BAJAJFINSV", "BEL", "BHARTIARTL",
    "BPCL", "CIPLA", "COALINDIA", "DRREDDY", "EICHERMOT",
    "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE", "HEROMOTOCO",
    "HINDALCO", "HINDUNILVR", "ICICIBANK", "INDUSINDBK", "INFY",
    "ITC", "JSWSTEEL", "KOTAKBANK", "LT", "M&M",
    "MARUTI", "NESTLEIND", "NTPC", "ONGC", "POWERGRID",
    "RELIANCE", "SBILIFE", "SBIN", "SUNPHARMA", "TATACONSUM",
    "TATAMOTORS", "TATASTEEL", "TCS", "TECHM", "TITAN",
    "ULTRACEMCO", "WIPRO", "SHRIRAMFIN", "TRENT", "JIOFIN"
]

CACHE_FILE = "yf_cache.pkl"

def get_writable_path(filename: str) -> str:
    # If running in Vercel or local directory is read-only, use /tmp
    if os.environ.get("VERCEL") or not os.access(".", os.W_OK):
        return os.path.join("/tmp", filename)
    return filename

def load_json_file(filename: str, default_val: Any) -> Any:
    # 1. Try writable path
    writable_path = get_writable_path(filename)
    if os.path.exists(writable_path):
        try:
            with open(writable_path, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"Failed to read from writable path {writable_path}: {e}")
            
    # 2. Try current directory
    if os.path.exists(filename):
        try:
            with open(filename, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"Failed to read from local fallback {filename}: {e}")
            
    return default_val

def get_cached_market_data() -> Optional[pd.DataFrame]:
    cache_path = get_writable_path(CACHE_FILE)
    # Check if writable cache exists
    if os.path.exists(cache_path):
        try:
            mtime = datetime.datetime.fromtimestamp(os.path.getmtime(cache_path))
            now = datetime.datetime.now()
            # Cache is valid for 1 hour
            if (now - mtime).total_seconds() < 3600:
                df = pd.read_pickle(cache_path)
                if not df.empty:
                    print("Serving market data from cache...")
                    return df
        except Exception as e:
            print(f"Failed to read cache from {cache_path}: {e}")
            
    # Also check local file as fallback
    if cache_path != CACHE_FILE and os.path.exists(CACHE_FILE):
        try:
            mtime = datetime.datetime.fromtimestamp(os.path.getmtime(CACHE_FILE))
            now = datetime.datetime.now()
            if (now - mtime).total_seconds() < 3600:
                df = pd.read_pickle(CACHE_FILE)
                if not df.empty:
                    print("Serving market data from local cache fallback...")
                    return df
        except Exception as e:
            print(f"Failed to read local cache fallback: {e}")
            
    return None

def save_market_data_to_cache(df: pd.DataFrame):
    try:
        cache_path = get_writable_path(CACHE_FILE)
        df.to_pickle(cache_path)
        print(f"Market data successfully cached to {cache_path}.")
    except Exception as e:
        print(f"Failed to save cache: {e}")

def save_scan_to_history(result: dict):
    history_file = "scan_history.json"
    history_data = load_json_file(history_file, [])
    if not isinstance(history_data, list):
        history_data = []
            
    today_str = datetime.datetime.now().strftime("%Y-%m-%d")
    
    # Check if there is already a scan record today
    today_record = None
    for item in history_data:
        if item.get("timestamp", "").startswith(today_str):
            today_record = item
            break
            
    if today_record:
        # Merge bullish candidates, avoiding symbol duplicates
        existing_bullish = {c["symbol"]: c for c in today_record.get("bullish_candidates", [])}
        for c in result.get("bullish_candidates", []):
            existing_bullish[c["symbol"]] = c  # Update with latest scan calculations
        today_record["bullish_candidates"] = list(existing_bullish.values())
        today_record["bullish_count"] = len(today_record["bullish_candidates"])
        
        # Merge bearish candidates, avoiding symbol duplicates
        existing_bearish = {c["symbol"]: c for c in today_record.get("bearish_candidates", [])}
        for c in result.get("bearish_candidates", []):
            existing_bearish[c["symbol"]] = c  # Update with latest scan calculations
        today_record["bearish_candidates"] = list(existing_bearish.values())
        today_record["bearish_count"] = len(today_record["bearish_candidates"])
        
        today_record["total_scanned"] = result.get("total_scanned", 30)
    else:
        # No record today, append a new one
        record = {
            "scan_id": str(uuid.uuid4()),
            "timestamp": datetime.datetime.now().isoformat(),
            "total_scanned": result.get("total_scanned", 0),
            "bullish_count": result.get("bullish_count", 0),
            "bearish_count": result.get("bearish_count", 0),
            "bullish_candidates": result.get("bullish_candidates", []),
            "bearish_candidates": result.get("bearish_candidates", [])
        }
        history_data.append(record)
    
    try:
        writable_path = get_writable_path(history_file)
        with open(writable_path, "w") as f:
            json.dump(history_data, f, indent=2)
    except Exception as e:
        print(f"Failed to write history file: {str(e)}")

def get_live_news_headlines(symbol: str) -> list:
    try:
        ticker = yf.Ticker(f"{symbol}.NS")
        news = ticker.news
        if news:
            # Extract headlines
            headlines = [n.get("title", "") for n in news if n.get("title")]
            if headlines:
                return headlines[:4]
    except Exception as e:
        print(f"Failed to fetch live news for {symbol}: {str(e)}")
    
    # Fallback to general message if news is empty or fails
    return [
        f"{symbol} is showing positive breakout indicators based on moving average crossovers.",
        f"Technical momentum and relative volume for {symbol} has exceeded average levels."
    ]

def calculate_technical_candidates(data: pd.DataFrame) -> tuple:
    bullish_candidates = []
    bearish_candidates = []

    for original_symbol in WATCHLIST:
        ticker = f"{original_symbol}.NS"
        
        try:
            if ticker in data.columns.levels[0]:
                df = data[ticker].dropna()
            else:
                continue
        except Exception:
            continue

        if len(df) < 30:
            continue

        # Format df index
        df = df.reset_index()
        date_col = 'Date' if 'Date' in df.columns else df.columns[0]
        df['timestamp'] = df[date_col].astype(str)
        df.columns = [col.lower() for col in df.columns]

        # Calculate indicators & patterns
        df_indicators = QuantitativeEngine.calculate_indicators(df)
        df_patterns = PatternDetector.detect_candlesticks(df_indicators)
        double_patterns = PatternDetector.detect_double_tops_bottoms(df)
        support_resistance = QuantitativeEngine.detect_support_resistance(df)

        # Get latest data point
        latest = df_patterns.iloc[-1]
        close_price = float(latest['close'])
        
        def safe_float(val, default=0.0):
            if val is None or pd.isna(val):
                return default
            return float(val)

        # Get indicators from latest row
        ema_50 = safe_float(latest.get('ema_50'), close_price)
        ema_200 = safe_float(latest.get('ema_200'), close_price)
        bb_lower = safe_float(latest.get('bb_lower'), close_price)
        bb_upper = safe_float(latest.get('bb_upper'), close_price)
        volume = safe_float(latest.get('volume'), 1.0)
        volume_avg_20 = safe_float(latest.get('volume_avg_20'), 1.0)
        adx = safe_float(latest.get('adx'), 25.0)
        high_20 = safe_float(latest.get('high_20'), close_price)
        low_20 = safe_float(latest.get('low_20'), close_price)
        macd_hist = safe_float(latest.get('macd_hist'), 0.0)
        prev_macd_hist = safe_float(df_patterns.iloc[-2].get('macd_hist') if len(df_patterns) > 1 else 0.0, 0.0)
        rsi = safe_float(latest.get('rsi'), 50.0)
        
        # Bullish Patterns
        is_bullish_engulfing = bool(latest.get('pattern_bullish_engulfing', False))
        is_hammer = bool(latest.get('pattern_hammer', False))
        db_indices = double_patterns.get("double_bottoms", [])
        is_double_bottom = any(idx >= (len(df) - 15) for idx in db_indices)
        is_cup_and_handle = PatternDetector.detect_cup_and_handle(df_patterns)
        is_bull_flag = PatternDetector.detect_bull_flag(df_patterns)
        
        # ----------------------------------------------------
        # A. Bullish Swing Setup Identification (Buy)
        # ----------------------------------------------------
        strategy_triggered = None
        
        # Strategy 1: EMA 50 Pullback
        if (close_price > ema_200 and ema_50 > ema_200 and 
            abs(close_price - ema_50) / ema_50 <= 0.015 and 
            (is_bullish_engulfing or is_hammer) and 
            rsi > 45 and volume > volume_avg_20 and adx > 25):
            strategy_triggered = "Strategy 1: EMA 50 Pullback Reversal"

        # Strategy 2: Volume Breakout
        elif (close_price >= high_20 and volume > 2.0 * volume_avg_20 and 
              rsi >= 55 and rsi <= 70 and macd_hist > 0):
            strategy_triggered = "Strategy 2: Volume Breakout"

        # Strategy 3: Cup & Handle Breakout
        elif is_cup_and_handle:
            strategy_triggered = "Strategy 3: Cup & Handle Breakout"

        # Strategy 4: Double Bottom + Volume Confirmation
        elif is_double_bottom and volume > volume_avg_20 and macd_hist > prev_macd_hist:
            strategy_triggered = "Strategy 4: Double Bottom Rebound"

        # Strategy 5: Bull Flag Breakout
        elif is_bull_flag:
            strategy_triggered = "Strategy 5: Bull Flag Breakout"

        # Strategy 6: Oversold RSI Rebound
        elif rsi < 38:
            strategy_triggered = "Strategy 6: Oversold RSI Rebound"

        # Strategy 7: Bollinger Band Lower Support
        elif close_price <= bb_lower * 1.015 and rsi < 45:
            strategy_triggered = "Strategy 7: Bollinger Band Lower Support"

        # Strategy 8: MACD Bullish Crossover
        elif macd_hist > 0 and prev_macd_hist <= 0 and rsi < 55:
            strategy_triggered = "Strategy 8: MACD Bullish Crossover"

        # Strategy 9: EMA Support Bounce
        elif (close_price > ema_200 and 
              abs(latest['low'] - ema_50) / ema_50 <= 0.015 and 
              (is_bullish_engulfing or is_hammer)):
            strategy_triggered = "Strategy 9: EMA Support Bounce"

        # If a strategy triggered, score it using the dynamic Multi-Factor Scoring Matrix
        if strategy_triggered:
            score = 0
            
            # 1. Trend Alignment (Max 25 pts)
            if close_price > ema_50 and ema_50 > ema_200:
                score += 25
            elif close_price > ema_200:
                score += 15
            elif abs(close_price - ema_50) / ema_50 < 0.02:
                score += 20
                
            # 2. Volume Expansion & Price Confirmation (Max 20 pts)
            rel_vol = volume / volume_avg_20 if volume_avg_20 > 0 else 1.0
            if rel_vol > 2.0:
                score += 20
            elif rel_vol > 1.2:
                score += 12
            elif rel_vol > 0.8:
                score += 6
                
            # 3. Momentum Confirmation (Max 20 pts)
            momentum_pts = 0
            if 45 <= rsi <= 68:
                momentum_pts += 10
            elif rsi < 38:
                momentum_pts += 10
                
            if macd_hist > prev_macd_hist:
                momentum_pts += 10
            elif macd_hist > 0:
                momentum_pts += 5
            score += momentum_pts
                
            # 4. Pattern Strength (Max 20 pts)
            if any(p in strategy_triggered for p in ["Cup & Handle", "Bull Flag", "Double Bottom"]):
                score += 20
            elif any(p in strategy_triggered for p in ["Engulfing", "Hammer", "Crossover"]):
                score += 15
            else:
                score += 10
                
            # 5. Volatility / Squeeze Breakout (Max 15 pts)
            bb_width = safe_float(latest.get('bb_width'), 0.0)
            vol_pts = 0
            if adx > 22:
                vol_pts += 8
            if bb_width > 0 and bb_width < 0.06:
                vol_pts += 7
            elif bb_width > 0.12:
                vol_pts += 3
            score += vol_pts
            
            # Only trigger suggestions if Swing Strength Score is >= 60
            if score >= 60:
                # Dynamic ATR & Support/Resistance exit/stop loss calculation
                atr_val = safe_float(latest.get('atr'), close_price * 0.02)
                if atr_val <= 0:
                    atr_val = close_price * 0.02
                    
                target_sl_atr = close_price - 1.5 * atr_val
                supports_below_close = [s for s in support_resistance.get("supports", []) if s < close_price]
                if supports_below_close:
                    nearest_support = max(supports_below_close)
                    if 0.94 * close_price <= nearest_support <= 0.985 * close_price:
                        stop_loss = nearest_support
                    else:
                        stop_loss = target_sl_atr
                else:
                    stop_loss = target_sl_atr
                stop_loss = round(stop_loss, 2)
                
                # Clamp SL between -1.5% and -5%
                min_sl = round(close_price * 0.985, 2)
                max_sl = round(close_price * 0.95, 2)
                if stop_loss > min_sl:
                    stop_loss = min_sl
                elif stop_loss < max_sl:
                    stop_loss = max_sl
                    
                # Dynamic Target (Target Risk-Reward of ~1.8x, aligned with Resistance)
                risk = close_price - stop_loss
                target_tp_atr = close_price + 1.8 * risk
                resistances_above_close = [r for r in support_resistance.get("resistances", []) if r > close_price]
                if resistances_above_close:
                    nearest_resistance = min(resistances_above_close)
                    if 1.03 * close_price <= nearest_resistance <= 1.08 * close_price:
                        target_price = nearest_resistance
                    else:
                        target_price = target_tp_atr
                else:
                    target_price = target_tp_atr
                target_price = round(target_price, 2)
                
                # Clamp Target between +3.5% and +8.5%
                min_target = round(close_price * 1.035, 2)
                max_target = round(close_price * 1.085, 2)
                if target_price < min_target:
                    target_price = min_target
                elif target_price > max_target:
                    target_price = max_target
                    
                potential_return_pct = round(((target_price - close_price) / close_price) * 100, 1)

                bullish_candidates.append({
                    "symbol": original_symbol,
                    "close_price": round(close_price, 2),
                    "target_price": target_price,
                    "stop_loss": stop_loss,
                    "potential_return": f"+{potential_return_pct}%",
                    "rsi": round(rsi, 1),
                    "setup_trigger": f"{strategy_triggered} (ADX: {round(adx,1)}, Rel Vol: {round(volume/volume_avg_20,1)}x)",
                    "accuracy_score": score,
                    "ema_50": round(ema_50, 2),
                    "ema_200": round(ema_200, 2),
                    "bb_lower": round(bb_lower, 2),
                    "bb_upper": round(bb_upper, 2),
                    "supports": [round(s, 2) for s in support_resistance.get("supports", [])[-3:]],
                    "resistances": [round(r, 2) for r in support_resistance.get("resistances", [])[-3:]],
                    "headlines": []
                })

        # ----------------------------------------------------
        # B. Bearish Swing Setup Identification (Short Sell)
        # ----------------------------------------------------
        is_overbought = rsi > 62
        is_bearish_engulfing = bool(latest.get('pattern_bearish_engulfing', False))
        is_shooting_star = bool(latest.get('pattern_shooting_star', False))
        dt_indices = double_patterns.get("double_tops", [])
        is_double_top = any(idx >= (len(df) - 15) for idx in dt_indices)

        bearish_strategy = None
        if (close_price < ema_200 and rsi > 55 and 
            (is_bearish_engulfing or is_shooting_star) and adx > 25):
            bearish_strategy = "Bearish Pullback Rejection"
        elif close_price <= low_20 and volume > 1.5 * volume_avg_20 and rsi < 45:
            bearish_strategy = "Volume Breakdown"
        elif is_double_top and volume > volume_avg_20 and macd_hist < prev_macd_hist:
            bearish_strategy = "Double Top Rebound"
        elif rsi > 62:
            bearish_strategy = "Strategy 4: Overbought RSI Pullback"
        elif close_price >= bb_upper * 0.985 and rsi > 55:
            bearish_strategy = "Strategy 5: Bollinger Band Upper Rejection"
        elif macd_hist < 0 and prev_macd_hist >= 0:
            bearish_strategy = "Strategy 6: MACD Bearish Crossover"

        if bearish_strategy:
            score = 0
            
            # 1. Trend Alignment (Max 25 pts)
            if close_price < ema_50 and ema_50 < ema_200:
                score += 25
            elif close_price < ema_200:
                score += 15
            elif abs(close_price - ema_50) / ema_50 < 0.02:
                score += 20
                
            # 2. Volume Expansion (Max 20 pts)
            rel_vol = volume / volume_avg_20 if volume_avg_20 > 0 else 1.0
            if rel_vol > 2.0:
                score += 20
            elif rel_vol > 1.2:
                score += 12
            elif rel_vol > 0.8:
                score += 6
                
            # 3. Momentum (Max 20 pts)
            momentum_pts = 0
            if 35 <= rsi <= 55:
                momentum_pts += 10
            elif rsi > 62:
                momentum_pts += 10
                
            if macd_hist < prev_macd_hist:
                momentum_pts += 10
            elif macd_hist < 0:
                momentum_pts += 5
            score += momentum_pts
                
            # 4. Pattern Strength (Max 20 pts)
            if any(p in bearish_strategy for p in ["Double Top"]):
                score += 20
            elif any(p in bearish_strategy for p in ["Engulfing", "Shooting Star", "Crossover"]):
                score += 15
            else:
                score += 10
                
            # 5. Volatility (Max 15 pts)
            bb_width = safe_float(latest.get('bb_width'), 0.0)
            vol_pts = 0
            if adx > 22:
                vol_pts += 8
            if bb_width > 0 and bb_width < 0.06:
                vol_pts += 7
            score += vol_pts
                
            if score >= 60:
                # Dynamic ATR & Support/Resistance stop loss calculation
                atr_val = safe_float(latest.get('atr'), close_price * 0.02)
                if atr_val <= 0:
                    atr_val = close_price * 0.02
                    
                target_sl_atr = close_price + 1.5 * atr_val
                resistances_above_close = [r for r in support_resistance.get("resistances", []) if r > close_price]
                if resistances_above_close:
                    nearest_resistance = min(resistances_above_close)
                    if 1.015 * close_price <= nearest_resistance <= 1.05 * close_price:
                        stop_loss = nearest_resistance
                    else:
                        stop_loss = target_sl_atr
                else:
                    stop_loss = target_sl_atr
                stop_loss = round(stop_loss, 2)
                
                # Clamp SL between +1.5% and +5%
                min_sl = round(close_price * 1.015, 2)
                max_sl = round(close_price * 1.05, 2)
                if stop_loss < min_sl:
                    stop_loss = min_sl
                elif stop_loss > max_sl:
                    stop_loss = max_sl
                    
                # Dynamic Target (Target Risk-Reward of ~1.8x, aligned with Support)
                risk = stop_loss - close_price
                target_tp_atr = close_price - 1.8 * risk
                supports_below_close = [s for s in support_resistance.get("supports", []) if s < close_price]
                if supports_below_close:
                    nearest_support = max(supports_below_close)
                    if 0.92 * close_price <= nearest_support <= 0.965 * close_price:
                        target_price = nearest_support
                    else:
                        target_price = target_tp_atr
                else:
                    target_price = target_tp_atr
                target_price = round(target_price, 2)
                
                # Clamp Target between -3.5% and -8.5%
                min_target = round(close_price * 0.965, 2)
                max_target = round(close_price * 0.915, 2)
                if target_price > min_target:
                    target_price = min_target
                elif target_price < max_target:
                    target_price = max_target
                    
                potential_return_pct = round(((close_price - target_price) / close_price) * 100, 1)

                bearish_candidates.append({
                    "symbol": original_symbol,
                    "close_price": round(close_price, 2),
                    "target_price": target_price,
                    "stop_loss": stop_loss,
                    "potential_return": f"+{potential_return_pct}% (Short)",
                    "rsi": round(rsi, 1),
                    "setup_trigger": f"{bearish_strategy} (ADX: {round(adx,1)}, Rel Vol: {round(volume/volume_avg_20,1)}x)",
                    "accuracy_score": score,
                    "ema_50": round(ema_50, 2),
                    "ema_200": round(ema_200, 2),
                    "bb_lower": round(bb_lower, 2),
                    "bb_upper": round(bb_upper, 2),
                    "supports": [round(s, 2) for s in support_resistance.get("supports", [])[-3:]],
                    "resistances": [round(r, 2) for r in support_resistance.get("resistances", [])[-3:]],
                    "headlines": []
                })

    return bullish_candidates, bearish_candidates

@app.get("/")
def read_root():
    return FileResponse("static/index.html")

@app.post("/scan")
async def scan_market(force_refresh: bool = False, feed: str = "auto"):
    # Append suffix for Yahoo Finance
    tickers = [f"{t}.NS" for t in WATCHLIST]
    tickers_str = " ".join(tickers)

    data = None
    if not force_refresh:
        data = await run_in_threadpool(get_cached_market_data)

    if data is None:
        use_angel = False
        if feed == "angel":
            use_angel = True
        elif feed == "auto" and angel.is_configured():
            use_angel = True

        if use_angel:
            try:
                print("Fetching data from Angel One SmartAPI...")
                # Download historical data from Angel One in parallel
                async def fetch_ticker_data(symbol: str):
                    df_ticker = await angel.get_historical_candles(symbol, interval="ONE_DAY", days_back=365)
                    return symbol, df_ticker
                
                tasks = [fetch_ticker_data(s) for s in WATCHLIST]
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
                    await run_in_threadpool(save_market_data_to_cache, data)
                else:
                    raise Exception("No data returned from Angel One for watchlist.")
            except Exception as e:
                print(f"Angel One data fetch failed: {e}")
                if feed == "angel":
                    raise HTTPException(
                        status_code=502,
                        detail=f"Angel One SmartAPI failed: {str(e)}"
                    )
                print("Falling back to Yahoo Finance...")
                data = None

        if data is None:
            try:
                # Download historical data (1 year of daily candles to support 200 EMA calculation)
                print("Fetching data from Yahoo Finance...")
                data = await run_in_threadpool(yf.download, tickers_str, period="1y", interval="1d", group_by="ticker", progress=False)
                await run_in_threadpool(save_market_data_to_cache, data)
            except Exception as e:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to fetch market data: {str(e)}"
                )

    # Calculate indicators in threadpool to prevent event loop blocking
    bullish_candidates, bearish_candidates = await run_in_threadpool(calculate_technical_candidates, data)

    # Perform async news/AI sentiment analysis sequentially
    for c in bullish_candidates:
        sym = c["symbol"]
        live_headlines = await run_in_threadpool(get_live_news_headlines, sym)
        c["headlines"] = live_headlines
        sentiment_report = await sentinel.analyze_sentiment(sym, live_headlines)
        validated = sentinel.validate_signal("BUY", sentiment_report)
        c["ai_sentiment"] = sentiment_report.get("sentiment", "NEUTRAL")
        c["ai_reason"] = sentiment_report.get("reasoning", "")
        c["status"] = "APPROVED" if validated else "BLOCKED_BY_RISK"

    for c in bearish_candidates:
        sym = c["symbol"]
        live_headlines = await run_in_threadpool(get_live_news_headlines, sym)
        c["headlines"] = live_headlines
        sentiment_report = await sentinel.analyze_sentiment(sym, live_headlines)
        validated = sentinel.validate_signal("SELL", sentiment_report)
        c["ai_sentiment"] = sentiment_report.get("sentiment", "NEUTRAL")
        c["ai_reason"] = sentiment_report.get("reasoning", "")
        c["status"] = "APPROVED" if validated else "BLOCKED_BY_RISK"

    # Sort candidates by accuracy score descending
    bullish_candidates = sorted(bullish_candidates, key=lambda x: x['accuracy_score'], reverse=True)
    bearish_candidates = sorted(bearish_candidates, key=lambda x: x['accuracy_score'], reverse=True)

    result = {
        "total_scanned": len(WATCHLIST),
        "bullish_count": len(bullish_candidates),
        "bearish_count": len(bearish_candidates),
        "bullish_candidates": bullish_candidates,
        "bearish_candidates": bearish_candidates
    }
    
    save_scan_to_history(result)
    
    return result

@app.get("/history")
async def get_history():
    history_file = "scan_history.json"
    scans = load_json_file(history_file, [])
    if not scans:
        return {"history": []}
        
    updated_scans = False
    flattened_history = []
    
    # 1. Identify all active candidates and find the earliest scan date
    active_tickers = set()
    earliest_date = None
    
    for scan in scans:
        timestamp_str = scan.get("timestamp")
        if not timestamp_str:
            continue
        try:
            scan_date = datetime.datetime.fromisoformat(timestamp_str)
        except Exception:
            continue
            
        for c in scan.get("bullish_candidates", []) + scan.get("bearish_candidates", []):
            if c.get("outcome", "ACTIVE") == "ACTIVE":
                active_tickers.add(c["symbol"])
                if earliest_date is None or scan_date < earliest_date:
                    earliest_date = scan_date
                    
    # 2. Batch download data from Yahoo Finance for all active tickers
    batch_data = {}
    if active_tickers:
        tickers_list = [f"{sym}.NS" for sym in active_tickers]
        start_date_str = earliest_date.strftime("%Y-%m-%d")
        end_date_str = (datetime.datetime.now() + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        
        try:
            print(f"Batch downloading {len(tickers_list)} active tickers from {start_date_str} to {end_date_str}...")
            # Use run_in_threadpool to keep it non-blocking
            df_batch = await run_in_threadpool(
                yf.download,
                tickers_list,
                start=start_date_str,
                end=end_date_str,
                group_by="ticker",
                progress=False
            )
            
            # Process df_batch to make it easy to index per symbol
            if not df_batch.empty:
                for symbol in active_tickers:
                    ticker = f"{symbol}.NS"
                    if len(tickers_list) == 1:
                        if isinstance(df_batch.columns, pd.MultiIndex):
                            ticker_key = df_batch.columns.levels[0][0]
                            df_ticker = df_batch[ticker_key]
                        else:
                            df_ticker = df_batch
                    else:
                        if isinstance(df_batch.columns, pd.MultiIndex) and ticker in df_batch.columns.levels[0]:
                            df_ticker = df_batch[ticker]
                        else:
                            df_ticker = pd.DataFrame()
                            
                    if not df_ticker.empty:
                        df_ticker = df_ticker.dropna()
                        batch_data[symbol] = df_ticker
        except Exception as e:
            print(f"Failed to batch download active tickers: {str(e)}")
            
    # 3. Evaluate outcomes using the downloaded batch data
    for scan in scans:
        timestamp_str = scan.get("timestamp")
        try:
            scan_date = datetime.datetime.fromisoformat(timestamp_str)
        except Exception:
            continue
            
        # Bullish
        for c in scan.get("bullish_candidates", []):
            symbol = c["symbol"]
            outcome = c.get("outcome", "ACTIVE")
            
            if outcome == "ACTIVE" and symbol in batch_data:
                df = batch_data[symbol]
                scan_date_only = scan_date.date()
                df_filtered = df[df.index.date >= scan_date_only]
                
                if not df_filtered.empty:
                    df_window = df_filtered.head(10)
                    target = float(c["target_price"])
                    sl = float(c["stop_loss"])
                    
                    outcome_found = False
                    for idx, row in df_window.iterrows():
                        high = float(row["High"])
                        low = float(row["Low"])
                        
                        if high >= target:
                            outcome = "ACHIEVED"
                            outcome_found = True
                            break
                        elif low <= sl:
                            outcome = "FAILED"
                            outcome_found = True
                            break
                            
                    if not outcome_found:
                        if len(df_filtered) >= 10:
                            outcome = "EXPIRED"
                        else:
                            outcome = "ACTIVE"
                            
                    if outcome != "ACTIVE":
                        c["outcome"] = outcome
                        updated_scans = True
                        
            flattened_history.append({
                "symbol": symbol,
                "scan_date": scan_date.strftime("%Y-%m-%d %H:%M"),
                "type": "BUY",
                "entry_price": c["close_price"],
                "target_price": c["target_price"],
                "stop_loss": c["stop_loss"],
                "rsi": c["rsi"],
                "setup_trigger": c["setup_trigger"],
                "outcome": outcome
            })
            
        # Bearish
        for c in scan.get("bearish_candidates", []):
            symbol = c["symbol"]
            outcome = c.get("outcome", "ACTIVE")
            
            if outcome == "ACTIVE" and symbol in batch_data:
                df = batch_data[symbol]
                scan_date_only = scan_date.date()
                df_filtered = df[df.index.date >= scan_date_only]
                
                if not df_filtered.empty:
                    df_window = df_filtered.head(10)
                    target = float(c["target_price"])
                    sl = float(c["stop_loss"])
                    
                    outcome_found = False
                    for idx, row in df_window.iterrows():
                        high = float(row["High"])
                        low = float(row["Low"])
                        
                        if low <= target:
                            outcome = "ACHIEVED"
                            outcome_found = True
                            break
                        elif high >= sl:
                            outcome = "FAILED"
                            outcome_found = True
                            break
                            
                    if not outcome_found:
                        if len(df_filtered) >= 10:
                            outcome = "EXPIRED"
                        else:
                            outcome = "ACTIVE"
                            
                    if outcome != "ACTIVE":
                        c["outcome"] = outcome
                        updated_scans = True
                        
            flattened_history.append({
                "symbol": symbol,
                "scan_date": scan_date.strftime("%Y-%m-%d %H:%M"),
                "type": "SHORT",
                "entry_price": c["close_price"],
                "target_price": c["target_price"],
                "stop_loss": c["stop_loss"],
                "rsi": c["rsi"],
                "setup_trigger": c["setup_trigger"],
                "outcome": outcome
            })
            
    if updated_scans:
        try:
            writable_path = get_writable_path(history_file)
            with open(writable_path, "w") as f:
                json.dump(scans, f, indent=2)
        except Exception as e:
            print(f"Failed to save history cache: {str(e)}")
            
    # Sort history (latest scan date first)
    flattened_history = sorted(flattened_history, key=lambda x: x['scan_date'], reverse=True)
    return {"history": flattened_history}

class BacktestRequest(BaseModel):
    start_date: str
    end_date: str
    target_pct: float
    stop_loss_pct: float

@app.post("/backtest")
async def run_backtest(req: BacktestRequest):
    from backtest import run_backtest_simulation
    try:
        result = await run_in_threadpool(
            run_backtest_simulation,
            start_date_str=req.start_date,
            end_date_str=req.end_date,
            target_pct=req.target_pct,
            stop_loss_pct=req.stop_loss_pct
        )
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api-status")
async def get_api_status():
    missing = []
    if not angel.client_id:
        missing.append("ANGEL_ONE_CLIENT_ID")
    if not angel.password:
        missing.append("ANGEL_ONE_PASSWORD")
    if not angel.api_key:
        missing.append("ANGEL_ONE_API_KEY")
    if not angel.totp_key:
        missing.append("ANGEL_ONE_TOTP_KEY")

    if missing:
        return {
            "status": "DISCONNECTED",
            "feed": "YAHOO_FINANCE",
            "details": f"Missing: {', '.join(missing)}"
        }
    
    is_logged_in = bool(angel.headers)
    if not is_logged_in:
        # Try authenticating
        is_logged_in = await angel.login()
        
    if is_logged_in:
        return {"status": "CONNECTED", "feed": "ANGEL_ONE", "details": f"Active Client ID: {angel.client_id}"}
    else:
        return {"status": "ERROR", "feed": "YAHOO_FINANCE", "details": "Authentication failed. Falling back to Yahoo Finance."}
