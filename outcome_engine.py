import datetime
import pandas as pd
import yfinance as yf
from typing import List, Dict, Any, Optional
from signal_database import SignalDatabase

class OutcomeEngine:
    @staticmethod
    async def evaluate_open_signals(db: SignalDatabase, max_days: int = 15):
        open_signals = db.get_open_signals()
        if not open_signals:
            return

        symbols = list(set(s["symbol"] for s in open_signals))
        tickers = [f"{sym}.NS" for sym in symbols]
        
        # Download historical data from earliest signal date to today
        earliest_date = datetime.datetime.now()
        for s in open_signals:
            dt = datetime.datetime.fromisoformat(s["timestamp"])
            if dt < earliest_date:
                earliest_date = dt
                
        start_date_str = earliest_date.strftime("%Y-%m-%d")
        
        try:
            print(f"OutcomeEngine downloading history for {len(symbols)} tickers since {start_date_str}...")
            data = yf.download(" ".join(tickers), start=start_date_str, group_by="ticker", progress=False)
        except Exception as e:
            print(f"OutcomeEngine failed to download data: {e}")
            return

        for s in open_signals:
            symbol = s["symbol"]
            ticker = f"{symbol}.NS"
            
            if isinstance(data.columns, pd.MultiIndex):
                if ticker not in data.columns.levels[0]:
                    continue
                df_ticker = data[ticker].dropna()
            else:
                df_ticker = data.dropna()
                
            if df_ticker.empty:
                continue

            # Slice from signal timestamp
            signal_time = datetime.datetime.fromisoformat(s["timestamp"])
            df_after = df_ticker[df_ticker.index.date >= signal_time.date()]
            
            if df_after.empty:
                continue
                
            # Exclude the exact entry signal candle if it triggered post-market (use days after)
            candles_window = df_after.head(max_days + 1)
            
            target = s["target_price"]
            sl = s["stop_loss"]
            
            outcome = "OPEN"
            outcome_date = None
            days_held = 0
            
            # Loop through candles to check triggers
            for idx, (dt, row) in enumerate(candles_window.iterrows()):
                if idx == 0:
                    # Skip signal day if entry was at close
                    continue
                    
                high = float(row["High"])
                low = float(row["Low"])
                
                target_hit = high >= target
                sl_hit = low <= sl
                
                if target_hit and sl_hit:
                    # Same-candle ambiguity!
                    # Mark as AMBIGUOUS as per user requirement
                    outcome = "AMBIGUOUS"
                    outcome_date = dt.strftime("%Y-%m-%d")
                    days_held = idx
                    break
                elif target_hit:
                    outcome = "ACHIEVED"
                    outcome_date = dt.strftime("%Y-%m-%d")
                    days_held = idx
                    break
                elif sl_hit:
                    outcome = "FAILED"
                    outcome_date = dt.strftime("%Y-%m-%d")
                    days_held = idx
                    break
            
            # If no target or SL hit, check expiration
            if outcome == "OPEN" and len(df_after) > max_days:
                outcome = "EXPIRED"
                # Expiration date is the date of the max_days index
                outcome_date = df_after.index[min(max_days, len(df_after) - 1)].strftime("%Y-%m-%d")
                days_held = max_days

            if outcome != "OPEN":
                db.update_outcome(s["signal_id"], outcome, outcome_date, days_held)
                print(f"Signal {s['signal_id']} ({symbol}) evaluated: {outcome} on {outcome_date} after {days_held} days.")
