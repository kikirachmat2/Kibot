#!/usr/bin/env python3
import sys
import os
from pathlib import Path

# Add project root to sys.path
sys.path.append(os.path.abspath("SERVER_BATAM/AI_Orchestration"))
sys.path.append(os.path.abspath("SERVER_BATAM/Support"))

from kibot_ai_coordinator import query_ai

def test_intelligence():
    print("🧠 Testing AI Intelligence Expansion...")
    
    prompt = "Apa arsitektur sistem KiBot dan apa aturan 3-RETRY POLICY?"
    
    print(f"Sending prompt: {prompt}")
    
    # We use OPS_CHAT as it's flexible for general questions
    response = query_ai(
        prompt_type="OPS_CHAT",
        context={
            "governor_profile": "conservative",
            "runtime": {"uptime": "24h", "status": "active"},
            "user_message": "Apa arsitektur sistem KiBot dan apa aturan 3-RETRY POLICY?"
        },
        force_refresh=True
    )
    
    print("\n--- AI Response ---")
    print(response)
    
    if "TRINITY MESH" in str(response).upper() or "3-RETRY" in str(response).upper():
        print("\n✅ SUCCESS: AI recognized the project rules!")
    else:
        print("\n⚠️ WARNING: AI response might not be referencing the rules directly. Check templates.")

if __name__ == "__main__":
    test_intelligence()
