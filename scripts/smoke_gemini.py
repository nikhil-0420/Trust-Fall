import asyncio
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
load_dotenv()

os.environ["LLM_DAILY_CAP"] = "100000000"

from agents.llm_gemini import GeminiLLM


async def main():
    llm = GeminiLLM(model_name="gemini-3.5-flash-lite")
    resp = await llm.complete(system="You are a helpful assistant.", prompt="Reply with the single word: Ready", purpose="smoke_test")
    print(f"Smoke test result: '{resp.strip()}'")


if __name__ == "__main__":
    asyncio.run(main())
