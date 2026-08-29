import asyncio
from dotenv import load_dotenv
load_dotenv()

import main

async def run():
    print("Starting automated daily swing scan...")
    result = await main.scan_market(force_refresh=True)
    print(f"Scan complete. Bullish Candidates found: {result['bullish_count']}")

if __name__ == "__main__":
    asyncio.run(run())
