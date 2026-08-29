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

# New modular engines
from market_data_engine import MarketDataEngine
from feature_engine import FeatureEngine
from strategy_engine import StrategyEngine
from risk_engine import RiskEngine
from signal_database import SignalDatabase
from outcome_engine import OutcomeEngine

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
market_data_eng = MarketDataEngine(angel)
signal_db = SignalDatabase()

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
            
            # Only trigger suggestions if Swing Strength Score is >= 70
            if score >= 70:
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
                
            if score >= 70:
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
    # 1. Download Nifty 50 for relative strength calculation
    nifty_df = None
    try:
        print("Downloading Nifty 50 index data for relative strength context...")
        nifty_df = await run_in_threadpool(yf.download, "^NSEI", period="1y", interval="1d", progress=False)
    except Exception as e:
        print(f"Failed to fetch Nifty data: {e}")

    # 2. Download daily market data for watchlist
    data = await market_data_eng.get_daily_data(WATCHLIST, force_refresh=force_refresh, feed=feed)
    if data is None or data.empty:
        raise HTTPException(status_code=500, detail="Failed to fetch market data.")

    bullish_candidates = []
    
    # 3. Analyze each constituent
    for original_symbol in WATCHLIST:
        ticker = f"{original_symbol}.NS"
        try:
            if isinstance(data.columns, pd.MultiIndex):
                if ticker not in data.columns.levels[0]:
                    continue
                df = data[ticker].dropna()
            else:
                continue
        except Exception:
            continue

        if len(df) < 30:
            continue

        # Format and calculate features
        df = df.reset_index()
        date_col = 'Date' if 'Date' in df.columns else df.columns[0]
        df['timestamp'] = df[date_col].astype(str)
        df.columns = [col.lower() for col in df.columns]

        df_features = FeatureEngine.calculate_features(df, nifty_df)
        if df_features.empty or len(df_features) < 2:
            continue

        latest = df_features.iloc[-1].to_dict()
        prev = df_features.iloc[-2].to_dict()

        # Evaluate strategy triggers
        strategy_triggered = StrategyEngine.evaluate_strategies(latest, prev)
        if not strategy_triggered:
            continue

        # Calculate Technical Score (Max 100)
        close_price = float(latest['close'])
        ema_50 = float(latest.get('ema_50', close_price))
        ema_200 = float(latest.get('ema_200', close_price))
        volume = float(latest.get('volume', 1.0))
        volume_avg_20 = float(latest.get('volume_avg_20', 1.0))
        rsi = float(latest.get('rsi', 50.0))
        macd_hist = float(latest.get('macd_hist', 0.0))
        prev_macd_hist = float(prev.get('macd_hist', 0.0))
        adx = float(latest.get('adx', 25.0))
        bb_width = float(latest.get('bb_width', 0.0))

        tech_score = 0
        # A. Trend Alignment (Max 25 pts)
        if close_price > ema_50 and ema_50 > ema_200:
            tech_score += 25
        elif close_price > ema_200:
            tech_score += 15
        elif abs(close_price - ema_50) / ema_50 < 0.02:
            tech_score += 20
            
        # B. Volume Expansion (Max 20 pts)
        rel_vol = volume / volume_avg_20 if volume_avg_20 > 0 else 1.0
        if rel_vol > 2.0:
            tech_score += 20
        elif rel_vol > 1.2:
            tech_score += 12
        elif rel_vol > 0.8:
            tech_score += 6
            
        # C. Momentum Confirmation (Max 20 pts)
        momentum_pts = 0
        if 45 <= rsi <= 68:
            momentum_pts += 10
        elif rsi < 38:
            momentum_pts += 10
        if macd_hist > prev_macd_hist:
            momentum_pts += 10
        elif macd_hist > 0:
            momentum_pts += 5
        tech_score += momentum_pts
            
        # D. Pattern/Strategy Type (Max 20 pts)
        if "Breakout" in strategy_triggered or "Momentum" in strategy_triggered:
            tech_score += 20
        else:
            tech_score += 15
            
        # E. Volatility Breakout (Max 15 pts)
        vol_pts = 0
        if adx > 22:
            vol_pts += 8
        if bb_width > 0 and bb_width < 0.06:
            vol_pts += 7
        elif bb_width > 0.12:
            vol_pts += 3
        tech_score += vol_pts

        # Filter out setups with technical score < 60
        if tech_score < 60:
            continue

        # Get local support/resistance for risk engine
        sr_levels = QuantitativeEngine.detect_support_resistance(df)
        supports = sr_levels.get("supports", [])
        resistances = sr_levels.get("resistances", [])
        atr_val = float(latest.get('atr', close_price * 0.02))

        # Risk Calculation
        trade_setup = RiskEngine.calculate_trade_setup(close_price, atr_val, supports, resistances)

        # AI sentiment ranking using NVIDIA Sentinel
        live_headlines = await run_in_threadpool(get_live_news_headlines, original_symbol)
        sentiment_report = await sentinel.analyze_sentiment(original_symbol, live_headlines)
        validated = sentinel.validate_signal("BUY", sentiment_report)

        ai_sentiment = sentiment_report.get("sentiment", "NEUTRAL")
        ai_reason = sentiment_report.get("reasoning", "")
        
        # Calculate AI Score
        confidence = float(sentiment_report.get("confidence", 0.5))
        if ai_sentiment == "POSITIVE":
            ai_score = int(50 + 50 * confidence)
        elif ai_sentiment == "NEGATIVE":
            ai_score = int(50 - 50 * confidence)
        else:
            ai_score = 50

        final_score = int(0.7 * tech_score + 0.3 * ai_score)

        candidate = {
            "symbol": original_symbol,
            "strategy": strategy_triggered,
            "entry_price": trade_setup["entry_price"],
            "stop_loss": trade_setup["stop_loss"],
            "target_price": trade_setup["target_price"],
            "rr_ratio": trade_setup["rr_ratio"],
            "position_size": trade_setup["position_size"],
            "total_investment": trade_setup["total_investment"],
            "technical_score": tech_score,
            "ai_score": ai_score,
            "final_score": final_score,
            "ai_sentiment": ai_sentiment,
            "ai_reason": ai_reason,
            "status": "APPROVED" if validated else "BLOCKED_BY_RISK"
        }

        # Log recommendation to Signal Database
        sig_id = signal_db.add_signal(candidate)
        if sig_id:
            candidate["signal_id"] = sig_id
            bullish_candidates.append(candidate)

    # 4. Trigger Outcome Engine to evaluate and update open signals
    await OutcomeEngine.evaluate_open_signals(signal_db)

    # Maintain compatibility with scan history JSON
    compat_bullish = []
    for c in bullish_candidates:
        compat_bullish.append({
            "symbol": c["symbol"],
            "close_price": c["entry_price"],
            "target_price": c["target_price"],
            "stop_loss": c["stop_loss"],
            "potential_return": f"+{round(((c['target_price']-c['entry_price'])/c['entry_price'])*100, 1)}%",
            "rsi": rsi,
            "setup_trigger": f"{c['strategy']} (Score: {c['technical_score']})",
            "accuracy_score": c["final_score"],
            "ai_sentiment": c["ai_sentiment"],
            "ai_reason": c["ai_reason"],
            "status": c["status"]
        })

    result = {
        "total_scanned": len(WATCHLIST),
        "bullish_count": len(compat_bullish),
        "bearish_count": 0,
        "bullish_candidates": compat_bullish,
        "bearish_candidates": []
    }
    save_scan_to_history(result)

    return result

