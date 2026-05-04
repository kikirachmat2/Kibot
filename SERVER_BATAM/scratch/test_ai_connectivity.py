import os
import sys
from pathlib import Path

# Add AI_Orchestration to path
_root = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(_root / "Batam" / "AI_Orchestration"))

import kibot_ai_coordinator
from kibot_ai_search import AISearchService

def test_ai():
    print("--- Testing AI Coordinator ---")
    print(f"GEMINI_API_KEY: {os.getenv('GEMINI_API_KEY')[:5] if os.getenv('GEMINI_API_KEY') else 'MISSING'}...")
    print(f"OPENROUTER_API_KEY: {os.getenv('OPENROUTER_API_KEY')[:5] if os.getenv('OPENROUTER_API_KEY') else 'MISSING'}...")
    try:
        # Test with a simple prompt
        context = {"user_message": "Hello KiBot, are you operational?"}
        response = kibot_ai_coordinator.query_ai(
            prompt_type="OPS_CHAT",
            context=context,
            cache_ttl_minutes=0
        )
        if response:
            print(f"AI Response: {response.get('answer')}")
            print(f"Provider used: {response.get('provider')}")
        else:
            print("AI Response failed (None)")
    except Exception as e:
        print(f"AI Test Error: {e}")

def test_search():
    print("\n--- Testing Search Service ---")
    search = AISearchService()
    
    print("Testing DuckDuckGo (No Key Required)...")
    try:
        ddg = search.ddg_search("bitcoin price news today", max_results=2)
        print(f"DDG Results: {len(ddg)} items found.")
    except Exception as e:
        print(f"DDG Error: {e}")

    print("\nTesting Tavily (Requires Key)...")
    try:
        tav = search.tavily_search("bitcoin news")
        print(f"Tavily Results: {len(tav)} items found.")
    except Exception as e:
        print(f"Tavily Error: {e}")

if __name__ == "__main__":
    test_ai()
    test_search()
