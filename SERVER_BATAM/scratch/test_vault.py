
import sys
import os
from pathlib import Path

# Add project root to sys.path
project_root = Path("/home/ubuntu/KiBot/SERVER_BATAM/SERVER_BATAM")
sys.path.append(str(project_root))

try:
    from Support.ki_vault import get_vault, load_sovereign_env
    
    vault = get_vault()
    print(f"Hardware ID: {vault._get_hardware_id()}")
    
    # Try to load the .env.kiv
    load_sovereign_env()
    
    # Check if some keys are loaded correctly
    for k in ["INDODAX_API_KEY", "POLYMARKET_PRIVATE_KEY"]:
        val = os.environ.get(k)
        if val:
            print(f"{k} loaded: {val[:6]}...")
        else:
            print(f"{k} NOT loaded")
            
except Exception as e:
    print(f"Error: {e}")
