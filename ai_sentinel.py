import os
import httpx
from typing import Dict, Any

class AISentinel:
    """
    AI Sentinel that verifies quantitative signals against fundamental news & sentiment.
    Uses free/low-cost cloud API endpoints (e.g., Groq) to analyze text data.
    """

    def __init__(self, api_key: str = None, model: str = "llama3-8b-8192"):
        # Load API key from environment if not passed explicitly
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        self.model = model
        self.api_url = "https://api.groq.com/openai/v1/chat/completions"

    async def analyze_sentiment(self, symbol: str, news_headlines: list) -> Dict[str, Any]:
        """
        Submits news headlines to the LLM to gauge sentiment.
        Returns a dict: {"sentiment": "POSITIVE"|"NEGATIVE"|"NEUTRAL", "confidence": float, "reasoning": str}
        """
        # Fallback if no API key is set
        if not self.api_key:
            return {
                "sentiment": "NEUTRAL",
                "confidence": 0.5,
                "reasoning": "Groq API key not configured. Defaulted to NEUTRAL for safety."
            }

        if not news_headlines:
            return {
                "sentiment": "NEUTRAL",
                "confidence": 0.5,
                "reasoning": "No recent headlines found for validation."
            }

        headlines_text = "\n".join([f"- {h}" for h in news_headlines])
        
        prompt = f"""
        Analyze the following financial headlines for the Indian stock symbol '{symbol}' and classify the overall short-term fundamental sentiment.
        
        Headlines:
        {headlines_text}
        
        Respond ONLY with a valid JSON object matching this structure:
        {{
            "sentiment": "POSITIVE" or "NEGATIVE" or "NEUTRAL",
            "confidence": 0.0 to 1.0,
            "reasoning": "A concise 1-2 sentence explanation of the sentiment classification"
        }}
        """

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        data = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are a professional financial risk analyst specializing in the Indian stock market (NSE/BSE). You must output your response in JSON format."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.0,
            "response_format": {"type": "json_object"}
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(self.api_url, headers=headers, json=data)
                response.raise_for_status()
                result = response.json()
                
                # Parse the response message content
                import json
                content_str = result["choices"][0]["message"]["content"]
                parsed_res = json.loads(content_str)
                return {
                    "sentiment": parsed_res.get("sentiment", "NEUTRAL").upper(),
                    "confidence": float(parsed_res.get("confidence", 0.5)),
                    "reasoning": parsed_res.get("reasoning", "Parsed successfully.")
                }
        except Exception as e:
            return {
                "sentiment": "NEUTRAL",
                "confidence": 0.5,
                "reasoning": f"AI Sentinel request failed: {str(e)}. Defaulted to NEUTRAL."
            }
            
    def validate_signal(self, signal_type: str, sentiment_data: Dict[str, Any]) -> bool:
        """
        Risk gatekeeper: Ensures we do not buy into negative news sentiment or sell into positive sentiment.
        """
        sentiment = sentiment_data.get("sentiment", "NEUTRAL")
        confidence = sentiment_data.get("confidence", 0.0)
        
        # Risk thresholds: block if sentiment is strongly opposite to the signal direction
        if signal_type == "BUY" and sentiment == "NEGATIVE" and confidence > 0.7:
            return False  # Block buy because of high-confidence negative news
        if signal_type == "SELL" and sentiment == "POSITIVE" and confidence > 0.7:
            return False  # Block sell because of high-confidence positive news
            
        return True
