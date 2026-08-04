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

def get_cached_market_data() -> Optional[pd.DataFrame]:
    if os.path.exists(CACHE_FILE):
        try:
            mtime = datetime.datetime.fromtimestamp(os.path.getmtime(CACHE_FILE))
            now = datetime.datetime.now()
            # Cache is valid for 1 hour
            if (now - mtime).total_seconds() < 3600:
                df = pd.read_pickle(CACHE_FILE)
                if not df.empty:
                    print("Serving market data from cache...")
                    return df
        except Exception as e:
            print(f"Failed to read cache: {e}")
    return None

def save_market_data_to_cache(df: pd.DataFrame):
    try:
        df.to_pickle(CACHE_FILE)
        print("Market data successfully cached.")
    except Exception as e:
        print(f"Failed to save cache: {e}")

def save_scan_to_history(result: dict):
    history_file = "scan_history.json"
    
    history_data = []
    if os.path.exists(history_file):
        try:
            with open(history_file, "r") as f:
                history_data = json.load(f)
                if not isinstance(history_data, list):
                    history_data = []
        except Exception:
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
        with open(history_file, "w") as f:
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

        # If a strategy triggered, score it using the AI Confidence matrix
        if strategy_triggered:
            score = 0
            
            # 1. Trend (EMA alignment) - 30%
            if close_price > ema_50 and ema_50 > ema_200:
                score += 30
            elif close_price > ema_200:
                score += 15
                
            # 2. Volume - 20%
            if volume > 2.0 * volume_avg_20:
                score += 20
            elif volume > volume_avg_20:
                score += 10
                
            # 3. Momentum (RSI + MACD) - 20%
            if (rsi > 45 or rsi < 38) and macd_hist > prev_macd_hist:
                score += 20
            elif (rsi > 45 or rsi < 38) or macd_hist > prev_macd_hist:
                score += 10
                
            # 4. Pattern Quality - 40%
            score += 40  # Triggered an elite pattern
            
            # 5. Volatility (ATR/ADX) - 10%
            if adx > 25:
                score += 10
                
            # Only trigger suggestions if AI confidence is >= 60
            if score >= 60:
                target_price = round(close_price * 1.050, 2)  # +5% target
                stop_loss = round(close_price * 0.965, 2)     # -3.5% stop loss

                bullish_candidates.append({
                    "symbol": original_symbol,
                    "close_price": round(close_price, 2),
                    "target_price": target_price,
                    "stop_loss": stop_loss,
                    "potential_return": "+5.0%",
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
            
            # 1. Trend (EMA alignment) - 30%
            if close_price < ema_50 and ema_50 < ema_200:
                score += 30
            elif close_price < ema_200:
                score += 15
                
            # 2. Volume - 20%
            if volume > 2.0 * volume_avg_20:
                score += 20
            elif volume > volume_avg_20:
                score += 10
                
            # 3. Momentum (RSI + MACD) - 20%
            if (rsi < 55 or rsi > 62) and macd_hist < prev_macd_hist:
                score += 20
            elif (rsi < 55 or rsi > 62) or macd_hist < prev_macd_hist:
                score += 10
                
            # 4. Pattern Quality - 40%
            score += 40
            
            # 5. Volatility (ATR/ADX) - 10%
            if adx > 25:
                score += 10
                
            if score >= 60:
                target_price = round(close_price * 0.950, 2)  # -5% target
                stop_loss = round(close_price * 1.035, 2)     # +3.5% stop loss

                bearish_candidates.append({
                    "symbol": original_symbol,
                    "close_price": round(close_price, 2),
                    "target_price": target_price,
                    "stop_loss": stop_loss,
                    "potential_return": "+5.0% (Short)",
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
async def scan_market(force_refresh: bool = False):
    # Append suffix for Yahoo Finance
    tickers = [f"{t}.NS" for t in WATCHLIST]
    tickers_str = " ".join(tickers)

    data = None
    if not force_refresh:
        data = await run_in_threadpool(get_cached_market_data)

    if data is None:
        if angel.is_configured():
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
                print(f"Angel One data fetch failed: {e}. Falling back to Yahoo Finance...")
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
    if not os.path.exists(history_file):
        return {"history": []}
        
    try:
        with open(history_file, "r") as f:
            scans = json.load(f)
    except Exception:
        return {"history": []}
        
    updated_scans = False
    flattened_history = []
    
    for scan in scans:
        timestamp_str = scan.get("timestamp")
        scan_date = datetime.datetime.fromisoformat(timestamp_str)
        
        # Bullish
        for c in scan.get("bullish_candidates", []):
            symbol = c["symbol"]
            ticker = f"{symbol}.NS"
            outcome = c.get("outcome", "ACTIVE")
            
            if outcome == "ACTIVE":
                start_date_str = scan_date.strftime("%Y-%m-%d")
                end_date = datetime.datetime.now()
                
                try:
                    df = yf.download(ticker, start=start_date_str, end=(end_date + datetime.timedelta(days=1)).strftime("%Y-%m-%d"), progress=False)
                    if not df.empty:
                        if isinstance(df.columns, pd.MultiIndex):
                            df.columns = df.columns.get_level_values(0)
                        df = df.dropna()
                        # Evaluate on up to 10 trading days
                        df_window = df.head(10)
                        
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
                            if len(df) >= 10:
                                outcome = "EXPIRED"
                            else:
                                outcome = "ACTIVE"
                                
                        if outcome != "ACTIVE":
                            c["outcome"] = outcome
                            updated_scans = True
                except Exception as e:
                    print(f"Failed to evaluate history for {symbol}: {str(e)}")
                    
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
            ticker = f"{symbol}.NS"
            outcome = c.get("outcome", "ACTIVE")
            
            if outcome == "ACTIVE":
                start_date_str = scan_date.strftime("%Y-%m-%d")
                end_date = datetime.datetime.now()
                
                try:
                    df = yf.download(ticker, start=start_date_str, end=(end_date + datetime.timedelta(days=1)).strftime("%Y-%m-%d"), progress=False)
                    if not df.empty:
                        if isinstance(df.columns, pd.MultiIndex):
                            df.columns = df.columns.get_level_values(0)
                        df = df.dropna()
                        df_window = df.head(10)
                        
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
                            if len(df) >= 10:
                                outcome = "EXPIRED"
                            else:
                                outcome = "ACTIVE"
                                
                        if outcome != "ACTIVE":
                            c["outcome"] = outcome
                            updated_scans = True
                except Exception as e:
                    print(f"Failed to evaluate history for {symbol}: {str(e)}")
                    
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
            with open(history_file, "w") as f:
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
    if not angel.is_configured():
        return {"status": "DISCONNECTED", "feed": "YAHOO_FINANCE", "details": "Credentials not configured in .env."}
    
    is_logged_in = bool(angel.headers)
    if not is_logged_in:
        # Try authenticating
        is_logged_in = await angel.login()
        
    if is_logged_in:
        return {"status": "CONNECTED", "feed": "ANGEL_ONE", "details": f"Active Client ID: {angel.client_id}"}
    else:
        return {"status": "ERROR", "feed": "YAHOO_FINANCE", "details": "Authentication failed. Falling back to Yahoo Finance."}
