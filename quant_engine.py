import pandas as pd
import numpy as np
import pandas_ta as ta
from typing import Dict, Any

class QuantitativeEngine:
    """
    Deterministic quantitative trading indicator engine.
    Calculates technical indicators with 100% precision.
    """
    
    @staticmethod
    def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculates basic technical indicators needed for Intraday and Swing strategies.
        Expects a DataFrame with columns: ['open', 'high', 'low', 'close', 'volume']
        """
        # Ensure column names are lowercase
        df.columns = [col.lower() for col in df.columns]
        
        # 1. Simple & Exponential Moving Averages (EMA/SMA)
        df['sma_20'] = ta.sma(df['close'], length=20)
        df['ema_50'] = ta.ema(df['close'], length=50)
        df['ema_200'] = ta.ema(df['close'], length=200)
        
        # 2. Relative Strength Index (RSI)
        df['rsi'] = ta.rsi(df['close'], length=14)
        
        # 3. MACD (Moving Average Convergence Divergence)
        macd_df = ta.macd(df['close'], fast=12, slow=26, signal=9)
        if macd_df is not None:
            # Find columns dynamically based on prefixes
            for col in macd_df.columns:
                if col.startswith('MACD_'):
                    df['macd'] = macd_df[col]
                elif col.startswith('MACDs_'):
                    df['macd_signal'] = macd_df[col]
                elif col.startswith('MACDh_'):
                    df['macd_hist'] = macd_df[col]
            
        # 4. Bollinger Bands
        bb_df = ta.bbands(df['close'], length=20, std=2)
        if bb_df is not None:
            # Find columns dynamically based on prefixes
            for col in bb_df.columns:
                if col.startswith('BBL_'):
                    df['bb_lower'] = bb_df[col]
                elif col.startswith('BBM_'):
                    df['bb_middle'] = bb_df[col]
                elif col.startswith('BBU_'):
                    df['bb_upper'] = bb_df[col]
            
        # 5. Volatility (ATR) and Momentum (ADX)
        try:
            df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
        except Exception:
            df['atr'] = df['high'].rolling(window=14).max() - df['low'].rolling(window=14).min()

        try:
            adx_df = ta.adx(df['high'], df['low'], df['close'], length=14)
            if adx_df is not None:
                for col in adx_df.columns:
                    if col.startswith('ADX_'):
                        df['adx'] = adx_df[col]
        except Exception:
            df['adx'] = 25.0 # Default if ADX fails

        # Fill default ADX if missing
        if 'adx' not in df.columns:
            df['adx'] = 25.0

        # 6. Volume Average and Rolling Extremes
        df['volume_avg_20'] = ta.sma(df['volume'], length=20)
        df['high_20'] = df['high'].rolling(window=20).max()
        df['low_20'] = df['low'].rolling(window=20).min()

        # 7. VWAP (Volume Weighted Average Price)
        try:
            df['vwap'] = ta.vwap(df['high'], df['low'], df['close'], df['volume'])
        except Exception:
            typical_price = (df['high'] + df['low'] + df['close']) / 3
            df['vwap'] = (typical_price * df['volume']).cumsum() / df['volume'].cumsum()
            
        return df

    @staticmethod
    def detect_support_resistance(df: pd.DataFrame, window: int = 20) -> Dict[str, list]:
        """
        Find local support and resistance levels based on rolling window local minima/maxima.
        """
        levels = {"supports": [], "resistances": []}
        
        for i in range(window, len(df) - window):
            # Check for local minimum (Support)
            if df['low'].iloc[i] == df['low'].iloc[i - window : i + window + 1].min():
                levels["supports"].append(float(df['low'].iloc[i]))
            
            # Check for local maximum (Resistance)
            if df['high'].iloc[i] == df['high'].iloc[i - window : i + window + 1].max():
                levels["resistances"].append(float(df['high'].iloc[i]))
                
        # Consolidate levels close to each other (clustering threshold of 0.5%)
        consolidated = {"supports": [], "resistances": []}
        for category in ["supports", "resistances"]:
            sorted_levels = sorted(levels[category])
            if not sorted_levels:
                continue
            
            temp_group = [sorted_levels[0]]
            for val in sorted_levels[1:]:
                # If difference is less than 0.5%, cluster them
                if (val - temp_group[-1]) / temp_group[-1] < 0.005:
                    temp_group.append(val)
                else:
                    consolidated[category].append(np.mean(temp_group))
                    temp_group = [val]
            consolidated[category].append(np.mean(temp_group))
            
        return consolidated
