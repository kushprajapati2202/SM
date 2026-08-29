import os
import json
import uuid
import datetime
from typing import List, Dict, Any, Optional

class SignalDatabase:
    def __init__(self, filepath: str = "suggestions_db.json"):
        self.filepath = self.get_writable_path(filepath)
        self._load_db()

    def get_writable_path(self, filename: str) -> str:
        if os.environ.get("VERCEL") or not os.access(".", os.W_OK):
            return os.path.join("/tmp", filename)
        return filename

    def _load_db(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r") as f:
                    self.data = json.load(f)
            except Exception as e:
                print(f"Error loading signal DB: {e}")
                self.data = []
        else:
            self.data = []

    def _save_db(self):
        try:
            with open(self.filepath, "w") as f:
                json.dump(self.data, f, indent=2)
        except Exception as e:
            print(f"Error saving signal DB: {e}")

    def add_signal(self, signal_dict: Dict[str, Any]) -> str:
        """
        Adds a new recommendation and returns a unique SIG-YYYYMMDD-XXXX signal ID.
        """
        today_str = datetime.datetime.now().strftime("%Y%m%d")
        
        # Calculate next serial number for today
        today_signals = [s for s in self.data if s.get("signal_id", "").startswith(f"SIG-{today_str}")]
        serial = len(today_signals) + 1
        
        signal_id = f"SIG-{today_str}-{serial:04d}"
        
        new_signal = {
            "signal_id": signal_id,
            "timestamp": datetime.datetime.now().isoformat(),
            "symbol": signal_dict.get("symbol"),
            "strategy": signal_dict.get("strategy"),
            "entry_price": float(signal_dict.get("entry_price")),
            "stop_loss": float(signal_dict.get("stop_loss")),
            "target_price": float(signal_dict.get("target_price")),
            "rr_ratio": float(signal_dict.get("rr_ratio", 2.0)),
            "technical_score": int(signal_dict.get("technical_score", 0)),
            "ai_score": int(signal_dict.get("ai_score", 0)),
            "final_score": int(signal_dict.get("final_score", 0)),
            "ai_sentiment": signal_dict.get("ai_sentiment", "NEUTRAL"),
            "ai_reason": signal_dict.get("ai_reason", ""),
            "status": signal_dict.get("status", "APPROVED"),
            "outcome": "OPEN",
            "outcome_timestamp": None,
            "days_held": 0
        }
        
        # Avoid duplicate open signals for the same stock/strategy on the same day
        duplicate = False
        for s in self.data:
            if (s["symbol"] == new_signal["symbol"] and 
                s["strategy"] == new_signal["strategy"] and 
                s["outcome"] == "OPEN"):
                duplicate = True
                break
                
        if not duplicate:
            self.data.append(new_signal)
            self._save_db()
            return signal_id
        return ""

    def get_open_signals(self) -> List[Dict[str, Any]]:
        return [s for s in self.data if s.get("outcome") == "OPEN"]

    def update_outcome(self, signal_id: str, outcome: str, outcome_date: str, days_held: int):
        for s in self.data:
            if s.get("signal_id") == signal_id:
                s["outcome"] = outcome
                s["outcome_timestamp"] = outcome_date
                s["days_held"] = days_held
                break
        self._save_db()

    def get_all_signals(self) -> List[Dict[str, Any]]:
        return self.data
