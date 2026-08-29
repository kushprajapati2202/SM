import pandas as pd
import pandas_ta as ta
import numpy as np
from typing import Optional
from quant_engine import QuantitativeEngine
from pattern_detector import PatternDetector

class FeatureEngine:
    @staticmethod
    def calculate_features(df: pd.DataFrame, nifty_df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
        # First calculate basic indicators
        df = QuantitativeEngine.calculate_indicators(df)
        df = PatternDetector.detect_candlesticks(df)
        
        # Calculate Relative Strength compared to NIFTY 50 index
        if nifty_df is not None and not nifty_df.empty:
            df_temp = df.copy()
            df_temp['date_only'] = pd.to_datetime(df_temp['timestamp']).dt.date
            
            nifty_copy = nifty_df.copy()
            if isinstance(nifty_copy.columns, pd.MultiIndex):
                nifty_copy.columns = nifty_copy.columns.get_level_values(0)
                
            nifty_copy['date_only'] = nifty_copy.index.date
            nifty_close = nifty_copy[['date_only', 'Close']]
            
            # If nifty_close has multiple columns named Close, pick the first one
            if isinstance(nifty_close, pd.DataFrame) and nifty_close.shape[1] > 2:
                nifty_close = nifty_close.iloc[:, :2]
                
            nifty_close.columns = ['date_only', 'nifty_close']
            
            merged = pd.merge(df_temp, nifty_close, on='date_only', how='left')
            
            # Calculate 20-day returns
            merged['stock_ret_20'] = merged['close'].pct_change(20)
            merged['nifty_ret_20'] = merged['nifty_close'].pct_change(20)
            merged['relative_strength_nifty'] = (merged['stock_ret_20'] - merged['nifty_ret_20']) * 100
            
            # Fill NaNs
            merged['relative_strength_nifty'] = merged['relative_strength_nifty'].fillna(0.0)
            
            # Drop temp columns
            merged.drop(columns=['date_only', 'nifty_close', 'stock_ret_20', 'nifty_ret_20'], inplace=True, errors='ignore')
            return merged
        else:
            df['relative_strength_nifty'] = 0.0
            return df