@app.get("/history")
async def get_history():
    all_signals = signal_db.get_all_signals()
    flattened_history = []
    
    for s in all_signals:
        flattened_history.append({
            "symbol": s["symbol"],
            "scan_date": s["timestamp"][:16].replace("T", " "),
            "type": "BUY",
            "entry_price": s["entry_price"],
            "target_price": s["target_price"],
            "stop_loss": s["stop_loss"],
            "rsi": 50.0, # fallback
            "setup_trigger": f"{s['strategy']} (Final Score: {s['final_score']})",
            "outcome": s["outcome"]
        })
        
    # Sort history (latest scan date first)
    flattened_history = sorted(flattened_history, key=lambda x: x['scan_date'], reverse=True)
    return {"history": flattened_history}

@app.get("/performance")
async def get_performance():
    signals = signal_db.get_all_signals()
    total = len(signals)
    if total == 0:
        return {
            "total_signals": 0,
            "targets_hit": 0,
            "stop_loss_hit": 0,
            "expired": 0,
            "ambiguous": 0,
            "open": 0,
            "win_rate": 0.0,
            "by_strategy": {},
            "by_ai_score": {},
            "stock_success": {}
        }

    achieved = sum(1 for s in signals if s["outcome"] == "ACHIEVED")
    failed = sum(1 for s in signals if s["outcome"] == "FAILED")
    expired = sum(1 for s in signals if s["outcome"] == "EXPIRED")
    ambiguous = sum(1 for s in signals if s["outcome"] == "AMBIGUOUS")
    open_count = sum(1 for s in signals if s["outcome"] == "OPEN")

    closed = achieved + failed
    win_rate = round((achieved / closed * 100), 1) if closed > 0 else 0.0

    # Group by strategy
    strategies = {}
    for s in signals:
        strat = s["strategy"]
        if strat not in strategies:
            strategies[strat] = {"total": 0, "win": 0, "loss": 0}
        strategies[strat]["total"] += 1
        if s["outcome"] == "ACHIEVED":
            strategies[strat]["win"] += 1
        elif s["outcome"] == "FAILED":
            strategies[strat]["loss"] += 1

    strategy_stats = {}
    for strat, data in strategies.items():
        closed_s = data["win"] + data["loss"]
        wr = round((data["win"] / closed_s * 100), 1) if closed_s > 0 else 0.0
        strategy_stats[strat] = f"{wr}% (Win: {data['win']}/{data['total']})"

    # Group by AI score range
    ai_groups = {"90-100": {"win": 0, "closed": 0}, "80-89": {"win": 0, "closed": 0}, "70-79": {"win": 0, "closed": 0}, "60-69": {"win": 0, "closed": 0}, "Below 60": {"win": 0, "closed": 0}}
    for s in signals:
        ai_score = s["ai_score"]
        outcome = s["outcome"]
        
        if ai_score >= 90:
            group = "90-100"
        elif ai_score >= 80:
            group = "80-89"
        elif ai_score >= 70:
            group = "70-79"
        elif ai_score >= 60:
            group = "60-69"
        else:
            group = "Below 60"
            
        if outcome in ["ACHIEVED", "FAILED"]:
            ai_groups[group]["closed"] += 1
            if outcome == "ACHIEVED":
                ai_groups[group]["win"] += 1

    ai_score_stats = {}
    for group, data in ai_groups.items():
        wr = round((data["win"] / data["closed"] * 100), 1) if data["closed"] > 0 else 0.0
        ai_score_stats[group] = f"{wr}% ({data['win']}/{data['closed']} closed)"

    # Stock-specific success rates
    stocks = {}
    for s in signals:
        sym = s["symbol"]
        if sym not in stocks:
            stocks[sym] = {"win": 0, "closed": 0}
        if s["outcome"] in ["ACHIEVED", "FAILED"]:
            stocks[sym]["closed"] += 1
            if s["outcome"] == "ACHIEVED":
                stocks[sym]["win"] += 1

    stock_success = {}
    for sym, data in stocks.items():
        if data["closed"] > 0:
            wr = round((data["win"] / data["closed"] * 100), 1)
            stock_success[sym] = f"{wr}% ({data['win']}/{data['closed']} trades)"

    return {
        "total_signals": total,
        "targets_hit": achieved,
        "stop_loss_hit": failed,
        "expired": expired,
        "ambiguous": ambiguous,
        "open": open_count,
        "win_rate": win_rate,
        "by_strategy": strategy_stats,
        "by_ai_score": ai_score_stats,
        "stock_success": stock_success
    }

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
